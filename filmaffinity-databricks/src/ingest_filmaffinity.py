# Databricks notebook source
# MAGIC %md
# MAGIC # Ingesta FilmAffinity → Delta
# MAGIC
# MAGIC Descarga las votaciones y listas públicas de un usuario de FilmAffinity y las guarda en Unity Catalog:
# MAGIC
# MAGIC | Tabla | Carga | Contenido |
# MAGIC |---|---|---|
# MAGIC | `ratings` | overwrite | Estado actual de las votaciones |
# MAGIC | `ratings_history` | append | Foto de cada ejecución (`snapshot_ts`) para ver cambios de nota en el tiempo |
# MAGIC | `lists` | overwrite | Listas públicas del usuario |
# MAGIC | `list_items` | overwrite | Películas de cada lista con su posición |

# COMMAND ----------

# MAGIC %pip install -q beautifulsoup4 requests

# COMMAND ----------

dbutils.widgets.text("user_id", "5089737")
dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "filmaffinity")
dbutils.widgets.dropdown("lang", "es", ["es", "en"])
dbutils.widgets.text("delay_seconds", "2")

user_id = int(dbutils.widgets.get("user_id"))
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
lang = dbutils.widgets.get("lang")
delay = float(dbutils.widgets.get("delay_seconds"))
target = f"`{catalog}`.`{schema}`"

# COMMAND ----------

from dataclasses import asdict

from filmaffinity_scraper import Client, fetch_list_items, fetch_lists, fetch_ratings

client = Client(delay=delay)

ratings = fetch_ratings(user_id, lang, client)
print(f"Votaciones: {len(ratings)}")
if not ratings:
    # Mejor fallar que sobrescribir la tabla con 0 filas si FilmAffinity cambia su HTML o bloquea.
    raise RuntimeError(
        "No se ha descargado ninguna votación. Revisa que el perfil sea público "
        "o si FilmAffinity ha cambiado el HTML."
    )

lists = fetch_lists(user_id, lang, client)
print(f"Listas: {len(lists)}")
list_items = []
for lst in lists:
    items = fetch_list_items(user_id, lst.list_id, lang, client)
    print(f"  {lst.list_name}: {len(items)}")
    list_items.extend(items)

# COMMAND ----------

from pyspark.sql import functions as F

FILM_COLS = """
    film_id BIGINT, title STRING, year INT, country STRING, directors STRING,
    title_type STRING, fa_avg_rating DOUBLE, url STRING
"""
RATINGS_SCHEMA = FILM_COLS + ", user_rating INT, rated_date DATE"
LISTS_SCHEMA = "list_id BIGINT, list_name STRING, url STRING"
LIST_ITEMS_SCHEMA = FILM_COLS + ", list_id BIGINT, position INT, user_rating INT"


def to_df(rows, ddl):
    return (
        spark.createDataFrame([asdict(r) for r in rows], ddl)
        .withColumn("user_id", F.lit(user_id).cast("bigint"))
        .withColumn("ingested_at", F.current_timestamp())
    )


ratings_df = to_df(ratings, RATINGS_SCHEMA)
lists_df = to_df(lists, LISTS_SCHEMA)
list_items_df = to_df(list_items, LIST_ITEMS_SCHEMA)

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {target}")


def overwrite(df, table):
    (
        df.write.mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(f"{target}.`{table}`")
    )


overwrite(ratings_df, "ratings")
overwrite(lists_df, "lists")
overwrite(list_items_df, "list_items")

(
    ratings_df.withColumn("snapshot_ts", F.col("ingested_at"))
    .write.mode("append")
    .option("mergeSchema", "true")
    .saveAsTable(f"{target}.`ratings_history`")
)

# COMMAND ----------

display(
    spark.sql(f"""
        SELECT user_rating, count(*) AS n
        FROM {target}.ratings
        GROUP BY user_rating
        ORDER BY user_rating DESC
    """)
)
