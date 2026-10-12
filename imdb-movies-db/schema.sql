-- Esquema de la base de datos de películas de IMDb (SQLite)
-- Fuente: IMDb Non-Commercial Datasets (https://developer.imdb.com/non-commercial-datasets/)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS movies (
    tconst          TEXT PRIMARY KEY,     -- id IMDb (tt0000001)
    title_type      TEXT NOT NULL,        -- movie / tvMovie
    primary_title   TEXT NOT NULL,
    original_title  TEXT,
    is_adult        INTEGER NOT NULL DEFAULT 0,
    start_year      INTEGER,
    runtime_minutes INTEGER
);

CREATE TABLE IF NOT EXISTS genres (
    genre_id INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS movie_genres (
    tconst   TEXT    NOT NULL REFERENCES movies(tconst),
    genre_id INTEGER NOT NULL REFERENCES genres(genre_id),
    PRIMARY KEY (tconst, genre_id)
);

CREATE TABLE IF NOT EXISTS ratings (
    tconst         TEXT PRIMARY KEY REFERENCES movies(tconst),
    average_rating REAL    NOT NULL,
    num_votes      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    nconst             TEXT PRIMARY KEY,  -- id IMDb (nm0000001)
    primary_name       TEXT NOT NULL,
    birth_year         INTEGER,
    death_year         INTEGER,
    primary_profession TEXT               -- lista separada por comas
);

-- Reparto y equipo principal (actores, directores, guionistas, productores, compositores...)
CREATE TABLE IF NOT EXISTS movie_people (
    tconst     TEXT    NOT NULL REFERENCES movies(tconst),
    ordering   INTEGER NOT NULL,
    nconst     TEXT    NOT NULL REFERENCES people(nconst),
    category   TEXT    NOT NULL,          -- actor, actress, director, writer...
    job        TEXT,
    characters TEXT,                      -- JSON, p.ej. ["Neo"]
    PRIMARY KEY (tconst, ordering)
);

CREATE TABLE IF NOT EXISTS movie_directors (
    tconst TEXT NOT NULL REFERENCES movies(tconst),
    nconst TEXT NOT NULL REFERENCES people(nconst),
    PRIMARY KEY (tconst, nconst)
);

CREATE TABLE IF NOT EXISTS movie_writers (
    tconst TEXT NOT NULL REFERENCES movies(tconst),
    nconst TEXT NOT NULL REFERENCES people(nconst),
    PRIMARY KEY (tconst, nconst)
);

-- Títulos alternativos por país / idioma
CREATE TABLE IF NOT EXISTS akas (
    tconst            TEXT    NOT NULL REFERENCES movies(tconst),
    ordering          INTEGER NOT NULL,
    title             TEXT    NOT NULL,
    region            TEXT,
    language          TEXT,
    types             TEXT,
    attributes        TEXT,
    is_original_title INTEGER,
    PRIMARY KEY (tconst, ordering)
);

-- Vista cómoda para consultas y para conectar desde Power BI / Excel
CREATE VIEW IF NOT EXISTS v_movies AS
SELECT m.tconst,
       m.primary_title,
       m.original_title,
       m.title_type,
       m.start_year,
       m.runtime_minutes,
       m.is_adult,
       r.average_rating,
       r.num_votes,
       (SELECT group_concat(g.name, ', ')
          FROM movie_genres mg JOIN genres g ON g.genre_id = mg.genre_id
         WHERE mg.tconst = m.tconst) AS genres,
       (SELECT group_concat(p.primary_name, ', ')
          FROM movie_directors md JOIN people p ON p.nconst = md.nconst
         WHERE md.tconst = m.tconst) AS directors,
       'https://www.imdb.com/title/' || m.tconst || '/' AS imdb_url
  FROM movies m
  LEFT JOIN ratings r ON r.tconst = m.tconst;
