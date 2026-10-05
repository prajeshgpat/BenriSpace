"""api/point_score.py (DB wiring on a fake connection) and the precision=point routes."""

from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import main, point_score
from api.areas import AGGREGATE_COLUMNS
from api.point_score import PointResult, PointScoringError
from common.geo import encode as geohash_encode
from scoring.engine import WEIGHTS_VERSION_V2_1
from scoring.scales import compute_scales, scales_to_rows
from tests.test_scales import make_rows

VERSION = WEIGHTS_VERSION_V2_1
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_cache():
    point_score.clear_scales_cache()
    yield
    point_score.clear_scales_cache()


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.log.append(("execute", sql, params))
        self.rows = self.conn.handler(sql, params)

    def executemany(self, sql, rows):
        self.conn.log.append(("executemany", sql, list(rows)))

    def fetchall(self):
        self.conn.log.append(("fetch", None, None))
        return list(self.rows)


class FakeConn:
    def __init__(self, handler):
        self.handler = handler
        self.log = []
        self.rolled_back = 0

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rolled_back += 1

    def commit(self):
        pass

    def kinds(self):
        return [k for k, _, _ in self.log]


CELL_ID = uuid4()


def cell_row(geohash="dr5reg", lat=40.70, lon=-73.99, metro="nyc"):
    return {
        "id": CELL_ID, "geohash": geohash, "latitude": lat, "longitude": lon,
        "formatted_address": None, "metro_area": metro, "neighborhood": "Somewhere, NYC",
        "grocery_count_500m": 3, "grocery_nearest_m": 120.0, "shopping_raw": 0.5,
        "shopping_variety_count_1mi": 3, "park_nearest_ft": 900.0,
        "park_largest_sq_ft_half_mi": 50_000.0, "school_district_name": "D1",
        "congestion_proxy_raw": 5.0, "emergency_corridor_facility_raw": 4.0,
        "street_orientation": "unknown",
    }  # fmt: skip


def live_rows(index=0):
    cats = (
        "grocery", "gym", "cafe", "restaurant", "bar", "gas_station", "convenience_store",
        "transit", "school", "shopping", "park", "whole_foods", "starbucks", "target",
    )  # fmt: skip
    rows = []
    for kind in ("pt", "ctr"):
        for c in cats:
            rows.append({"i": index, "kind": kind, "category": c, "n": 2,
                         "ds": [100.0, 200.0, 300.0], "lats": [40.7] * 3, "lons": [-73.99] * 3})  # fmt: skip
    return rows


def handler_for(cells, rows=None, scale_rows=None, calls=None):
    def handler(sql, params):
        if calls is not None:
            calls.append(sql)
        if "from geo_entities ge join feature_store f" in sql:
            wanted = set(params[0])
            return [c for c in cells if c["geohash"] in wanted]
        if "with p(i, geohash, lon, lat)" in sql:
            return rows if rows is not None else live_rows()
        if "from score_scales" in sql:
            if scale_rows is None:
                raise psycopg.errors.UndefinedTable("score_scales")
            return scale_rows
        if "from feature_store fs" in sql:
            return make_rows(60)
        if "from geo_entities where latitude between" in sql:
            return [
                {"geohash": c["geohash"], "latitude": c["latitude"], "longitude": c["longitude"]}
                for c in cells
            ]
        raise AssertionError(sql)

    return handler


# --- scales loading ----------------------------------------------------------------


def test_scales_from_table_when_present_and_cached():
    scales = compute_scales(make_rows(50), VERSION)
    table = [
        {"factor": f, "component": c, "lo": lo, "hi": hi, "n": n}
        for _, _, f, c, lo, hi, n in scales_to_rows(VERSION, "nyc", scales)
    ]
    calls = []
    conn = FakeConn(handler_for([], scale_rows=table, calls=calls))
    got = point_score.load_scales(conn, VERSION, "nyc")
    assert got == scales
    assert point_score.load_scales(conn, VERSION, "nyc") is got
    assert len(calls) == 1  # second call served from the cache
    assert point_score.scales_info()[(VERSION, "nyc")][0] == "table"


def test_scales_fall_back_to_feature_store_when_table_missing():
    calls = []
    conn = FakeConn(handler_for([], scale_rows=None, calls=calls))
    got = point_score.load_scales(conn, VERSION, "nyc")
    assert "grocery_score" in got
    assert conn.rolled_back == 1  # failed statement rolled back before the retry
    assert "from feature_store fs" in calls[-1]
    assert "fs.grocery_count_1600ft" in calls[-1] and "fs.*" not in calls[-1]
    assert point_score.scales_info()[(VERSION, "nyc")][0] == "feature_store"


def test_empty_table_also_falls_back():
    conn = FakeConn(handler_for([], scale_rows=[]))
    assert point_score.load_scales(conn, VERSION, "nyc")


# --- score_points ---------------------------------------------------------------------


def test_score_points_one_round_trip_and_result_shape(monkeypatch):
    monkeypatch.setattr(
        point_score, "load_scales", lambda c, v, m: compute_scales(make_rows(60), v)
    )
    cell = cell_row(geohash_encode(40.7003, -73.9912, precision=6))
    conn = FakeConn(handler_for([cell]))
    [res] = point_score.score_points(conn, [(40.7003, -73.9912)], VERSION)
    # cell lookup and live query are both sent before either result is read (one pipeline round trip)
    assert conn.kinds() == ["execute", "execute", "fetch", "fetch"]
    assert 0 <= res.scores["composite_score"] <= 100
    assert res.cell["id"] == CELL_ID and res.metro_area == "nyc"
    assert res.features["airport_drive_time_min"] > 0
    assert res.timings_ms["total"] >= res.timings_ms["query"] >= 0


def test_score_points_handles_several_points(monkeypatch):
    monkeypatch.setattr(
        point_score, "load_scales", lambda c, v, m: compute_scales(make_rows(60), v)
    )
    pts = [(40.7003, -73.9912), (40.75, -73.90)]
    cells = [cell_row(geohash_encode(la, lo, precision=6)) for la, lo in pts]
    conn = FakeConn(handler_for(cells, rows=[*live_rows(0), *live_rows(1)]))
    res = point_score.score_points(conn, pts, VERSION)
    assert [(r.lat, r.lon) for r in res] == pts
    assert conn.kinds().count("execute") == 2  # still one cell query + one live query


def test_missing_cell_uses_nearest_cell_and_reruns_live(monkeypatch):
    monkeypatch.setattr(
        point_score, "load_scales", lambda c, v, m: compute_scales(make_rows(60), v)
    )
    neighbour = cell_row("dr5ret")
    calls = []

    def handler(sql, params):
        if "from geo_entities ge join feature_store f" in sql:
            return [neighbour] if "dr5ret" in params[0] else []
        return handler_for([neighbour], calls=calls)(sql, params)

    conn = FakeConn(handler)
    [res] = point_score.score_points(conn, [(40.7003, -73.9912)], VERSION)
    assert res.cell["geohash"] == "dr5ret"
    live_calls = [c for c in calls if "with p(i, geohash" in c]
    assert len(live_calls) == 2  # original (cell-less) pass, then one against the neighbour


def test_no_cell_anywhere_raises():
    conn = FakeConn(
        lambda sql, params: (
            []
            if "geo_entities" in sql and "feature_store f" in sql
            else live_rows()
            if "with p(" in sql
            else []
        )
    )
    with pytest.raises(PointScoringError):
        point_score.score_points(conn, [(40.7, -73.99)], VERSION)


def test_unsupported_version_raises():
    with pytest.raises(PointScoringError):
        point_score.score_points(FakeConn(handler_for([])), [(40.7, -73.99)], "v1-handtuned")


# --- response builders ------------------------------------------------------------------


def make_result(scores=None, lat=40.7003, lon=-73.9912):
    cols = {c: 60.0 for c in AGGREGATE_COLUMNS}
    cols.update(scores or {})
    return PointResult(lat, lon, cell_row(), cols, {"grocery_nearest_m": 150.0}, "nyc")


def test_point_score_response_shape():
    res = point_score.point_score_response(make_result({"composite_score": 71.0}), VERSION)
    body = res.model_dump(by_alias=True)
    assert body["precision"] == "point"
    assert body["compositeScore"] == 71.0
    assert body["latitude"] == 40.7003 and body["longitude"] == -73.9912
    assert body["address"] == "40.70030,-73.99120"
    assert body["neighborhood"] == "Somewhere, NYC"
    assert body["geoEntityId"] == CELL_ID
    assert body["weightsVersion"] == VERSION
    assert body["subScores"]["grocery"] == 60.0


def test_area_aggregate_is_the_equal_weight_mean_with_null_skipping():
    a = make_result({"grocery_score": 100.0, "gym_score": None, "composite_score": 80.0})
    b = make_result({"grocery_score": 50.0, "gym_score": 40.0, "composite_score": 60.0})
    b.cell = {**b.cell, "id": uuid4()}
    agg = point_score.area_aggregate_from_points([a, b], VERSION)
    assert agg["grocery_score"] == 75.0
    assert agg["gym_score"] == 40.0  # a null factor drops out of that factor's mean
    assert agg["composite_score"] == 70.0
    assert agg["cell_count"] == 2
    assert agg["weights_version"] == VERSION


# --- routes ----------------------------------------------------------------------------------


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def grid_score_row():
    row = {c: 50.0 for c in AGGREGATE_COLUMNS}
    row.update(weights_version=VERSION, computed_at=NOW)
    return row


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "get_connection", lambda: _Ctx())
    entity = {"id": CELL_ID, "latitude": 40.7, "longitude": -73.99, "formatted_address": None}
    monkeypatch.setattr(main, "get_geo_entity_by_geohash", lambda c, g: entity)
    monkeypatch.setattr(main, "get_latest_score", lambda c, i, v: grid_score_row())
    monkeypatch.setattr(main, "get_feature_row", lambda c, i: {})
    monkeypatch.setattr(main, "SCORING_WEIGHTS_VERSION", VERSION)
    return TestClient(main.app)


def test_score_default_is_grid(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not run point scoring by default")

    monkeypatch.setattr(main.point_score, "score_points", boom)
    body = client.get("/v1/score", params={"lat": 40.7, "lon": -73.99}).json()
    assert body["precision"] == "grid"
    assert body["compositeScore"] == 50.0


def test_score_precision_point(client, monkeypatch):
    seen = {}

    def fake(conn, pts, version):
        seen["args"] = (pts, version)
        return [make_result({"composite_score": 88.0}, 40.7003, -73.9912)]

    monkeypatch.setattr(main.point_score, "score_points", fake)
    body = client.get(
        "/v1/score", params={"lat": 40.7003, "lon": -73.9912, "precision": "point"}
    ).json()
    assert seen["args"] == ([(40.7003, -73.9912)], VERSION)
    assert body["precision"] == "point" and body["compositeScore"] == 88.0
    assert body["latitude"] == 40.7003


def test_score_point_failure_falls_back_to_grid(client, monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(main.point_score, "score_points", fail)
    r = client.get("/v1/score", params={"lat": 40.7, "lon": -73.99, "precision": "point"})
    assert r.status_code == 200
    assert r.json()["precision"] == "grid"


def test_score_rejects_unknown_precision(client):
    r = client.get("/v1/score", params={"lat": 40.7, "lon": -73.99, "precision": "exact"})
    assert r.status_code in (400, 422)


SQ = {
    "type": "Polygon",
    "coordinates": [
        [[-74.0, 40.69], [-73.98, 40.69], [-73.98, 40.71], [-74.0, 40.71], [-74.0, 40.69]]
    ],
}


@pytest.fixture
def area_client(client, monkeypatch):
    area = {
        "id": 3,
        "area_sq_m": 1_000_000.0,
        "extent_m": None,
        "bounded_by": ["A St"],
        "geometry": SQ,
    }
    monkeypatch.setattr(main, "get_area_candidates", lambda c, la, lo: [area])
    agg = grid_score_row() | {"cell_count": 4}
    monkeypatch.setattr(main, "get_area_aggregate", lambda c, a, v: agg)
    return client


def test_area_precision_point_scores_interior_samples(area_client, monkeypatch):
    seen = {}

    def fake(conn, pts, version):
        seen["pts"] = pts
        return [make_result({"composite_score": 90.0}, la, lo) for la, lo in pts]

    monkeypatch.setattr(main.point_score, "score_points", fake)
    r = area_client.get("/v1/area", params={"lat": 40.70, "lon": -73.99, "precision": "point"})
    body = r.json()
    assert r.status_code == 200 and body["precision"] == "point"
    assert body["compositeScore"] == 90.0
    assert 1 <= len(seen["pts"]) <= 5
    assert all(-74.0 < lo < -73.98 and 40.69 < la < 40.71 for la, lo in seen["pts"])
    assert body["areaId"] == 3 and "Area bounded by A St" == body["address"]
    assert r.headers["cache-control"] == "public, max-age=300"


def test_area_point_failure_serves_grid_aggregate(area_client, monkeypatch):
    def fail(*a, **k):
        raise PointScoringError("nope")

    monkeypatch.setattr(main.point_score, "score_points", fail)
    body = area_client.get(
        "/v1/area", params={"lat": 40.70, "lon": -73.99, "precision": "point"}
    ).json()
    assert body["precision"] == "grid" and body["compositeScore"] == 50.0


def test_area_default_is_grid_and_unknown_area_is_404(area_client, monkeypatch):
    assert (
        area_client.get("/v1/area", params={"lat": 40.70, "lon": -73.99}).json()["precision"]
        == "grid"
    )
    monkeypatch.setattr(main, "get_area_candidates", lambda c, la, lo: [])
    r = area_client.get("/v1/area", params={"lat": 40.70, "lon": -73.99, "precision": "point"})
    assert r.status_code == 404
