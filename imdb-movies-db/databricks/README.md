# IMDb en Databricks (proyecto de aprendizaje)

Construye un *lakehouse* con todas las películas de IMDb en Databricks, siguiendo la
**arquitectura medallion** (bronze → silver → gold) sobre **Delta Lake** y **Unity Catalog**.

```
datasets.imdbws.com ──► Volumen UC ──► imdb_bronze ──► imdb_silver ──► imdb_gold ──► Dashboard / Power BI
     (.tsv.gz)          raw_files      (texto tal cual)  (modelo tipado)   (KPIs)
```

| Notebook | Qué hace | Qué aprendes |
| --- | --- | --- |
| `00_config.py` | Nombres de catálogo, esquemas, rutas y parámetros | `%run`, Unity Catalog (catálogo.esquema.tabla) |
| `01_bronze_ingesta.py` | Crea esquemas y volumen, descarga los ficheros y los carga como tablas Delta | Volúmenes, `spark.read.csv`, `saveAsTable`, metadatos `_metadata` |
| `02_silver_modelo.py` | Filtra películas, tipa columnas y crea el modelo relacional | PySpark: `cast`, `split`/`explode`, `from_json`, *semi/anti joins*, calidad de datos |
| `03_gold_analitica.py` | Tabla enriquecida y agregados para reporting | Spark SQL, CTE, ventanas, `collect_list`, `CLUSTER BY` |
| `04_analisis.sql` | Consultas de análisis y funciones de Delta | Notebooks SQL, visualizaciones, `DESCRIBE HISTORY`, *time travel*, `OPTIMIZE` |

## Paso a paso

1. **Crea una cuenta gratuita** en [Databricks Free Edition](https://www.databricks.com/learn/free-edition)
   (o usa el workspace que tengas).
2. **Importa los notebooks**: *Workspace → tu carpeta → ⋮ → Import* y sube los 5 ficheros de esta
   carpeta. También puedes conectar este repositorio de GitHub con *Workspace → Create → Git folder*.
3. Revisa `00_config` (por defecto usa el catálogo `workspace`).
4. Ejecuta en orden `01` → `02` → `03` con el cómputo **Serverless**. Luego explora con `04`.

Tiempos orientativos: la descarga (~2 GB) unos minutos; bronze es la parte más pesada porque
`title.principals` tiene ~95 millones de filas.

> **Si la descarga desde Databricks falla** (acceso a Internet restringido en el workspace):
> descarga los 6 ficheros `.tsv.gz` desde <https://datasets.imdbws.com/> en tu ordenador y súbelos
> en *Catalog → workspace → imdb_bronze → raw_files → Upload to this volume*. Ejecuta antes la
> primera celda de `01` para que se creen el esquema y el volumen.

## Modelo resultante

**Silver** (`imdb_silver`): `movies`, `movie_genres`, `ratings`, `movie_directors`,
`movie_writers`, `movie_people`, `people`, `akas`.

**Gold** (`imdb_gold`):
- `movies_enriched`: una fila por película con nota, **nota ponderada** (fórmula bayesiana del
  Top 250 de IMDb), géneros, directores, reparto principal y URL.
- `stats_by_genre`, `stats_by_decade`, `top_directors`.

## Automatizarlo con un Job

*Jobs & Pipelines → Create → Job*: crea tres tareas de tipo *Notebook* (`01`, `02`, `03`), cada
una dependiente de la anterior, y prográmalo a diario. En `01` pon `FORCE_DOWNLOAD = True` para
traer siempre los datos nuevos de IMDb.

## Conectar Power BI

En Power BI Desktop: *Obtener datos → Azure Databricks* (o *Databricks*), con el *Server hostname*
y *HTTP path* de un **SQL Warehouse** (*SQL Warehouses → tu warehouse → Connection details*).
Importa las tablas de `imdb_gold`, o las de `imdb_silver` para montar tu propio modelo en estrella.

## Ejercicios propuestos

1. Incluye telefilms (`TITLE_TYPES = ["movie", "tvMovie"]`) y compara los resultados.
2. Crea en gold una tabla `top_actors` (análoga a `top_directors`) a partir de `movie_people`.
3. Convierte la ingesta bronze en una pipeline declarativa (**Lakeflow / DLT**) con *expectations*
   de calidad en lugar de los `assert` de silver.
4. Haz la carga incremental: guarda `title_ratings` diariamente con fecha y analiza qué
   películas ganan más votos (`MERGE INTO`, *Change Data Feed*).
5. Monta un **AI/BI Dashboard** con la evolución por década y el top por género.

## Licencia de los datos

Datos de [IMDb Non-Commercial Datasets](https://developer.imdb.com/non-commercial-datasets/):
uso exclusivamente personal y no comercial.
