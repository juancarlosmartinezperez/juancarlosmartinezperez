# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold: tablas para análisis
# MAGIC
# MAGIC La capa gold está pensada para **consumir**: dashboards de Databricks, Power BI o SQL ad hoc.
# MAGIC
# MAGIC | Tabla | Descripción |
# MAGIC | --- | --- |
# MAGIC | `movies_enriched` | Una fila por película con nota, nota ponderada, géneros, directores y reparto principal |
# MAGIC | `stats_by_genre` | Películas, nota media y votos por género |
# MAGIC | `stats_by_decade` | Películas, duración y nota media por década |
# MAGIC | `top_directors` | Directores con más películas bien valoradas |
# MAGIC
# MAGIC Esta vez lo hacemos en **SQL** (`spark.sql`) para practicar ambos lenguajes.

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

S = f"{CATALOG}.{SILVER}"
G = f"{CATALOG}.{GOLD}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## movies_enriched
# MAGIC Incluye una **nota ponderada** (fórmula bayesiana que usaba el Top 250 de IMDb), que evita
# MAGIC que una película con 12 votos de 10 supere a *El Padrino*:
# MAGIC
# MAGIC $$WR = \frac{v}{v+m}R + \frac{m}{v+m}C$$
# MAGIC
# MAGIC `R` = nota media, `v` = votos, `m` = votos mínimos de referencia, `C` = nota media global.
# MAGIC
# MAGIC Usamos **CTE** (`WITH`) y `collect_list` / `array_sort` para agregar listas, y
# MAGIC **liquid clustering** (`CLUSTER BY`) para acelerar los filtros más comunes.

# COMMAND ----------

MIN_VOTES = 25_000

spark.sql(f"""
CREATE OR REPLACE TABLE {G}.movies_enriched
CLUSTER BY (start_year)
COMMENT 'Una fila por película con métricas y atributos principales'
AS
WITH global AS (
  SELECT avg(average_rating) AS c FROM {S}.ratings
),
directors AS (
  SELECT md.tconst, array_sort(collect_list(p.primary_name)) AS directors
  FROM {S}.movie_directors md JOIN {S}.people p USING (nconst)
  GROUP BY md.tconst
),
main_cast AS (
  -- Los 4 primeros actores/actrices según el orden de créditos
  SELECT tconst,
         transform(array_sort(collect_list(struct(ordering, primary_name))), x -> x.primary_name) AS main_cast
  FROM (
    SELECT mp.tconst, mp.ordering, p.primary_name,
           row_number() OVER (PARTITION BY mp.tconst ORDER BY mp.ordering) AS rn
    FROM {S}.movie_people mp JOIN {S}.people p USING (nconst)
    WHERE mp.category IN ('actor', 'actress', 'self')
  )
  WHERE rn <= 4
  GROUP BY tconst
)
SELECT
  m.tconst,
  m.primary_title,
  m.original_title,
  m.start_year,
  (m.start_year DIV 10) * 10                          AS decade,
  m.runtime_minutes,
  m.genres,
  r.average_rating,
  r.num_votes,
  round(
    r.num_votes / (r.num_votes + {MIN_VOTES}) * r.average_rating
    + {MIN_VOTES} / (r.num_votes + {MIN_VOTES}) * g.c, 3)  AS weighted_rating,
  d.directors,
  c.main_cast,
  concat('https://www.imdb.com/title/', m.tconst, '/') AS imdb_url
FROM {S}.movies m
LEFT JOIN {S}.ratings r USING (tconst)
LEFT JOIN directors d USING (tconst)
LEFT JOIN main_cast c USING (tconst)
CROSS JOIN global g
""")
display(spark.sql(f"SELECT * FROM {G}.movies_enriched ORDER BY weighted_rating DESC NULLS LAST LIMIT 20"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## stats_by_genre y stats_by_decade
# MAGIC La nota media "justa" se pondera por votos: `sum(nota * votos) / sum(votos)`.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {G}.stats_by_genre
COMMENT 'Indicadores por género'
AS
SELECT
  mg.genre,
  count(*)                                                        AS movies,
  round(avg(r.average_rating), 2)                                 AS avg_rating,
  round(sum(r.average_rating * r.num_votes) / sum(r.num_votes), 2) AS vote_weighted_rating,
  sum(r.num_votes)                                                AS total_votes
FROM {S}.movie_genres mg
LEFT JOIN {S}.ratings r USING (tconst)
GROUP BY mg.genre
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {G}.stats_by_decade
COMMENT 'Indicadores por década de estreno'
AS
SELECT
  decade,
  count(*)                          AS movies,
  round(avg(runtime_minutes), 1)    AS avg_runtime,
  round(avg(average_rating), 2)     AS avg_rating,
  count(average_rating)             AS rated_movies
FROM {G}.movies_enriched
WHERE decade IS NOT NULL
GROUP BY decade
""")

display(spark.sql(f"SELECT * FROM {G}.stats_by_genre ORDER BY movies DESC"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## top_directors

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {G}.top_directors
COMMENT 'Directores con al menos 3 películas con más de 10.000 votos'
AS
SELECT
  p.nconst,
  p.primary_name                         AS director,
  count(*)                               AS movies,
  round(avg(r.average_rating), 2)        AS avg_rating,
  max_by(m.primary_title, r.average_rating) AS best_movie,
  sum(r.num_votes)                       AS total_votes
FROM {S}.movie_directors md
JOIN {S}.people p  USING (nconst)
JOIN {S}.movies m  USING (tconst)
JOIN {S}.ratings r USING (tconst)
WHERE r.num_votes >= 10000
GROUP BY p.nconst, p.primary_name
HAVING count(*) >= 3
""")
display(spark.sql(f"SELECT * FROM {G}.top_directors ORDER BY avg_rating DESC LIMIT 25"))
