"""hard_source (mocked HTTP only) and build.py (fake DB connection only)."""

import gzip
import json
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from shapely.geometry import Polygon, mapping

from ingestion.areas import build, hard_source
from ingestion.areas.faces import Face
from ingestion.areas.osm_source import SAMPLE_BBOX, Projector, cache_path

FIXTURE = Path(__file__).parent / "fixtures" / "areas_hard_sample.json"


# -------------------------------------------------------------- hard_source


def way(wid, tags, pts, nodes=None):
    return {
        "type": "way",
        "id": wid,
        "tags": tags,
        "nodes": nodes if nodes is not None else list(range(wid * 10, wid * 10 + len(pts))),
        "geometry": [{"lat": a, "lon": b} for a, b in pts],
    }


ELEMENTS = {
    "elements": [
        way(1, {"highway": "secondary", "name": "A St"}, [(40.7, -74.0), (40.71, -74.0)]),
        way(2, {"highway": "residential", "name": "Elm"}, [(40.7, -74.0), (40.7, -74.01)]),
        way(3, {"highway": "primary", "tunnel": "yes"}, [(40.7, -74.0), (40.72, -74.0)]),
        way(4, {"highway": "trunk_link", "bridge": "viaduct"}, [(40.7, -74.0), (40.7, -73.99)]),
        way(5, {"natural": "coastline"}, [(40.69, -74.02), (40.69, -74.0)]),
        way(6, {"railway": "rail"}, [(40.7, -74.0), (40.7, -73.98)]),
        way(7, {"highway": "motorway", "area": "yes"}, [(40.7, -74.0), (40.7, -73.97)]),
    ]
}


def test_hard_highway_set_uses_weights():
    assert hard_source.HARD_HIGHWAYS == {
        "motorway", "motorway_link", "trunk", "trunk_link",
        "primary", "primary_link", "secondary", "secondary_link",
    }  # fmt: skip


def test_parse_hard_filters_and_flags():
    proj = Projector(40.7, -74.0)
    roads, coast = hard_source.parse_hard(ELEMENTS, proj)
    assert [r.id for r in roads] == [1, 4]
    assert roads[1].bridge and not roads[0].bridge
    assert len(coast) == 1 and coast[0][0][0] < coast[0][1][0]  # direction kept (west->east)
    roads_rail, _ = hard_source.parse_hard(ELEMENTS, proj, include_rail=True)
    assert [r.id for r in roads_rail] == [1, 4, 6]


def test_region_tiles_cover_union_bbox_plus_margin():
    bbox = hard_source.region_bbox()
    s, w, n, e = bbox
    assert s == pytest.approx(39.80) and n == pytest.approx(42.05)
    assert w == pytest.approx(-75.25) and e == pytest.approx(-71.80)
    tiles = hard_source.tile_bboxes(bbox)
    assert 6 <= len(tiles) <= 12
    assert min(t[0] for t in tiles) == s and max(t[2] for t in tiles) == n
    assert min(t[1] for t in tiles) == w and max(t[3] for t in tiles) == e


def test_tile_query_contents():
    q = hard_source.build_tile_query((40.0, -74.0, 40.5, -73.5))
    assert "(40.0,-74.0,40.5,-73.5)" in q
    assert 'way["natural"="coastline"]' in q and "secondary" in q and "motorway_link" in q
    assert "residential" not in q and "tertiary" not in q and "railway" not in q
    assert 'way["railway"="rail"]' in hard_source.build_tile_query((0, 0, 1, 1), include_rail=True)
    assert "out geom;" in q


def test_fetch_refuses_network_by_default(tmp_path):
    def post(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("network touched")

    tile = (40.0, -74.0, 40.5, -73.5)
    with pytest.raises(hard_source.NetworkNotAllowed):
        hard_source.fetch_tile(tile, tmp_path, post=post)
    with pytest.raises(hard_source.NetworkNotAllowed):
        hard_source.fetch_region(hard_source.region_bbox(), tmp_path, post=post)


def test_fetch_tile_mocked_http_and_cache(tmp_path):
    calls = []

    def post(query, timeout):
        calls.append((query, timeout))
        return ELEMENTS

    tile = (40.0, -74.0, 40.5, -73.5)
    d1 = hard_source.fetch_tile(tile, tmp_path, allow_network=True, post=post)
    assert d1 == ELEMENTS and len(calls) == 1
    assert hard_source.tile_cache_path(tile, tmp_path).exists()
    d2 = hard_source.fetch_tile(tile, tmp_path, allow_network=False, post=post)  # cached
    assert d2 == ELEMENTS and len(calls) == 1


def test_fetch_region_merges_tiles_and_dedupes(tmp_path):
    calls = []

    def post(query, timeout):
        calls.append(query)
        return ELEMENTS

    data = hard_source.fetch_region(
        hard_source.region_bbox(), tmp_path, allow_network=True, post=post
    )
    assert len(calls) == 9
    assert len(data["elements"]) == len(ELEMENTS["elements"])  # same ways in every tile


# ------------------------------------------------------------------ build.py


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.log.append(("execute", sql, params))
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("boom")
        self._rows = self.conn.rows if sql.startswith("select") else []

    def executemany(self, sql, rows):
        rows = list(rows)
        self.conn.log.append(("executemany", sql, rows))

    def __iter__(self):
        return iter(self._rows)


class FakeConn:
    def __init__(self, rows=(), fail_on=None):
        self.log, self.rows, self.fail_on = [], list(rows), fail_on

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))


def make_numbered():
    sq = Polygon([(-74.0, 40.70), (-73.99, 40.70), (-73.99, 40.71), (-74.0, 40.71)])
    f1 = Face(sq, ("Main St",), 1_000_000.0, (40.70, 40.71, -74.0, -73.99), (("dr5reg", 600000.0), ("dr5ref", 400000.0)))
    f2 = Face(Polygon([(0, 0), (1, 0), (1, 1)]), (), 2.0, (1.0, 2.0, 3.0, 4.0), ())
    return [(1, f1), (2, f2)]


def test_write_areas_single_transaction_sequence():
    conn = FakeConn()
    res = build.write_areas(conn, make_numbered(), "areas-v1-test")
    kinds = [e[0] for e in conn.log]
    assert kinds == ["execute", "execute", "executemany", "executemany", "commit"]
    assert conn.log[0][1] == "delete from area_cells"
    assert conn.log[1][1] == "delete from areas"
    assert conn.log[2][1].startswith("insert into areas")
    assert conn.log[3][1].startswith("insert into area_cells")
    area_rows, cell_rows = conn.log[2][2], conn.log[3][2]
    assert [r[0] for r in area_rows] == [1, 2] and area_rows[0][1] == "areas-v1-test"
    assert area_rows[0][2] == "nyc" and area_rows[1][2] is None
    assert area_rows[0][9] == ["Main St"] and area_rows[0][7] == 1_000_000.0
    assert area_rows[0][8].obj == mapping(make_numbered()[0][1].geometry)
    assert cell_rows == [(1, "dr5reg", 600000.0), (1, "dr5ref", 400000.0)]
    assert res == {"areas": 2, "area_cells": 2}


def test_write_areas_rolls_back_on_error():
    conn = FakeConn(fail_on="delete from areas")
    with pytest.raises(RuntimeError):
        build.write_areas(conn, make_numbered(), "v")
    assert conn.log[-1] == ("rollback",)
    assert ("commit",) not in conn.log


def test_write_areas_refuses_empty_build():
    conn = FakeConn()
    with pytest.raises(ValueError):
        build.write_areas(conn, [], "v")
    assert conn.log == []


def test_read_geohashes_is_a_plain_select():
    conn = FakeConn(rows=[{"geohash": "dr5reg"}, {"geohash": "dr5ref"}])
    assert build.read_geohashes(conn) == frozenset({"dr5reg", "dr5ref"})
    assert [e[1] for e in conn.log] == ["select geohash from geo_entities"]


def test_cli_write_requires_region_source():
    with pytest.raises(SystemExit):
        build.main(["--write"])


def test_cli_region_without_allow_network_refuses(tmp_path):
    with pytest.raises(hard_source.NetworkNotAllowed):
        build.main(["--source", "region", "--cache-dir", str(tmp_path), "--out-dir", str(tmp_path / "o")])


def test_cli_dry_run_on_cached_sample(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    data = json.loads(FIXTURE.read_text())
    with gzip.open(cache_path(SAMPLE_BBOX, cache), "wt", encoding="utf-8") as f:
        json.dump({"elements": data["elements"]}, f)
    out = tmp_path / "out"
    assert build.main(["--cache-dir", str(cache), "--out-dir", str(out)]) == 0
    gj = json.loads((out / "areas.geojson").read_text())
    metrics = json.loads((out / "metrics.json").read_text())
    assert len(gj["features"]) == metrics["face_count"] > 100
    assert [ft["id"] for ft in gj["features"]] == list(range(1, metrics["face_count"] + 1))
    assert (out / "areas_preview.png").stat().st_size > 1000
    assert metrics.get("faces_over_water", 0) == 0
