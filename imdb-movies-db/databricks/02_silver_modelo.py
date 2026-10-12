# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver: limpieza y modelo de películas
# MAGIC
# MAGIC A partir de bronze construimos un modelo relacional **solo con películas**:
# MAGIC
# MAGIC ```
# MAGIC movies ──< movie_genres
# MAGIC   ├── ratings                  (1:1)
# MAGIC   ├──< movie_people >── people (reparto y equipo principal)
# MAGIC   ├──< movie_directors >── people
# MAGIC   ├──< movie_writers   >── people
# MAGIC   └──< akas                    (títulos por país / idioma)
# MAGIC ```
# MAGIC
# MAGIC Técnicas que verás: **cast** de tipos, `split` + `explode` para listas,
# MAGIC `from_json` para JSON, **left semi join** para filtrar y comprobaciones de calidad.

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def bronze(dataset: str) -> DataFrame:
    return spark.table(bronze_table(dataset)).drop("_source_file", "_ingested_at")


def save(df: DataFrame, name: str, comment: str) -> None:
    table = f"{CATALOG}.{SILVER}.{name}"
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)
    spark.sql(f"COMMENT ON TABLE {table} IS '{comment}'")
    print(f"✓ {table}: {spark.table(table).count():,} filas")


def split_list(col: str):
    """'a,b,c' -> ['a','b','c'] (null si el campo es nulo)."""
    return F.split(F.col(col), ",")

# COMMAND ----------

# MAGIC %md
# MAGIC ## movies
# MAGIC Filtramos por tipo de título y tipamos columnas. `try_cast` devuelve `null`
# MAGIC en lugar de fallar si algún valor no es numérico.

# COMMAND ----------

basics = bronze("title.basics.tsv.gz").filter(F.col("titleType").isin(TITLE_TYPES))
if not INCLUDE_ADULT:
    basics = basics.filter(F.col("isAdult") == "0")

movies = basics.select(
    F.col("tconst"),
    F.col("titleType").alias("title_type"),
    F.col("primaryTitle").alias("primary_title"),
    F.col("originalTitle").alias("original_title"),
    (F.col("isAdult") == "1").alias("is_adult"),
    F.expr("try_cast(startYear AS INT)").alias("start_year"),
    F.expr("try_cast(runtimeMinutes AS INT)").alias("runtime_minutes"),
    split_list("genres").alias("genres"),
)
save(movies, "movies", "Películas de IMDb (una fila por título)")

# A partir de aquí todo se filtra contra esta tabla
movies = spark.table(f"{CATALOG}.{SILVER}.movies")
movie_keys = movies.select("tconst")

# COMMAND ----------

# MAGIC %md
# MAGIC ## movie_genres
# MAGIC `explode` convierte un array en una fila por elemento: tabla puente película ↔ género,
# MAGIC útil para relaciones N:M en Power BI.

# COMMAND ----------

movie_genres = movies.select("tconst", F.explode("genres").alias("genre"))
save(movie_genres, "movie_genres", "Géneros de cada película (puente N:M)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## ratings
# MAGIC Un **left semi join** se queda con las filas de la izquierda que tienen pareja en la derecha,
# MAGIC sin añadir columnas: es el equivalente a `WHERE tconst IN (SELECT tconst FROM movies)`.

# COMMAND ----------

ratings = (
    bronze("title.ratings.tsv.gz")
    .join(movie_keys, "tconst", "left_semi")
    .select(
        "tconst",
        F.col("averageRating").cast("double").alias("average_rating"),
        F.col("numVotes").cast("int").alias("num_votes"),
    )
)
save(ratings, "ratings", "Valoración media y número de votos")

# COMMAND ----------

# MAGIC %md
# MAGIC ## movie_directors y movie_writers

# COMMAND ----------

crew = bronze("title.crew.tsv.gz").join(movie_keys, "tconst", "left_semi")

for role, col in (("directors", "directors"), ("writers", "writers")):
    df = crew.select("tconst", F.explode(split_list(col)).alias("nconst")).distinct()
    save(df, f"movie_{role}", f"Relación película - {role}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## movie_people (reparto y equipo principal)
# MAGIC `characters` viene como texto JSON (`["Neo"]`); lo convertimos en `array<string>`.

# COMMAND ----------

movie_people = (
    bronze("title.principals.tsv.gz")
    .join(movie_keys, "tconst", "left_semi")
    .select(
        "tconst",
        F.col("ordering").cast("int").alias("ordering"),
        "nconst",
        "category",
        "job",
        F.from_json("characters", "array<string>").alias("characters"),
    )
)
save(movie_people, "movie_people", "Reparto y equipo principal de cada película")

# COMMAND ----------

# MAGIC %md
# MAGIC ## akas (títulos alternativos)

# COMMAND ----------

akas = (
    bronze("title.akas.tsv.gz")
    .withColumnRenamed("titleId", "tconst")
    .join(movie_keys, "tconst", "left_semi")
    .select(
        "tconst",
        F.col("ordering").cast("int").alias("ordering"),
        "title",
        "region",
        "language",
        "types",
        "attributes",
        (F.col("isOriginalTitle") == "1").alias("is_original_title"),
    )
)
save(akas, "akas", "Títulos alternativos por región e idioma")

# COMMAND ----------

# MAGIC %md
# MAGIC ## people
# MAGIC Solo las personas que aparecen en alguna película (de ~14 M que tiene IMDb).

# COMMAND ----------

referenced = (
    spark.table(f"{CATALOG}.{SILVER}.movie_people").select("nconst")
    .union(spark.table(f"{CATALOG}.{SILVER}.movie_directors").select("nconst"))
    .union(spark.table(f"{CATALOG}.{SILVER}.movie_writers").select("nconst"))
    .distinct()
)

people = (
    bronze("name.basics.tsv.gz")
    .join(referenced, "nconst", "left_semi")
    .select(
        "nconst",
        F.col("primaryName").alias("primary_name"),
        F.expr("try_cast(birthYear AS INT)").alias("birth_year"),
        F.expr("try_cast(deathYear AS INT)").alias("death_year"),
        split_list("primaryProfession").alias("primary_profession"),
        split_list("knownForTitles").alias("known_for_titles"),
    )
)
save(people, "people", "Personas que participan en alguna película")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Calidad de datos
# MAGIC Comprobaciones sencillas; si alguna falla, el notebook (y el Job) se detiene.

# COMMAND ----------

def t(name: str) -> DataFrame:
    return spark.table(f"{CATALOG}.{SILVER}.{name}")


checks = {
    "movies: tconst único": t("movies").groupBy("tconst").count().filter("count > 1").count() == 0,
    "movies: título no nulo": t("movies").filter(F.col("primary_title").isNull()).count() == 0,
    "ratings: nota entre 1 y 10": t("ratings").filter(~F.col("average_rating").between(1, 10)).count() == 0,
    "movie_people: clave (tconst, ordering) única":
        t("movie_people").groupBy("tconst", "ordering").count().filter("count > 1").count() == 0,
}
for name, ok in checks.items():
    print(("✓ " if ok else "✗ ") + name)

# Personas sin ficha en name.basics: es normal que haya unas pocas, solo lo informamos
orphans = t("movie_people").join(t("people"), "nconst", "left_anti").count()
print(f"ℹ {orphans:,} participaciones con persona sin ficha en name.basics")

assert all(checks.values()), "Fallaron comprobaciones de calidad"
