# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Configuración compartida
# MAGIC
# MAGIC El resto de notebooks lo cargan con `%run ./00_config`, así los nombres de catálogo,
# MAGIC esquemas y rutas se definen **en un único sitio**.
# MAGIC
# MAGIC **Unity Catalog** organiza los datos en tres niveles: `catálogo.esquema.tabla`.
# MAGIC Usamos un esquema por capa de la *arquitectura medallion*:
# MAGIC
# MAGIC | Capa | Esquema | Contenido |
# MAGIC | --- | --- | --- |
# MAGIC | Bronze | `imdb_bronze` | Ficheros originales y tablas tal cual llegan (todo texto) |
# MAGIC | Silver | `imdb_silver` | Datos limpios, tipados y filtrados a películas (modelo relacional) |
# MAGIC | Gold   | `imdb_gold`   | Tablas listas para análisis y reporting (agregados, KPIs) |
# MAGIC
# MAGIC > En **Databricks Free Edition** el catálogo por defecto es `workspace`. Si tu workspace
# MAGIC > tiene otro catálogo donde puedas crear esquemas, cámbialo aquí.

# COMMAND ----------

CATALOG = "workspace"
BRONZE = "imdb_bronze"
SILVER = "imdb_silver"
GOLD = "imdb_gold"

# Volumen de Unity Catalog donde se guardan los .tsv.gz descargados
VOLUME = "raw_files"
RAW_PATH = f"/Volumes/{CATALOG}/{BRONZE}/{VOLUME}"

# Ficheros oficiales de IMDb (https://developer.imdb.com/non-commercial-datasets/)
IMDB_BASE_URL = "https://datasets.imdbws.com/"
DATASETS = [
    "title.basics.tsv.gz",
    "title.ratings.tsv.gz",
    "title.crew.tsv.gz",
    "title.principals.tsv.gz",
    "title.akas.tsv.gz",
    "name.basics.tsv.gz",
]

# Qué se considera "película": movie (cine). Añade "tvMovie" o "video" si los quieres.
TITLE_TYPES = ["movie"]
INCLUDE_ADULT = False


def bronze_table(dataset: str) -> str:
    """title.basics.tsv.gz -> workspace.imdb_bronze.title_basics"""
    return f"{CATALOG}.{BRONZE}.{dataset.removesuffix('.tsv.gz').replace('.', '_')}"


print(f"Catálogo: {CATALOG} | Esquemas: {BRONZE}, {SILVER}, {GOLD} | Ficheros: {RAW_PATH}")
