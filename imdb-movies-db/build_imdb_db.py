#!/usr/bin/env python3
"""Construye una base de datos SQLite con todas las películas de IMDb.

Descarga los datasets oficiales no comerciales de IMDb
(https://developer.imdb.com/non-commercial-datasets/), filtra los títulos que
son películas y carga su información (géneros, valoraciones, reparto, equipo,
directores, guionistas y títulos alternativos) en un modelo relacional.

Uso básico:
    python build_imdb_db.py                      # descarga + carga en imdb_movies.db
    python build_imdb_db.py --title-types movie,tvMovie --skip-akas
    python build_imdb_db.py --skip-download --data-dir ./data

Solo usa la biblioteca estándar de Python (3.9+).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import sqlite3
import sys
import time
import urllib.request
from itertools import islice
from pathlib import Path
from typing import Iterable, Iterator

BASE_URL = "https://datasets.imdbws.com/"
DATASETS = (
    "title.basics.tsv.gz",
    "title.ratings.tsv.gz",
    "title.crew.tsv.gz",
    "title.principals.tsv.gz",
    "title.akas.tsv.gz",
    "name.basics.tsv.gz",
)
NULL = "\\N"
BATCH_SIZE = 50_000
HERE = Path(__file__).resolve().parent

# Algunos campos de IMDb (p. ej. títulos) superan el límite por defecto del módulo csv.
csv.field_size_limit(sys.maxsize)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Descarga
# --------------------------------------------------------------------------- #
def download(data_dir: Path, names: Iterable[str], force: bool) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = data_dir / name
        if target.exists() and not force:
            log(f"{name}: ya descargado, se reutiliza")
            continue
        url = BASE_URL + name
        log(f"Descargando {url}")
        tmp = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r    {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
        print()
        tmp.replace(target)


# --------------------------------------------------------------------------- #
# Lectura de TSV
# --------------------------------------------------------------------------- #
def read_tsv(path: Path) -> Iterator[dict[str, str]]:
    """Lee un TSV de IMDb en streaming. IMDb no usa comillas: QUOTE_NONE es obligatorio."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)


def val(s: str | None) -> str | None:
    return None if s is None or s == NULL or s == "" else s


def to_int(s: str | None) -> int | None:
    s = val(s)
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def split_list(s: str | None) -> list[str]:
    s = val(s)
    return s.split(",") if s else []


def insert_batches(conn: sqlite3.Connection, sql: str, rows: Iterable[tuple]) -> int:
    it = iter(rows)
    total = 0
    while batch := list(islice(it, BATCH_SIZE)):
        conn.executemany(sql, batch)
        total += len(batch)
    return total


# --------------------------------------------------------------------------- #
# Carga
# --------------------------------------------------------------------------- #
def load_movies(conn, data_dir, title_types: set[str], include_adult: bool) -> set[str]:
    log("Cargando películas (title.basics)...")
    movie_ids: set[str] = set()
    genre_ids: dict[str, int] = {}
    movie_genres: list[tuple[str, int]] = []

    def rows():
        for r in read_tsv(data_dir / "title.basics.tsv.gz"):
            if r["titleType"] not in title_types:
                continue
            is_adult = r["isAdult"] == "1"
            if is_adult and not include_adult:
                continue
            tconst = r["tconst"]
            movie_ids.add(tconst)
            for g in split_list(r["genres"]):
                gid = genre_ids.setdefault(g, len(genre_ids) + 1)
                movie_genres.append((tconst, gid))
            yield (
                tconst,
                r["titleType"],
                r["primaryTitle"],
                val(r["originalTitle"]),
                int(is_adult),
                to_int(r["startYear"]),
                to_int(r["runtimeMinutes"]),
            )

    n = insert_batches(conn, "INSERT INTO movies VALUES (?,?,?,?,?,?,?)", rows())
    conn.executemany("INSERT INTO genres VALUES (?,?)", [(i, g) for g, i in genre_ids.items()])
    conn.executemany("INSERT INTO movie_genres VALUES (?,?)", movie_genres)
    conn.commit()
    log(f"  {n:,} películas, {len(genre_ids)} géneros")
    return movie_ids


def load_ratings(conn, data_dir, movie_ids: set[str]) -> None:
    log("Cargando valoraciones (title.ratings)...")
    rows = (
        (r["tconst"], float(r["averageRating"]), int(r["numVotes"]))
        for r in read_tsv(data_dir / "title.ratings.tsv.gz")
        if r["tconst"] in movie_ids
    )
    n = insert_batches(conn, "INSERT INTO ratings VALUES (?,?,?)", rows)
    conn.commit()
    log(f"  {n:,} valoraciones")


def load_crew(conn, data_dir, movie_ids: set[str], person_ids: set[str]) -> None:
    log("Cargando directores y guionistas (title.crew)...")
    directors: list[tuple[str, str]] = []
    writers: list[tuple[str, str]] = []
    for r in read_tsv(data_dir / "title.crew.tsv.gz"):
        tconst = r["tconst"]
        if tconst not in movie_ids:
            continue
        for n in dict.fromkeys(split_list(r["directors"])):
            directors.append((tconst, n))
            person_ids.add(n)
        for n in dict.fromkeys(split_list(r["writers"])):
            writers.append((tconst, n))
            person_ids.add(n)
    insert_batches(conn, "INSERT INTO movie_directors VALUES (?,?)", directors)
    insert_batches(conn, "INSERT INTO movie_writers VALUES (?,?)", writers)
    conn.commit()
    log(f"  {len(directors):,} relaciones de dirección, {len(writers):,} de guion")


def load_principals(conn, data_dir, movie_ids: set[str], person_ids: set[str]) -> None:
    log("Cargando reparto y equipo principal (title.principals)...")

    def rows():
        for r in read_tsv(data_dir / "title.principals.tsv.gz"):
            if r["tconst"] not in movie_ids:
                continue
            person_ids.add(r["nconst"])
            yield (
                r["tconst"],
                int(r["ordering"]),
                r["nconst"],
                r["category"],
                val(r["job"]),
                val(r["characters"]),
            )

    n = insert_batches(conn, "INSERT INTO movie_people VALUES (?,?,?,?,?,?)", rows())
    conn.commit()
    log(f"  {n:,} participaciones")


def load_akas(conn, data_dir, movie_ids: set[str]) -> None:
    log("Cargando títulos alternativos (title.akas)...")
    rows = (
        (
            r["titleId"],
            int(r["ordering"]),
            r["title"],
            val(r["region"]),
            val(r["language"]),
            val(r["types"]),
            val(r["attributes"]),
            to_int(r["isOriginalTitle"]),
        )
        for r in read_tsv(data_dir / "title.akas.tsv.gz")
        if r["titleId"] in movie_ids
    )
    n = insert_batches(conn, "INSERT OR IGNORE INTO akas VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    log(f"  {n:,} títulos alternativos")


def load_people(conn, data_dir, person_ids: set[str]) -> None:
    log("Cargando personas (name.basics)...")
    rows = (
        (
            r["nconst"],
            r["primaryName"],
            to_int(r["birthYear"]),
            to_int(r["deathYear"]),
            val(r["primaryProfession"]),
        )
        for r in read_tsv(data_dir / "name.basics.tsv.gz")
        if r["nconst"] in person_ids
    )
    n = insert_batches(conn, "INSERT INTO people VALUES (?,?,?,?,?)", rows)

    # Elimina relaciones con personas que IMDb ya no publica, para mantener la integridad.
    orphans = 0
    for table in ("movie_people", "movie_directors", "movie_writers"):
        cur = conn.execute(
            f"DELETE FROM {table} WHERE nconst NOT IN (SELECT nconst FROM people)"
        )
        orphans += cur.rowcount
    conn.commit()
    log(f"  {n:,} personas ({orphans:,} relaciones huérfanas eliminadas)")


def create_indexes(conn) -> None:
    log("Creando índices...")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS ix_movies_year    ON movies(start_year);
        CREATE INDEX IF NOT EXISTS ix_movies_title   ON movies(primary_title);
        CREATE INDEX IF NOT EXISTS ix_ratings_votes  ON ratings(num_votes);
        CREATE INDEX IF NOT EXISTS ix_mg_genre       ON movie_genres(genre_id);
        CREATE INDEX IF NOT EXISTS ix_mp_nconst      ON movie_people(nconst);
        CREATE INDEX IF NOT EXISTS ix_mp_category    ON movie_people(category);
        CREATE INDEX IF NOT EXISTS ix_md_nconst      ON movie_directors(nconst);
        CREATE INDEX IF NOT EXISTS ix_mw_nconst      ON movie_writers(nconst);
        CREATE INDEX IF NOT EXISTS ix_people_name    ON people(primary_name);
        CREATE INDEX IF NOT EXISTS ix_akas_title     ON akas(title);
        CREATE INDEX IF NOT EXISTS ix_akas_region    ON akas(region);
        """
    )
    conn.commit()


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=HERE / "imdb_movies.db", help="fichero SQLite de salida")
    p.add_argument("--data-dir", type=Path, default=HERE / "data", help="carpeta de los .tsv.gz")
    p.add_argument(
        "--title-types",
        default="movie",
        help="tipos de título a incluir, separados por comas (p. ej. movie,tvMovie,video)",
    )
    p.add_argument("--include-adult", action="store_true", help="incluir títulos para adultos")
    p.add_argument("--skip-akas", action="store_true", help="no cargar títulos alternativos (más rápido)")
    p.add_argument("--skip-download", action="store_true", help="usar los ficheros ya presentes en --data-dir")
    p.add_argument("--force-download", action="store_true", help="volver a descargar aunque existan")
    args = p.parse_args(argv)

    needed = [d for d in DATASETS if not (args.skip_akas and d == "title.akas.tsv.gz")]
    if not args.skip_download:
        download(args.data_dir, needed, args.force_download)
    missing = [d for d in needed if not (args.data_dir / d).exists()]
    if missing:
        p.error(f"faltan ficheros en {args.data_dir}: {', '.join(missing)}")

    start = time.time()
    tmp_db = args.db.with_suffix(args.db.suffix + ".building")
    tmp_db.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp_db)
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    # Carga masiva: las FK se validan al final borrando huérfanos.
    conn.executescript(
        "PRAGMA foreign_keys = OFF; PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;"
    )

    title_types = {t.strip() for t in args.title_types.split(",") if t.strip()}
    movie_ids = load_movies(conn, args.data_dir, title_types, args.include_adult)
    person_ids: set[str] = set()
    load_ratings(conn, args.data_dir, movie_ids)
    load_crew(conn, args.data_dir, movie_ids, person_ids)
    load_principals(conn, args.data_dir, movie_ids, person_ids)
    if not args.skip_akas:
        load_akas(conn, args.data_dir, movie_ids)
    load_people(conn, args.data_dir, person_ids)
    create_indexes(conn)
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    tmp_db.replace(args.db)
    size_mb = args.db.stat().st_size / 1e6
    log(f"Base de datos lista: {args.db} ({size_mb:,.0f} MB) en {time.time() - start:,.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
