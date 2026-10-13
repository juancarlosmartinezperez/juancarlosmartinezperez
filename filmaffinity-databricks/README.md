# FilmAffinity → Databricks

Ingesta periódica de mis votaciones y listas públicas de FilmAffinity a tablas Delta en Unity Catalog.

FilmAffinity no tiene API pública, así que el notebook descarga y parsea el HTML de las páginas públicas del perfil (`userratings.php`, `userlists.php`, `userlist.php`), con una pausa de 2 s entre peticiones.

## Estructura

```
databricks.yml                 # Asset Bundle: job semanal (lunes 07:00, Europe/Madrid)
src/filmaffinity_scraper.py    # Scraper (también se puede usar como CLI local)
src/ingest_filmaffinity.py     # Notebook: scraping + escritura en Delta
tests/test_scraper.py          # Tests del parseo con HTML de ejemplo
```

## Tablas resultantes (`main.filmaffinity` por defecto)

| Tabla | Carga | Columnas principales |
|---|---|---|
| `ratings` | overwrite | `film_id`, `title`, `year`, `country`, `directors`, `title_type`, `fa_avg_rating`, `user_rating`, `rated_date` |
| `ratings_history` | append | Igual que `ratings` + `snapshot_ts` (una foto por ejecución) |
| `lists` | overwrite | `list_id`, `list_name`, `url` |
| `list_items` | overwrite | Datos de la película + `list_id`, `position`, `user_rating` |

`title_type` vale `Serie`, `Miniserie`, `TV`… y queda vacío en las películas.

## Probar en local

```bash
pip install requests beautifulsoup4
python src/filmaffinity_scraper.py --user-id 5089737 --out ./filmaffinity_export
python -m unittest discover -s tests
```

## Desplegar en Databricks

1. Pon la URL de tu workspace en `targets.default.workspace.host` de `databricks.yml`.
2. Autentícate con el CLI: `databricks auth login --host https://<tu-workspace>...`
3. Despliega y lanza una primera ejecución:

```bash
databricks bundle validate
databricks bundle deploy
databricks bundle run filmaffinity_ingest
```

El catálogo y el esquema se cambian con variables: `databricks bundle deploy --var="catalog=mi_catalogo"`.

Si tu workspace no tiene cómputo serverless para jobs, añade un `new_cluster` a la tarea en `databricks.yml`.

## Limitaciones

- Solo se ve lo **público**: votaciones y listas privadas no aparecen.
- Depende del HTML de FilmAffinity. Si lo cambian, el job falla (no sobrescribe con 0 filas) y habrá que ajustar los selectores de `filmaffinity_scraper.py`.
- Si FilmAffinity bloquea las IPs del proveedor cloud (respuesta 403), la alternativa es ejecutar el scraper desde otra máquina y subir los CSV a un Volume de Unity Catalog.
