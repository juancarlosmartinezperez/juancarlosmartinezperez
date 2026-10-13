"""Tests del parseo con HTML de ejemplo que imita la estructura de FilmAffinity.

    python -m unittest discover -s tests
"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import filmaffinity_scraper as fa  # noqa: E402

MOVIE_CARD = """
<div class="movie-card" data-movie-id="{id}">
  <div class="mc-title"><a href="https://www.filmaffinity.com/es/film{id}.html">{title}</a></div>
  <div class="d-flex"><span class="mc-year">{year}</span>
    <img class="nflag" alt="{country}" src="x.png"></div>
  {type}
  <div class="mc-director"><span class="nb"><a title="{director}" href="#">{director}</a></span></div>
  <div class="avg">{avg}</div>
</div>
"""


def card(id, title, year, country="Estados Unidos", director="Director X", avg="7,4", type=""):
    return MOVIE_CARD.format(
        id=id, title=title, year=year, country=country, director=director, avg=avg, type=type
    )


RATINGS_HTML = f"""
<html><body>
<div class="fa-content-card">
  <div class="card-header">Votada el 3 de octubre de 2024</div>
  <div class="row mb-4">{card(809297, "El padrino", 1972)}<div class="fa-user-rat-box">10</div></div>
  <div class="row mb-4">
    {card(123456, "Chernobyl", 2019, type='<div class="types-wrapper"><span class="type">Miniserie</span></div>')}
    <div class="fa-user-rat-box">9</div>
  </div>
</div>
<div class="fa-content-card">
  <div class="card-header">votada el 15 de enero de 2023</div>
  <div class="row mb-4">{card(111111, "Otra peli", 2001, avg="")}<div class="fa-user-rat-box">4</div></div>
</div>
</body></html>
"""

LISTS_HTML = """
<ul class="fa-list-group">
  <li><a class="ls-imgs" href="/es/userlist.php?user_id=5089737&list_id=1001"><img></a>
      <div class="list-name-wrapper"><a href="/es/userlist.php?user_id=5089737&list_id=1001">Favoritas</a></div></li>
  <li><div class="list-name-wrapper"><a href="/es/userlist.php?user_id=5089737&list_id=1002">Pendientes</a></div></li>
</ul>
"""

LIST_HTML = f"""
<ul class="fa-list-group">
  <li><div class="movie-wrapper">{card(809297, "El padrino", 1972)}<div class="fa-user-rat-box">10</div></div></li>
  <li><div class="movie-wrapper">{card(222222, "Sin votar", 2020)}</div></li>
</ul>
"""


class ParseTests(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(fa.parse_date("Votada el 3 de octubre de 2024"), date(2024, 10, 3))
        self.assertEqual(fa.parse_date("Rated October 3, 2024"), date(2024, 10, 3))
        self.assertIsNone(fa.parse_date("sin fecha"))

    def test_ratings_page(self):
        ratings = fa.parse_ratings_page(RATINGS_HTML)
        self.assertEqual(len(ratings), 3)
        godfather, chernobyl, other = ratings
        self.assertEqual(godfather.film_id, 809297)
        self.assertEqual(godfather.title, "El padrino")
        self.assertEqual(godfather.year, 1972)
        self.assertEqual(godfather.country, "Estados Unidos")
        self.assertEqual(godfather.directors, "Director X")
        self.assertEqual(godfather.fa_avg_rating, 7.4)
        self.assertEqual(godfather.user_rating, 10)
        self.assertEqual(godfather.rated_date, date(2024, 10, 3))
        self.assertIsNone(godfather.title_type)
        self.assertEqual(chernobyl.title_type, "Miniserie")
        self.assertEqual(other.rated_date, date(2023, 1, 15))
        self.assertIsNone(other.fa_avg_rating)

    def test_lists_page(self):
        lists = fa.parse_lists_page(LISTS_HTML)
        self.assertEqual([(l.list_id, l.list_name) for l in lists], [(1001, "Favoritas"), (1002, "Pendientes")])

    def test_list_page(self):
        items = fa.parse_list_page(LIST_HTML, list_id=1001, start_position=31)
        self.assertEqual([(i.position, i.film_id, i.user_rating) for i in items],
                         [(31, 809297, 10), (32, 222222, None)])


class FakeClient:
    """Devuelve páginas predefinidas; la última se repite como hace FilmAffinity."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def get(self, url):
        self.calls += 1
        return self.pages[min(self.calls, len(self.pages)) - 1]


class PaginationTests(unittest.TestCase):
    def test_stops_when_page_repeats(self):
        client = FakeClient([RATINGS_HTML])
        ratings = fa.fetch_ratings(1, client=client)
        self.assertEqual(len(ratings), 3)
        self.assertEqual(client.calls, 2)

    def test_stops_on_404(self):
        client = FakeClient([LIST_HTML, None])
        items = fa.fetch_list_items(1, 1001, client=client)
        self.assertEqual(len(items), 2)


if __name__ == "__main__":
    unittest.main()
