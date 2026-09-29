#!/usr/bin/env python3
"""Genera un catálogo de artistas y géneros a partir de la API de Last.fm."""

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://ws.audioscrobbler.com/2.0/"
DEFAULT_GENRES = ("rock", "pop", "jazz", "hip-hop", "electronic")
RETRYABLE_API_ERRORS = {8, 11, 16, 29}


class LastfmError(Exception):
    def __init__(self, method, code, message=""):
        self.code = code
        super().__init__(f"{method}: error {code} de Last.fm: {message}")


class LastfmClient:
    def __init__(self, api_key, delay=0.25, retries=3, timeout=20):
        self.api_key = api_key
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.next_request = 0.0

    def get(self, method, **params):
        query = urlencode({"method": method, "api_key": self.api_key, "format": "json", **params})
        request = Request(API_URL + "?" + query, headers={"User-Agent": "lastfm-csv-generator/1.0"})
        for attempt in range(self.retries + 1):
            remaining = self.next_request - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            self.next_request = time.monotonic() + self.delay
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise RuntimeError(f"{method}: HTTP {exc.code}") from exc
                wait = exc.headers.get("Retry-After", "")
                self._backoff(attempt, wait)
                continue
            except (URLError, TimeoutError, OSError) as exc:
                if attempt == self.retries:
                    raise RuntimeError(f"{method}: error de conexión: {exc.reason if isinstance(exc, URLError) else exc}") from exc
                self._backoff(attempt)
                continue
            except (ValueError, UnicodeError) as exc:
                raise RuntimeError(f"{method}: respuesta JSON inválida") from exc

            if not isinstance(payload, dict):
                raise RuntimeError(f"{method}: respuesta inesperada")
            if "error" in payload:
                code = int(payload["error"])
                if code in RETRYABLE_API_ERRORS and attempt < self.retries:
                    self._backoff(attempt)
                    continue
                raise LastfmError(method, code, payload.get("message", ""))
            return payload
        raise RuntimeError(f"{method}: se agotaron los reintentos")

    def _backoff(self, attempt, retry_after=""):
        try:
            seconds = min(60.0, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            seconds = min(60.0, 2 ** attempt)
        time.sleep(seconds)


def items(value):
    if isinstance(value, list):
        return value
    return [value] if isinstance(value, dict) else []


def artist_id(artist):
    mbid = str(artist.get("mbid") or "").strip().lower()
    if mbid:
        return "mbid:" + mbid
    return "name:" + str(artist.get("name") or "").strip().casefold()


def genre_id(name):
    return "tag:" + name.strip().casefold()


def parse_genres(raw):
    result = {}
    for name in raw.split(","):
        name = name.strip()
        if name:
            result.setdefault(genre_id(name), name)
    if not result:
        raise ValueError("Indica al menos un género")
    return result


def fetch_candidates(client, genres, scan_per_genre, start_page=1):
    candidates = {}
    for gid, name in genres.items():
        fetched = 0
        page = start_page
        while fetched < scan_per_genre:
            response = client.get("tag.getTopArtists", tag=name, limit=50, page=page)
            artists = items(response.get("topartists", {}).get("artist"))
            if not artists:
                break
            for artist in artists[:scan_per_genre - fetched]:
                if not artist.get("name"):
                    continue
                key = artist["name"].strip().casefold()
                candidate = candidates.setdefault(key, {"artist": artist, "seeds": set()})
                if artist.get("mbid") and not candidate["artist"].get("mbid"):
                    candidate["artist"] = artist
                candidate["seeds"].add(gid)
                fetched += 1
            if len(artists) < 50:
                break
            page += 1
    return candidates


def fetch_country_artists(client, country, country_scan):
    by_name = {}
    mbids = set()
    fetched = 0
    page = 1
    while fetched < country_scan:
        response = client.get("geo.getTopArtists", country=country, limit=50, page=page)
        chart_artists = items(response.get("topartists", {}).get("artist"))
        if not chart_artists:
            break
        for artist in chart_artists[:country_scan - fetched]:
            name = str(artist.get("name") or "").strip().casefold()
            if not name:
                continue
            mbid = str(artist.get("mbid") or "").strip().lower()
            by_name.setdefault(name, set()).add(mbid)
            if mbid:
                mbids.add(mbid)
            fetched += 1
        if len(chart_artists) < 50:
            break
        page += 1
    return by_name, mbids


def appears_in_country_chart(artist, country_artists):
    by_name, mbids = country_artists
    mbid = str(artist.get("mbid") or "").strip().lower()
    if mbid and mbid in mbids:
        return True
    name_mbids = by_name.get(str(artist.get("name") or "").strip().casefold())
    return bool(name_mbids is not None and (not mbid or not any(name_mbids) or mbid in name_mbids))


def within_popularity_limits(stats, max_listeners, max_playcount):
    for key, maximum in (("listeners", max_listeners), ("playcount", max_playcount)):
        if maximum is None:
            continue
        value = stats.get(key, stats.get("plays") if key == "playcount" else None)
        try:
            if value is None or int(value) > maximum:
                return False
        except (TypeError, ValueError):
            return False
    return True


def build_dataset(client, genres, per_genre, similar_limit,
                  max_listeners=None, max_playcount=None, scan_per_genre=None,
                  start_page=None, country=None, country_scan=500):
    popularity_filtered = max_listeners is not None or max_playcount is not None
    if scan_per_genre is None:
        scan_per_genre = per_genre * 10 if popularity_filtered or country else per_genre
    if start_page is None:
        start_page = 5 if popularity_filtered else 1
    country_artists = fetch_country_artists(client, country, country_scan) if country else None
    candidates = fetch_candidates(client, genres, scan_per_genre, start_page)
    if country_artists is not None:
        candidates = {key: candidate for key, candidate in candidates.items()
                      if appears_in_country_chart(candidate["artist"], country_artists)}
    artists = {}
    artist_genres = {}
    similar_raw = {}
    selected_per_genre = dict.fromkeys(genres, 0)
    for index, candidate in enumerate(candidates.values(), 1):
        if all(count >= per_genre for count in selected_per_genre.values()):
            break
        needed_genres = {gid for gid in candidate["seeds"] if selected_per_genre[gid] < per_genre}
        if not needed_genres:
            continue
        seed = candidate["artist"]
        print(f"[{index}/{len(candidates)}] {seed['name']}", file=sys.stderr)
        query = {"mbid": seed["mbid"]} if seed.get("mbid") else {"artist": seed["name"], "autocorrect": 1}
        try:
            info = client.get("artist.getInfo", **query).get("artist", {})
        except LastfmError as exc:
            if exc.code not in (6, 7):
                raise
            print(f"  Omitido: {exc}", file=sys.stderr)
            continue
        if not isinstance(info, dict) or not info.get("name"):
            print("  Omitido: sin ficha de artista", file=sys.stderr)
            continue
        stats = info.get("stats") or {}
        if not within_popularity_limits(stats, max_listeners, max_playcount):
            print("  Omitido: supera el límite de popularidad o faltan datos", file=sys.stderr)
            continue
        try:
            tags = client.get("artist.getTopTags", **query).get("toptags", {}).get("tag", [])
            similar = (
                client.get("artist.getSimilar", limit=similar_limit, **query).get("similarartists", {}).get("artist", [])
                if similar_limit else []
            )
        except LastfmError as exc:
            if exc.code not in (6, 7):
                raise
            print(f"  Omitido: {exc}", file=sys.stderr)
            continue
        aid = artist_id(info)
        artists[aid] = {
            "artist_id": aid,
            "name": info["name"],
            "mbid": info.get("mbid") or seed.get("mbid") or "",
            "url": info.get("url") or seed.get("url") or "",
            "listeners": stats.get("listeners", ""),
            "playcount": stats.get("playcount", stats.get("plays", "")),
        }
        seen = set()
        for tag in items(tags):
            gid = genre_id(str(tag.get("name") or ""))
            if gid in genres and gid not in seen:
                artist_genres[(aid, gid)] = {
                    "artist_id": aid, "genre_id": gid,
                    "tag_count": tag.get("count", ""), "source": "artist.getTopTags",
                }
                seen.add(gid)
        for gid in candidate["seeds"]:
            artist_genres.setdefault((aid, gid), {
                "artist_id": aid, "genre_id": gid, "tag_count": "", "source": "tag.getTopArtists",
            })
        similar_raw[aid] = items(similar)
        for gid in needed_genres:
            selected_per_genre[gid] += 1

    # Las similitudes solo apuntan a artistas presentes en artists.csv.
    by_name = {row["name"].casefold(): aid for aid, row in artists.items()}
    similar_rows = {}
    for source_id, matches in similar_raw.items():
        for match in matches:
            target_id = artist_id(match)
            if target_id not in artists:
                target_id = by_name.get(str(match.get("name") or "").casefold())
            if target_id and target_id != source_id:
                similar_rows[(source_id, target_id)] = {
                    "artist_id": source_id, "similar_artist_id": target_id,
                    "match_score": match.get("match", ""),
                }

    return {
        "artists.csv": (list(artists.values()), ["artist_id", "name", "mbid", "url", "listeners", "playcount"]),
        "genres.csv": ([{"genre_id": gid, "name": name} for gid, name in genres.items()], ["genre_id", "name"]),
        "artist_genres.csv": (list(artist_genres.values()), ["artist_id", "genre_id", "tag_count", "source"]),
        "artist_similar.csv": (list(similar_rows.values()), ["artist_id", "similar_artist_id", "match_score"]),
    }


def write_dataset(dataset, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = []
    try:
        for filename, (rows, columns) in dataset.items():
            with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", dir=output_dir, prefix=".lastfm-", delete=False) as file:
                temporary.append((Path(file.name), output_dir / filename))
                writer = csv.DictWriter(file, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
        for source, target in temporary:
            os.replace(source, target)
    finally:
        for source, _ in temporary:
            source.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genres", default=",".join(DEFAULT_GENRES), help="Géneros separados por comas")
    parser.add_argument("--country", help="País donde se escucha al artista, por ejemplo Spain")
    parser.add_argument("--country-scan", type=int, default=500, help="Artistas del ranking del país que se cruzan con los géneros (por defecto: 500)")
    parser.add_argument("--per-genre", type=int, default=20, help="Artistas aceptados por género (por defecto: 20)")
    parser.add_argument("--max-listeners", type=int, help="Excluir artistas con más oyentes que este valor")
    parser.add_argument("--max-playcount", type=int, help="Excluir artistas con más reproducciones que este valor")
    parser.add_argument("--scan-per-genre", type=int, help="Máximo de candidatos a revisar por género")
    parser.add_argument("--start-page", type=int, help="Primera página de artistas por género (5 con filtros; 1 sin filtros)")
    parser.add_argument("--similar-limit", type=int, default=10, help="Artistas similares por artista (0 desactiva esta consulta)")
    parser.add_argument("--delay", type=float, default=0.25, help="Pausa mínima entre peticiones, en segundos")
    parser.add_argument("--output", type=Path, default=Path("data"), help="Directorio de salida")
    args = parser.parse_args(argv)
    if (args.per_genre < 1 or args.similar_limit < 0 or args.delay < 0
            or args.scan_per_genre is not None and args.scan_per_genre < 1
            or args.start_page is not None and args.start_page < 1
            or args.country_scan < 1
            or args.max_listeners is not None and args.max_listeners < 0
            or args.max_playcount is not None and args.max_playcount < 0):
        parser.error("--per-genre, --scan-per-genre, --start-page y --country-scan deben ser positivos; los demás límites no pueden ser negativos")
    try:
        genres = parse_genres(args.genres)
    except ValueError as exc:
        parser.error(str(exc))
    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        parser.error("Falta LASTFM_API_KEY en el entorno")
    try:
        dataset = build_dataset(LastfmClient(api_key, delay=args.delay), genres, args.per_genre, args.similar_limit,
                                args.max_listeners, args.max_playcount, args.scan_per_genre, args.start_page,
                                args.country, args.country_scan)
        write_dataset(dataset, args.output)
    except (LastfmError, RuntimeError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    for filename, (rows, _) in dataset.items():
        print(f"{args.output / filename}: {len(rows)} filas")


if __name__ == "__main__":
    main()
