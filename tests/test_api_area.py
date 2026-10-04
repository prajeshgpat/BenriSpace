"""Tests for GET /v1/area: geometry, area picking, aggregation and the route
(db functions monkeypatched; no database)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api import main
from api.areas import (
    AGGREGATE_COLUMNS,
    aggregate_cells,
    aggregate_sql,
    bounded_by_text,
    pick_area,
    point_in_polygon,
    usable_areas,
)
from api.schemas import AreaScoreResponse
from scoring.engine import CATEGORY_SPECS

SQ = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
HOLE = [[4, 4], [4, 6], [6, 6], [6, 4], [4, 4]]


def poly(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}


# --- point in polygon --------------------------------------------------------


def test_pip_inside_outside():
    g = poly(SQ)
    assert point_in_polygon(5, 5, g)
    assert not point_in_polygon(11, 5, g)
    assert not point_in_polygon(5, -1, g)


def test_pip_hole_excluded():
    g = poly(SQ, HOLE)
    assert not point_in_polygon(5, 5, g)
    assert point_in_polygon(2, 2, g)


def test_pip_multipolygon():
    far = [[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]
    g = {"type": "MultiPolygon", "coordinates": [[SQ], [far]]}
    assert point_in_polygon(25, 25, g)
    assert point_in_polygon(5, 5, g)
    assert not point_in_polygon(15, 15, g)


def test_pip_unknown_type_and_edge_is_deterministic():
    assert not point_in_polygon(1, 1, {"type": "Point", "coordinates": [1, 1]})
    assert isinstance(point_in_polygon(0, 5, poly(SQ)), bool)


# --- pick_area ---------------------------------------------------------------

LAT, LON = 40.75, -73.99
D = 0.001  # ~0.001 deg ~ 85-111 m


def box(lon0, lat0, lon1, lat1):
    return poly([[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]])


def test_pick_prefers_smallest_containing():
    big = {"id": 1, "area_sq_m": 5e6, "geometry": box(LON - D, LAT - D, LON + D, LAT + D)}
    small = {
        "id": 2,
        "area_sq_m": 1e6,
        "geometry": box(LON - D / 2, LAT - D / 2, LON + D / 2, LAT + D / 2),
    }
    assert pick_area(LAT, LON, [big, small])["id"] == 2


def test_pick_snaps_within_40m():
    # Point ~22 m west of the box's west edge (0.00025 deg lon ~ 21 m).
    a = {"id": 7, "area_sq_m": 1e6, "geometry": box(LON, LAT - D, LON + D, LAT + D)}
    assert pick_area(LAT, LON - 0.00025, [a])["id"] == 7


def test_pick_no_snap_beyond_40m():
    # 0.001 deg lon ~ 84 m away.
    a = {"id": 7, "area_sq_m": 1e6, "geometry": box(LON, LAT - D, LON + D, LAT + D)}
    assert pick_area(LAT, LON - 0.001, [a]) is None


def test_pick_snaps_to_nearest_and_contained_beats_snap():
    near = {"id": 1, "area_sq_m": 1, "geometry": box(LON, LAT - D, LON + D, LAT + D)}
    nearer = {
        "id": 2,
        "area_sq_m": 9,
        "geometry": box(LON - 0.00035, LAT - 0.0002, LON - 0.00026, LAT + D),
    }
    # point just west of `near` (~21 m); `nearer`'s edge is ~8 m away
    assert pick_area(LAT, LON - 0.00025, [near, nearer])["id"] == 2
    inside = {"id": 3, "area_sq_m": 99, "geometry": box(LON - D, LAT - D, LON, LAT + D)}
    assert pick_area(LAT, LON - 0.00025, [near, inside])["id"] == 3


def test_pick_empty():
    assert pick_area(LAT, LON, []) is None


# --- aggregate SQL -----------------------------------------------------------


def test_aggregate_columns_cover_all_factors_and_composite():
    cols = {s.score_column for s in CATEGORY_SPECS}
    assert len(cols) == 17  # 13 factors + the 4 v2-only legacy columns
    assert {"shopping_score", "recreation_score", "gas_convenience_score"} <= cols
    assert {"premium_retail_score", "trail_popularity_score"} <= cols
    assert cols <= set(AGGREGATE_COLUMNS)
    assert "composite_score" in AGGREGATE_COLUMNS
    assert "school_proximity_score" in AGGREGATE_COLUMNS


def test_aggregate_sql_text():
    sql = aggregate_sql()
    for col in AGGREGATE_COLUMNS:
        assert f"filter (where s.{col} is not null)" in sql
        assert f"sum(s.{col}::float8 * ac.overlap_sq_m)" in sql
    # Same version preference as common.db.get_latest_score; two placeholders.
    assert "order by (s2.weights_version = %s) desc nulls last, s2.computed_at desc" in sql
    assert sql.count("%s") == 2
    assert "max(s.computed_at) as computed_at" in sql
    assert "ac.area_id = %s" in sql


def test_get_area_aggregate_params_and_missing_tables(monkeypatch):
    import psycopg

    from common import db

    calls = {}

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            calls["params"] = params
            raise psycopg.errors.UndefinedTable("x")

    class Conn:
        rolled = False

        def cursor(self):
            return Cur()

        def rollback(self):
            self.rolled = True

    conn = Conn()
    assert db.get_area_aggregate(conn, 5, "v2") is None
    assert calls["params"] == ("v2", 5)
    assert conn.rolled
    conn2 = Conn()
    assert db.get_area_candidates(conn2, 1.0, 2.0) == []
    assert conn2.rolled


# --- reference weighted mean, hand-computed ----------------------------------


def cell(w, **cols):
    return {"overlap_sq_m": w, **cols}


CASES = [
    # (cells, column, expected)
    ([cell(1, grocery_score=50)], "grocery_score", 50),
    ([cell(100, grocery_score=73.5)], "grocery_score", 73.5),
    ([cell(1, grocery_score=0), cell(1, grocery_score=100)], "grocery_score", 50),
    ([cell(1, grocery_score=0), cell(3, grocery_score=100)], "grocery_score", 75),
    ([cell(2, grocery_score=10), cell(3, grocery_score=20)], "grocery_score", 16),
    ([cell(5, grocery_score=10), cell(5, grocery_score=None)], "grocery_score", 10),
    ([cell(5, grocery_score=None), cell(5, grocery_score=None)], "grocery_score", None),
    ([cell(1, gym_score=40), cell(1, gym_score=None), cell(2, gym_score=70)], "gym_score", 60),
    ([cell(10, cafe_score=80), cell(30, cafe_score=40)], "cafe_score", 50),
    (
        [cell(1, transit_score=100), cell(1, transit_score=50), cell(2, transit_score=0)],
        "transit_score",
        37.5,
    ),
    ([cell(4, road_score=25), cell(1, road_score=100)], "road_score", 40),
    (
        [cell(1, school_score=None, school_proximity_score=60), cell(1, school_score=80)],
        "school_score",
        80,
    ),
    (
        [cell(1, school_score=None, school_proximity_score=60), cell(1, school_score=80)],
        "school_proximity_score",
        60,
    ),
    ([cell(3, composite_score=60), cell(1, composite_score=80)], "composite_score", 65),
    ([cell(0.5, composite_score=90), cell(1.5, composite_score=50)], "composite_score", 60),
    (
        [cell(1, airport_score=20), cell(1, airport_score=40), cell(1, airport_score=90)],
        "airport_score",
        50,
    ),
    ([cell(7, bar_score=None), cell(2, bar_score=45), cell(1, bar_score=90)], "bar_score", 60),
    (
        [cell(1, emergency_corridor_score=10), cell(9, emergency_corridor_score=None)],
        "emergency_corridor_score",
        10,
    ),
    (
        [cell(2, restaurant_score=30), cell(2, restaurant_score=60), cell(4, restaurant_score=90)],
        "restaurant_score",
        67.5,
    ),
    (
        [cell(1, trail_popularity_score=0), cell(1, premium_retail_score=5)],
        "premium_retail_score",
        5,
    ),
]


@pytest.mark.parametrize(("cells", "col", "expected"), CASES)
def test_reference_weighted_mean(cells, col, expected):
    got = aggregate_cells(cells)[col]
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)
    assert aggregate_cells(cells)["cell_count"] == len(cells)


# --- text --------------------------------------------------------------------


def test_bounded_by_text():
    assert bounded_by_text([]) == "Area bounded by major roads"
    assert bounded_by_text(["A"]) == "Area bounded by A"
    assert bounded_by_text(["A", "B"]) == "Area bounded by A and B"
    assert bounded_by_text(["A", "B", "C", "D", "E"]) == "Area bounded by A, B, C and D"


# --- route -------------------------------------------------------------------

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CLICK = (40.7484, -73.9857)


def make_area(sq_m=1_000_000.0, extent_m=None):
    return {
        "id": 3,
        "area_sq_m": sq_m,
        "extent_m": extent_m,
        "bounded_by": ["A St", "B Ave", "C Rd", "D Blvd", "E St"],
        "geometry": box(CLICK[1] - 0.01, CLICK[0] - 0.01, CLICK[1] + 0.01, CLICK[0] + 0.01),
    }


def make_aggregate():
    row = {c: 60.0 for c in AGGREGATE_COLUMNS}
    row["grocery_score"] = 90.0
    row["gym_score"] = None
    row.update(cell_count=4, computed_at=NOW, weights_version="v1-handtuned")
    return row


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "get_connection", lambda: FakeConn())
    entity = {"id": uuid4(), "latitude": CLICK[0], "longitude": CLICK[1], "formatted_address": None}
    monkeypatch.setattr(main, "get_geo_entity_by_geohash", lambda c, g: entity)
    monkeypatch.setattr(main, "get_feature_row", lambda c, i: {"grocery_nearest_m": 300.0})
    monkeypatch.setattr(main, "get_area_candidates", lambda c, la, lo: [make_area()])
    monkeypatch.setattr(main, "get_area_aggregate", lambda c, a, v: make_aggregate())
    return TestClient(main.app)


def test_route_200_shape(client):
    r = client.get("/v1/area", params={"lat": CLICK[0], "lon": CLICK[1]})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=300"
    body = r.json()
    parsed = AreaScoreResponse.model_validate(body)
    assert body["address"] == "Area bounded by A St, B Ave, C Rd and D Blvd"
    assert body["latitude"] == CLICK[0] and body["longitude"] == CLICK[1]
    assert body["areaId"] == 3
    assert body["area"]["cellCount"] == 4
    assert body["area"]["areaSqMi"] == pytest.approx(1_000_000 / 2_589_988.11)
    assert body["area"]["geometry"]["type"] == "Polygon"
    assert body["subScores"]["grocery"] == 90.0
    assert body["subScores"]["gym"] is None
    assert body["compositeScore"] == 60.0
    assert "from this spot" in body["explanation"]
    assert parsed.area.bounded_by[-1] == "E St"


def test_route_404_tables_missing(client, monkeypatch):
    monkeypatch.setattr(main, "get_area_candidates", lambda c, la, lo: [])
    r = client.get("/v1/area", params={"lat": CLICK[0], "lon": CLICK[1]})
    assert r.status_code == 404
    assert r.json()["code"] == "area_not_found"


def test_route_404_cap_exceeded(client, monkeypatch):
    monkeypatch.setattr(
        main, "get_area_candidates", lambda c, la, lo: [make_area(0.81 * 2_589_988.11)]
    )
    r = client.get("/v1/area", params={"lat": CLICK[0], "lon": CLICK[1]})
    assert r.status_code == 404


def test_route_404_extent_exceeded_and_ok_at_limit(client, monkeypatch):
    params = {"lat": CLICK[0], "lon": CLICK[1]}
    monkeypatch.setattr(
        main, "get_area_candidates", lambda c, la, lo: [make_area(extent_m=1.41 * 1609.344)]
    )
    assert client.get("/v1/area", params=params).status_code == 404
    monkeypatch.setattr(
        main, "get_area_candidates", lambda c, la, lo: [make_area(extent_m=1.4 * 1609.344)]
    )
    assert client.get("/v1/area", params=params).status_code == 200
    # legacy row (extent_m null) under the area cap is still served
    monkeypatch.setattr(
        main, "get_area_candidates", lambda c, la, lo: [make_area(0.79 * 2_589_988.11)]
    )
    assert client.get("/v1/area", params=params).status_code == 200


def test_route_prefers_smallest_piece_and_skips_oversized(client, monkeypatch):
    huge = make_area(9 * 2_589_988.11)
    huge["id"] = 1
    piece = make_area(0.7 * 2_589_988.11)
    piece["id"] = 2
    monkeypatch.setattr(main, "get_area_candidates", lambda c, la, lo: [huge, piece])
    assert client.get("/v1/area", params={"lat": CLICK[0], "lon": CLICK[1]}).json()["areaId"] == 2
    monkeypatch.setattr(main, "get_area_candidates", lambda c, la, lo: [huge])
    assert client.get("/v1/area", params={"lat": CLICK[0], "lon": CLICK[1]}).status_code == 404


def test_usable_areas_filters_by_area_and_extent():
    ok = {"area_sq_m": 1e6, "extent_m": 1500.0}
    assert usable_areas([ok, {"area_sq_m": 4e6}, {"area_sq_m": 1e6, "extent_m": 4000.0}]) == [ok]


def test_route_404_no_scored_cells(client, monkeypatch):
    monkeypatch.setattr(main, "get_area_aggregate", lambda c, a, v: None)
    assert client.get("/v1/area", params={"lat": CLICK[0], "lon": CLICK[1]}).status_code == 404


def test_route_404_point_outside_polygon(client):
    r = client.get("/v1/area", params={"lat": CLICK[0] + 0.05, "lon": CLICK[1]})
    assert r.status_code == 404


def test_route_400(client):
    assert client.get("/v1/area").status_code == 400
    assert client.get("/v1/area", params={"lat": "x", "lon": 1}).status_code == 400
    assert client.get("/v1/area", params={"lat": 95, "lon": 1}).status_code == 400


def test_route_422_out_of_coverage(client):
    r = client.get("/v1/area", params={"lat": 10, "lon": 10})
    assert r.status_code == 422
    assert r.json()["code"] == "out_of_coverage"
