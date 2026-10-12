-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 04 · Análisis con SQL
-- MAGIC
-- MAGIC Notebook en **SQL** para explorar las tablas gold y silver y practicar funciones de Delta Lake.
-- MAGIC Si cambiaste el catálogo o los esquemas en `00_config`, ajústalos en la celda siguiente.
-- MAGIC
-- MAGIC Truco: en cada resultado puedes pulsar **+ → Visualization** para crear un gráfico y
-- MAGIC después añadirlo a un **Dashboard**.

-- COMMAND ----------

USE CATALOG workspace;
USE SCHEMA imdb_gold;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Top 25 películas (nota ponderada)

-- COMMAND ----------

SELECT primary_title, start_year, average_rating, num_votes, weighted_rating,
       array_join(directors, ', ') AS directors,
       array_join(genres, ', ')    AS genres
FROM movies_enriched
WHERE num_votes >= 25000
ORDER BY weighted_rating DESC
LIMIT 25;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Evolución por década

-- COMMAND ----------

SELECT * FROM stats_by_decade ORDER BY decade;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Mejor película de cada género (función de ventana)

-- COMMAND ----------

SELECT genre, primary_title, start_year, weighted_rating
FROM (
  SELECT g.genre, m.primary_title, m.start_year, m.weighted_rating,
         row_number() OVER (PARTITION BY g.genre ORDER BY m.weighted_rating DESC) AS rn
  FROM movies_enriched m
  LATERAL VIEW explode(m.genres) g AS genre
  WHERE m.num_votes >= 25000
)
WHERE rn = 1
ORDER BY weighted_rating DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Filmografía de un actor o actriz (modelo silver)

-- COMMAND ----------

SELECT m.primary_title, m.start_year, array_join(mp.characters, ' / ') AS personaje, r.average_rating
FROM imdb_silver.people p
JOIN imdb_silver.movie_people mp USING (nconst)
JOIN imdb_silver.movies m        USING (tconst)
LEFT JOIN imdb_silver.ratings r  USING (tconst)
WHERE p.primary_name = 'Penélope Cruz'
  AND mp.category IN ('actor', 'actress')
ORDER BY m.start_year;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Títulos en España

-- COMMAND ----------

SELECT m.primary_title, a.title AS titulo_espana, m.start_year
FROM imdb_silver.akas a
JOIN movies_enriched m USING (tconst)
WHERE a.region = 'ES' AND m.num_votes >= 500000
ORDER BY m.num_votes DESC
LIMIT 50;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Delta Lake: historial, *time travel* y mantenimiento
-- MAGIC Cada escritura crea una versión. Puedes consultar versiones anteriores con `VERSION AS OF`.

-- COMMAND ----------

DESCRIBE HISTORY movies_enriched;

-- COMMAND ----------

SELECT count(*) FROM movies_enriched VERSION AS OF 0;

-- COMMAND ----------

DESCRIBE DETAIL movies_enriched;

-- COMMAND ----------

-- Compacta ficheros pequeños y aplica el liquid clustering (CLUSTER BY start_year)
OPTIMIZE movies_enriched;
