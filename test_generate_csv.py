import csv
import tempfile
import unittest
from pathlib import Path

from generate_csv import build_dataset, parse_genres, write_dataset


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, method, **params):
        self.calls.append((method, params))
        if method == "tag.getTopArtists":
            if params["tag"] == "rock":
                return {"topartists": {"artist": [
                    {"name": "Alpha", "mbid": "a"},
                    {"name": "Beta", "mbid": "b"},
                ]}}
            return {"topartists": {"artist": [
                {"name": "alpha", "mbid": "a"},
            ]}}
        artist = params["mbid"]
        if method == "artist.getInfo":
            return {"artist": {
                "name": "Alpha" if artist == "a" else "Beta",
                "mbid": artist, "url": "https://www.last.fm/music/" + artist,
                "stats": {"listeners": "100", "playcount": "500"},
            }}
        if method == "artist.getTopTags":
            return {"toptags": {"tag": [
                {"name": "rock", "count": "80"},
                {"name": "seen live", "count": "40"},
            ] if artist == "a" else []}}
        if method == "artist.getSimilar":
            return {"similarartists": {"artist": [
                {"name": "Beta", "mbid": "b", "match": "0.7"},
                {"name": "Outside", "mbid": "outside", "match": "0.9"},
            ] if artist == "a" else []}}
        raise AssertionError(method)


class GeneratorTests(unittest.TestCase):
    def test_csv_relations_and_deduplication(self):
        client = FakeClient()
        dataset = build_dataset(client, parse_genres("rock,pop"), 2, 10)
        with tempfile.TemporaryDirectory() as directory:
            write_dataset(dataset, Path(directory))
            tables = {}
            for filename in dataset:
                with (Path(directory) / filename).open(encoding="utf-8-sig", newline="") as file:
                    tables[filename] = list(csv.DictReader(file))

        self.assertEqual({row["artist_id"] for row in tables["artists.csv"]}, {"mbid:a", "mbid:b"})
        self.assertEqual({row["genre_id"] for row in tables["genres.csv"]}, {"tag:rock", "tag:pop"})
        self.assertEqual(len(tables["artist_genres.csv"]), 3)
        self.assertIn({"artist_id": "mbid:a", "genre_id": "tag:rock", "tag_count": "80", "source": "artist.getTopTags"}, tables["artist_genres.csv"])
        self.assertIn({"artist_id": "mbid:a", "genre_id": "tag:pop", "tag_count": "", "source": "tag.getTopArtists"}, tables["artist_genres.csv"])
        self.assertEqual(tables["artist_similar.csv"], [{"artist_id": "mbid:a", "similar_artist_id": "mbid:b", "match_score": "0.7"}])
        self.assertEqual(len([call for call in client.calls if call[0] == "artist.getInfo"]), 2)

    def test_popularity_limits_continue_to_next_page(self):
        class PaginatedClient:
            def __init__(self):
                self.calls = []

            def get(self, method, **params):
                self.calls.append((method, params))
                if method == "tag.getTopArtists":
                    if params["page"] == 5:
                        names = [f"Famous {number}" for number in range(50)]
                    elif params["page"] == 6:
                        names = ["Small A", "Too Many Plays", "Small B"]
                    else:
                        raise AssertionError("No se deben consultar las primeras cuatro páginas")
                    return {"topartists": {"artist": [{"name": name} for name in names]}}
                name = params["artist"]
                if method == "artist.getInfo":
                    listeners, plays = {
                        "Small A": (500, 1000),
                        "Too Many Plays": (499, 1001),
                        "Small B": (300, 900),
                    }.get(name, (10000, 10000))
                    return {"artist": {"name": name, "stats": {
                        "listeners": str(listeners), "playcount": str(plays),
                    }}}
                if method == "artist.getTopTags":
                    return {"toptags": {"tag": [{"name": "rock", "count": "10"}]}}
                raise AssertionError(method)

        client = PaginatedClient()
        dataset = build_dataset(client, parse_genres("rock"), 2, 0,
                                max_listeners=500, max_playcount=1000, scan_per_genre=53)
        self.assertEqual({row["name"] for row in dataset["artists.csv"][0]}, {"Small A", "Small B"})
        self.assertEqual(len(dataset["artist_genres.csv"][0]), 2)
        self.assertEqual(len([call for call in client.calls if call[0] == "artist.getTopTags"]), 2)
        self.assertEqual([call[1]["page"] for call in client.calls if call[0] == "tag.getTopArtists"], [5, 6])

    def test_country_chart_filters_before_artist_requests(self):
        class CountryClient(FakeClient):
            def get(self, method, **params):
                if method == "geo.getTopArtists":
                    self.calls.append((method, params))
                    self_country = params["country"]
                    if self_country != "Spain":
                        raise AssertionError(self_country)
                    return {"topartists": {"artist": [
                        {"name": "Alpha", "mbid": "a"},
                        {"name": "Beta", "mbid": "another-id"},
                    ]}}
                return super().get(method, **params)

        client = CountryClient()
        dataset = build_dataset(client, parse_genres("rock,pop"), 2, 0,
                                country="Spain", country_scan=2)
        self.assertEqual({row["artist_id"] for row in dataset["artists.csv"][0]}, {"mbid:a"})
        self.assertEqual(len([call for call in client.calls if call[0] == "artist.getInfo"]), 1)
        self.assertEqual([call[1]["page"] for call in client.calls if call[0] == "geo.getTopArtists"], [1])

    def test_empty_similar_file_has_header(self):
        dataset = build_dataset(FakeClient(), parse_genres("rock"), 1, 0)
        with tempfile.TemporaryDirectory() as directory:
            write_dataset(dataset, Path(directory))
            with (Path(directory) / "artist_similar.csv").open(encoding="utf-8-sig") as file:
                self.assertEqual(file.read().strip(), "artist_id,similar_artist_id,match_score")


if __name__ == "__main__":
    unittest.main()
