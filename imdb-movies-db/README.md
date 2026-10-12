# Base de datos de películas de IMDb

Script que construye una base de datos **SQLite** con todas las películas publicadas en IMDb
(~700.000 títulos de tipo `movie`) y su información: géneros, valoraciones, reparto, directores,
guionistas, personas y títulos alternativos por país.

Los datos proceden de los [datasets oficiales no comerciales de IMDb](https://developer.imdb.com/non-commercial-datasets/),
que se actualizan a diario. **Solo pueden usarse para fines personales y no comerciales**
(ver [condiciones de IMDb](https://www.imdb.com/conditions)).

## Uso

Requisitos: Python 3.9+ (sin dependencias externas) y ~10 GB libres de disco.

```bash
cd imdb-movies-db
python build_imdb_db.py
```

El script descarga los ficheros `.tsv.gz` (~2 GB) en `data/`, filtra las películas y genera
`imdb_movies.db`. La carga completa tarda en torno a 15–30 minutos según la máquina.

| Opción | Descripción |
| --- | --- |
| `--title-types movie,tvMovie,video` | Tipos de título a incluir (por defecto `movie`) |
| `--include-adult` | Incluir títulos para adultos (excluidos por defecto) |
| `--skip-akas` | No cargar títulos alternativos (BD más pequeña y carga más rápida) |
| `--skip-download` | Reutilizar los ficheros ya presentes en `--data-dir` |
| `--force-download` | Volver a descargar para obtener los datos más recientes |
| `--db RUTA` / `--data-dir RUTA` | Ubicación de la BD y de los ficheros descargados |

## Modelo de datos

```
movies ──< movie_genres >── genres
  │
  ├── ratings                (nota media y número de votos)
  ├──< movie_people >── people   (reparto y equipo principal: actor, director, writer, producer...)
  ├──< movie_directors >── people
  ├──< movie_writers   >── people
  └──< akas                  (títulos alternativos por región / idioma)
```

- **movies**: `tconst`, `title_type`, `primary_title`, `original_title`, `is_adult`, `start_year`, `runtime_minutes`
- **ratings**: `average_rating`, `num_votes`
- **people**: `nconst`, `primary_name`, `birth_year`, `death_year`, `primary_profession`
- **movie_people**: `ordering`, `category`, `job`, `characters` (JSON)
- **akas**: `title`, `region`, `language`, `types`, `attributes`, `is_original_title`
- **v_movies** (vista): una fila por película con nota, votos, géneros, directores y URL de IMDb.

El esquema completo está en [`schema.sql`](schema.sql) y hay consultas de ejemplo en [`queries.sql`](queries.sql).

## Consultar los datos

```bash
sqlite3 imdb_movies.db < queries.sql
```

O desde Python:

```python
import sqlite3
con = sqlite3.connect("imdb_movies.db")
for row in con.execute("SELECT primary_title, average_rating FROM v_movies WHERE num_votes > 500000 ORDER BY average_rating DESC LIMIT 10"):
    print(row)
```

**Power BI / Excel**: instala el [driver ODBC de SQLite](http://www.ch-werner.de/sqliteodbc/), crea un DSN
apuntando a `imdb_movies.db` y conéctate con *Obtener datos → ODBC*. Las tablas forman un modelo en
estrella listo para relacionar (`movies` como dimensión central, `ratings` 1:1, puentes `movie_*` N:M).

## Limitaciones

- IMDb no publica en estos datasets sinopsis, presupuesto, recaudación, pósters ni reseñas.
- `movie_people` incluye solo el reparto/equipo **principal** (unas 10 personas por película).
- Para actualizar los datos basta con volver a ejecutar el script con `--force-download`.

## Databricks

En [`databricks/`](databricks/) está la versión *lakehouse* (bronze → silver → gold con Delta Lake y Unity Catalog), pensada para aprender Databricks.
