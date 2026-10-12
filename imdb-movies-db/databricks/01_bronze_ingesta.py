# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze: descarga e ingesta de los datos de IMDb
# MAGIC
# MAGIC En esta capa guardamos los datos **tal y como llegan**, sin transformarlos:
# MAGIC 1. Creamos los esquemas de Unity Catalog y un **volumen** para ficheros.
# MAGIC 2. Descargamos los `.tsv.gz` oficiales de IMDb al volumen.
# MAGIC 3. Los leemos con Spark y los guardamos como **tablas Delta**, todas las columnas como texto,
# MAGIC    añadiendo columnas de auditoría (`_source_file`, `_ingested_at`).
# MAGIC
# MAGIC Así, si más adelante cambia la lógica de limpieza, podemos reprocesar silver desde bronze
# MAGIC sin volver a descargar nada.

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Esquemas y volumen
# MAGIC Un **volumen** es una carpeta gobernada por Unity Catalog para ficheros no tabulares
# MAGIC (CSV, JSON, imágenes...). Se accede con rutas `/Volumes/<catálogo>/<esquema>/<volumen>/`.

# COMMAND ----------

for schema in (BRONZE, SILVER, GOLD):
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{BRONZE}.{VOLUME}")

display(spark.sql(f"SHOW SCHEMAS IN {CATALOG} LIKE 'imdb*'"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Descarga de los ficheros
# MAGIC Se descargan ~2 GB. Si un fichero ya existe en el volumen se reutiliza
# MAGIC (pon `FORCE_DOWNLOAD = True` para traer la versión más reciente; IMDb los actualiza a diario).
# MAGIC
# MAGIC > **Si la descarga falla** (algunos workspaces restringen el acceso a Internet):
# MAGIC > descarga los ficheros en tu PC desde https://datasets.imdbws.com/ y súbelos al volumen
# MAGIC > desde **Catalog → workspace → imdb_bronze → raw_files → Upload to this volume**.
# MAGIC > Después vuelve a ejecutar este notebook: detectará que ya están.

# COMMAND ----------

import os
import shutil
import urllib.request

FORCE_DOWNLOAD = False

for name in DATASETS:
    target = f"{RAW_PATH}/{name}"
    if os.path.exists(target) and not FORCE_DOWNLOAD:
        print(f"✓ {name} ya está en el volumen")
        continue
    print(f"↓ Descargando {name}...")
    try:
        # Se descarga primero a disco local y luego se copia al volumen (escritura secuencial)
        local = f"/tmp/{name}"
        with urllib.request.urlopen(IMDB_BASE_URL + name, timeout=120) as resp, open(local, "wb") as out:
            shutil.copyfileobj(resp, out, length=8 * 1024 * 1024)
        shutil.copy(local, target)
        os.remove(local)
        print(f"✓ {name}: {os.path.getsize(target) / 1e6:,.0f} MB")
    except Exception as e:
        print(f"✗ No se pudo descargar {name}: {e}\n  → Súbelo manualmente al volumen (ver instrucciones arriba)")

display(dbutils.fs.ls(RAW_PATH))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. De fichero a tabla Delta
# MAGIC Particularidades de los TSV de IMDb que hay que indicar a Spark:
# MAGIC - Separador tabulador: `sep="\t"`.
# MAGIC - Los nulos se escriben como `\N`: `nullValue="\\N"`.
# MAGIC - **No usan comillas**; algunos títulos contienen `"` y, si Spark las interpretara, uniría
# MAGIC   líneas. Por eso desactivamos el entrecomillado con `quote=""`.
# MAGIC - Spark lee `.gz` directamente, sin descomprimir.
# MAGIC
# MAGIC No inferimos tipos (`inferSchema`): en bronze todo es `string`; el tipado se hace en silver.

# COMMAND ----------

from pyspark.sql import functions as F

missing = [d for d in DATASETS if not os.path.exists(f"{RAW_PATH}/{d}")]
assert not missing, f"Faltan ficheros en {RAW_PATH}: {missing}"


def read_imdb_tsv(path: str):
    return (
        spark.read.options(sep="\t", header=True, quote="", nullValue="\\N")
        .csv(path)
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


for name in DATASETS:
    table = bronze_table(name)
    df = read_imdb_tsv(f"{RAW_PATH}/{name}")
    (df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table))
    print(f"✓ {table}: {spark.table(table).count():,} filas")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Primer vistazo
# MAGIC Fíjate en que `title_basics` contiene **todo** IMDb (series, episodios, cortos, videojuegos...),
# MAGIC no solo películas. El filtrado lo haremos en silver.

# COMMAND ----------

display(
    spark.table(bronze_table("title.basics.tsv.gz"))
    .groupBy("titleType").count().orderBy(F.desc("count"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC **Para practicar:** cada `saveAsTable` crea una nueva versión de la tabla Delta.
# MAGIC Prueba `DESCRIBE HISTORY workspace.imdb_bronze.title_basics` en una celda SQL.
