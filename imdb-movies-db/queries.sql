-- Consultas de ejemplo sobre imdb_movies.db

-- 1. Top 20 películas mejor valoradas (mínimo 100.000 votos)
SELECT primary_title, start_year, average_rating, num_votes, genres, directors
  FROM v_movies
 WHERE num_votes >= 100000
 ORDER BY average_rating DESC, num_votes DESC
 LIMIT 20;

-- 2. Número de películas y nota media por década
SELECT (m.start_year / 10) * 10 AS decada,
       COUNT(*)                 AS peliculas,
       ROUND(AVG(r.average_rating), 2) AS nota_media
  FROM movies m LEFT JOIN ratings r USING (tconst)
 WHERE m.start_year IS NOT NULL
 GROUP BY decada
 ORDER BY decada;

-- 3. Películas por género
SELECT g.name AS genero, COUNT(*) AS peliculas
  FROM movie_genres mg JOIN genres g USING (genre_id)
 GROUP BY g.name
 ORDER BY peliculas DESC;

-- 4. Filmografía de un actor/actriz
SELECT m.primary_title, m.start_year, mp.characters, r.average_rating
  FROM people p
  JOIN movie_people mp USING (nconst)
  JOIN movies m        USING (tconst)
  LEFT JOIN ratings r  USING (tconst)
 WHERE p.primary_name = 'Keanu Reeves'
   AND mp.category IN ('actor', 'actress')
 ORDER BY m.start_year;

-- 5. Directores con más películas de nota >= 8 (mínimo 25.000 votos)
SELECT p.primary_name, COUNT(*) AS peliculas
  FROM movie_directors md
  JOIN people p  USING (nconst)
  JOIN ratings r USING (tconst)
 WHERE r.average_rating >= 8 AND r.num_votes >= 25000
 GROUP BY p.nconst
 ORDER BY peliculas DESC
 LIMIT 20;

-- 6. Título con el que se estrenó en España
SELECT m.primary_title, a.title AS titulo_es
  FROM movies m JOIN akas a USING (tconst)
 WHERE a.region = 'ES'
   AND m.primary_title LIKE '%Shawshank%';
