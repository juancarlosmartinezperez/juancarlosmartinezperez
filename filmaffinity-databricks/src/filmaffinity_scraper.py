"""Scraper de las páginas públicas de un usuario de FilmAffinity.

FilmAffinity no ofrece API, así que se parsea el HTML de:
  - userratings.php  -> votaciones (con fecha de voto)
  - userlists.php    -> listas públicas del usuario
  - userlist.php     -> películas de cada lista

Las funciones parse_* trabajan sobre HTML ya descargado (testeables sin red);
las fetch_* se encargan de paginar con pausas entre peticiones.

Uso local:
    python filmaffinity_scraper.py --user-id 5089737 --out ./export
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Callable, Iterator, Optional

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.filmaffinity.com/{lang}/"
RATINGS_URL = BASE_URL + "userratings.php?user_id={user_id}&p={page}&orderby=rating-date&chv=list"
LISTS_URL = BASE_URL + "userlists.php?user_id={user_id}&p={page}"
LIST_URL = BASE_URL + "userlist.php?user_id={user_id}&list_id={list_id}&page={page}"

DEFAULT_DELAY = 2.0  # segundos entre peticiones, para no saturar FilmAffinity
MAX_PAGES = 1000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}

MONTHS = {
    # es
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    # en
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

FILM_ID_RE = re.compile(r"film(\d+)\.html")
LIST_ID_RE = re.compile(r"list_id=(\d+)")


class ScraperError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #


@dataclass
class Film:
    film_id: Optional[int]
    title: str
    year: Optional[int]
    country: Optional[str]
    directors: Optional[str]
    title_type: Optional[str]  # "Serie", "Miniserie", "TV"... None si es película
    fa_avg_rating: Optional[float]
    url: Optional[str]


@dataclass
class Rating(Film):
    user_rating: Optional[int]
    rated_date: Optional[date]


@dataclass
class UserList:
    list_id: int
    list_name: str
    url: str


@dataclass
class ListItem(Film):
    list_id: int
    position: int
    user_rating: Optional[int]


# --------------------------------------------------------------------------- #
# Helpers de parseo
# --------------------------------------------------------------------------- #


def _text(tag: Optional[Tag]) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def _to_int(value: str) -> Optional[int]:
    m = re.search(r"\d+", value or "")
    return int(m.group()) if m else None


def _to_float(value: str) -> Optional[float]:
    m = re.search(r"\d+(?:[.,]\d+)?", value or "")
    return float(m.group().replace(",", ".")) if m else None


def parse_date(text: str) -> Optional[date]:
    """'votada el 3 de octubre de 2024' / 'Rated October 3, 2024' -> date."""
    t = (text or "").lower()
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", t)
    if m:
        day, month, year = m.groups()
    else:
        m = re.search(r"([a-z]+)\s+(\d{1,2}),\s*(\d{4})", t)
        if not m:
            return None
        month, day, year = m.groups()
    month_num = MONTHS.get(month)
    if not month_num:
        return None
    return date(int(year), month_num, int(day))


def parse_film_card(card: Tag) -> Film:
    """Extrae los datos comunes de una ficha de película (div.movie-card o similar)."""
    title_link = card.select_one(".mc-title a")
    if title_link is None:
        raise ScraperError("Ficha sin .mc-title a")

    href = title_link.get("href") or ""
    film_id = card.get("data-movie-id") or (
        FILM_ID_RE.search(href).group(1) if FILM_ID_RE.search(href) else None
    )

    directors = []
    for d in card.select(".mc-director a"):
        name = (d.get("title") or d.get_text(strip=True)).strip()
        if name and name not in directors:
            directors.append(name)

    flag = card.select_one("img.nflag")
    type_tag = card.select_one(".types-wrapper .type") or card.select_one(".type")

    return Film(
        film_id=int(film_id) if film_id else None,
        title=title_link.get_text(strip=True),
        year=_to_int(_text(card.select_one(".mc-year"))),
        country=((flag.get("alt") or "").strip() or None) if flag else None,
        directors=", ".join(directors) or None,
        title_type=_text(type_tag) or None,
        fa_avg_rating=_to_float(_text(card.select_one(".avg"))),
        url=href or None,
    )


def _film_card_in(container: Tag) -> Tag:
    return (
        container.select_one("[data-movie-id]")
        or container.select_one(".movie-card")
        or container
    )


# --------------------------------------------------------------------------- #
# Parsers de página
# --------------------------------------------------------------------------- #


def parse_ratings_page(html: str) -> list[Rating]:
    """Página de userratings.php ordenada por fecha: un bloque por día de voto."""
    soup = BeautifulSoup(html, "html.parser")
    ratings: list[Rating] = []
    for day_block in soup.select(".fa-content-card"):
        rated = parse_date(_text(day_block.select_one(".card-header")))
        for row in day_block.select(".row.mb-4"):
            rat_box = row.select_one(".fa-user-rat-box")
            if rat_box is None or row.select_one(".mc-title a") is None:
                continue
            film = parse_film_card(_film_card_in(row))
            ratings.append(
                Rating(**asdict(film), user_rating=_to_int(_text(rat_box)), rated_date=rated)
            )
    return ratings


def parse_lists_page(html: str) -> list[UserList]:
    """Página de userlists.php: enlaces a userlist.php?...&list_id=N."""
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[int, UserList] = {}
    for a in soup.select("a[href*='list_id=']"):
        href = a.get("href") or ""
        m = LIST_ID_RE.search(href)
        name = a.get_text(" ", strip=True)
        if not m or not name or "userlist.php" not in href:
            continue
        list_id = int(m.group(1))
        seen.setdefault(list_id, UserList(list_id=list_id, list_name=name, url=href))
    return list(seen.values())


def parse_list_page(html: str, list_id: int, start_position: int = 1) -> list[ListItem]:
    """Página de userlist.php: películas de una lista, en su orden."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[ListItem] = []
    containers = soup.select(".movie-wrapper") or soup.select("ul.fa-list-group > li")
    for container in containers:
        if container.select_one(".mc-title a") is None:
            continue
        film = parse_film_card(_film_card_in(container))
        # La nota del usuario puede estar fuera de .movie-wrapper, dentro del mismo <li>.
        scope = container.find_parent("li") or container
        items.append(
            ListItem(
                **asdict(film),
                list_id=list_id,
                position=start_position + len(items),
                user_rating=_to_int(_text(scope.select_one(".fa-user-rat-box"))),
            )
        )
    return items


# --------------------------------------------------------------------------- #
# Descarga con paginación
# --------------------------------------------------------------------------- #


class Client:
    def __init__(self, delay: float = DEFAULT_DELAY, max_retries: int = 4):
        self.delay = delay
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last_request = 0.0

    def get(self, url: str) -> Optional[str]:
        """Devuelve el HTML, o None si la página no existe (fin de paginación)."""
        backoff = 30.0
        for attempt in range(self.max_retries):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries - 1:
                    break
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code == 403:
                raise ScraperError(
                    f"FilmAffinity ha devuelto 403 en {url}. Puede estar bloqueando la IP "
                    "de origen (habitual en IPs de nube)."
                )
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        raise ScraperError(f"FilmAffinity no responde tras {self.max_retries} intentos: {url}")


def _paginate(
    client: Client,
    url_for_page: Callable[[int], str],
    parse: Callable[[str, int], list],
    key: Callable[[object], object],
) -> Iterator:
    """Recorre páginas hasta que una no exista o no aporte elementos nuevos.

    FilmAffinity a veces repite la última página en vez de devolver 404, por eso
    se corta también cuando todos los elementos ya se habían visto.
    """
    seen: set = set()
    for page in range(1, MAX_PAGES + 1):
        html = client.get(url_for_page(page))
        if html is None:
            return
        new = [x for x in parse(html, len(seen)) if key(x) not in seen]
        if not new:
            return
        for x in new:
            seen.add(key(x))
            yield x
    raise ScraperError(f"Se alcanzó el límite de {MAX_PAGES} páginas")


def fetch_ratings(user_id: int, lang: str = "es", client: Optional[Client] = None) -> list[Rating]:
    client = client or Client()
    return list(
        _paginate(
            client,
            lambda p: RATINGS_URL.format(lang=lang, user_id=user_id, page=p),
            lambda html, _: parse_ratings_page(html),
            key=lambda r: (r.film_id, r.title, r.year),
        )
    )


def fetch_lists(user_id: int, lang: str = "es", client: Optional[Client] = None) -> list[UserList]:
    client = client or Client()
    return list(
        _paginate(
            client,
            lambda p: LISTS_URL.format(lang=lang, user_id=user_id, page=p),
            lambda html, _: parse_lists_page(html),
            key=lambda lst: lst.list_id,
        )
    )


def fetch_list_items(
    user_id: int, list_id: int, lang: str = "es", client: Optional[Client] = None
) -> list[ListItem]:
    client = client or Client()
    return list(
        _paginate(
            client,
            lambda p: LIST_URL.format(lang=lang, user_id=user_id, list_id=list_id, page=p),
            lambda html, n_seen: parse_list_page(html, list_id, start_position=n_seen + 1),
            key=lambda it: (it.film_id, it.title, it.year),
        )
    )


# --------------------------------------------------------------------------- #
# CLI local
# --------------------------------------------------------------------------- #


def _write_csv(rows: list, path: Path) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[f.name for f in fields(rows[0])])
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta votaciones y listas de FilmAffinity")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--lang", default="es", choices=["es", "en"])
    parser.add_argument("--out", type=Path, default=Path("filmaffinity_export"))
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args()

    client = Client(delay=args.delay)
    args.out.mkdir(parents=True, exist_ok=True)

    ratings = fetch_ratings(args.user_id, args.lang, client)
    print(f"Votaciones: {len(ratings)}")
    lists = fetch_lists(args.user_id, args.lang, client)
    print(f"Listas: {len(lists)}")
    items: list[ListItem] = []
    for lst in lists:
        lst_items = fetch_list_items(args.user_id, lst.list_id, args.lang, client)
        print(f"  {lst.list_name}: {len(lst_items)}")
        items.extend(lst_items)

    _write_csv(ratings, args.out / "ratings.csv")
    _write_csv(lists, args.out / "lists.csv")
    _write_csv(items, args.out / "list_items.csv")
    (args.out / "summary.json").write_text(
        json.dumps({"ratings": len(ratings), "lists": len(lists), "list_items": len(items)}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
