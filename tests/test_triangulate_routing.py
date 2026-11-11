"""POST /v1/triangulate and GET /v1/isochrone on the cell graph, plus optimizer upgrades."""

import contextlib

import pytest
from fastapi.testclient import TestClient

from api import main, optimize, reach, triangulate
from common import cellgrid


def row_graph(iy, ix0, n, dm=60):
    rows = []
    for ix in range(ix0, ix0 + n):
        la, lo = cellgrid.cell_center(iy, ix)
        edges = [-1] * 8
        edges[2], edges[6] = dm, dm
        rows.append({"latitude": la, "longitude": lo, "edges_dm": edges})
    return rows


class Conn:
    def __init__(self, graph_rows):
        self.graph_rows = graph_rows

    def cursor(self):
        outer = self

        class C:
            def __init__(self):
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                self.rows = outer.graph_rows if "cell_graph" in sql else []

            def fetchall(self):
                return self.rows

        return C()

    def rollback(self):
        pass


@pytest.fixture
def client(monkeypatch):
    iy, _ = cellgrid.cell_index(40.7, -74.0)
    ix0 = cellgrid.cell_index(40.7, -74.0)[1] - 6
    conn = Conn(row_graph(iy, ix0, 14))

    @contextlib.contextmanager
    def fake_conn():
        yield conn

    monkeypatch.setattr(main, "get_connection", fake_conn)
    monkeypatch.setattr(
        main,
        "get_scored_candidates_in_box",
        lambda c, box, v: [
            {
                "geo_entity_id": f"00000000-0000-0000-0000-{i:012d}",
                "composite_score": 50 + i,
                "formatted_address": f"cell {i}",
                "latitude": cellgrid.cell_center(iy, ix0 + i)[0],
                "longitude": cellgrid.cell_center(iy, ix0 + i)[1],
            }
            for i in range(14)
        ],
    )
    monkeypatch.setattr(main.slim_areas, "land_points", lambda conn, pts: list(pts))
    return TestClient(main.app)


def test_isochrone_endpoint_returns_polygon(client):
    r = client.get("/v1/isochrone", params={"lat": 40.7, "lon": -74.0, "mode": "walk", "minutes": 13})
    assert r.status_code == 200
    iso = r.json()["isochrone"]
    assert iso["method"] == "network" and iso["mode"] == "walk" and iso["minutes"] == 13
    assert iso["cellCount"] == 5  # 6 min a hop: the origin plus two cells each way
    assert iso["geometry"]["type"] == "MultiPolygon" and iso["areaSqMi"] > 0
    assert r.headers["cache-control"].startswith("public")


def test_isochrone_falls_back_to_estimate_without_routing_data(client, monkeypatch):
    monkeypatch.setattr(reach, "reach", lambda *a, **k: None)
    r = client.get("/v1/isochrone", params={"lat": 40.7, "lon": -74.0, "mode": "drive", "minutes": 10})
    assert r.json()["isochrone"]["method"] == "estimate"
    assert r.json()["isochrone"]["cellCount"] > 1


def test_triangulate_intersect_and_union(client):
    anchors = [
        {"label": "a", "latitude": 40.7, "longitude": -74.0 - 2 * cellgrid.LON_STEP,
         "maxTravelMinutes": 13, "mode": "walk"},
        {"label": "b", "latitude": 40.7, "longitude": -74.0 + 2 * cellgrid.LON_STEP,
         "maxTravelMinutes": 13, "mode": "walk"},
    ]  # fmt: skip
    both = client.post("/v1/triangulate", json={"anchors": anchors}).json()
    assert len(both["isochrones"]) == 2 and both["combined"]["cellCount"] <= 5
    assert all(i["method"] == "network" for i in both["isochrones"])
    assert both["results"] and both["results"][0]["compositeScore"] >= both["results"][-1]["compositeScore"]
    union = client.post("/v1/triangulate", json={"anchors": anchors, "combineMode": "union"}).json()
    assert union["combined"]["cellCount"] > both["combined"]["cellCount"]
    assert len(union["results"]) > len(both["results"])


def test_triangulate_bad_anchor_is_400(client):
    r = client.post("/v1/triangulate", json={"anchors": [{"label": "x"}]})
    assert r.status_code == 400


def test_anchor_cells_default_minutes_and_circle_fallback(monkeypatch):
    monkeypatch.setattr(reach, "reach", lambda *a, **k: None)
    cells, mins, method = triangulate.anchor_cells(object(), 40.7, -74.0, "walk", None)
    assert method == "estimate" and mins == 20 and len(cells) > 5


# ---------------------------------------------------------------------------- optimizer


def test_weiszfeld_median_of_collinear_points_is_the_weighted_middle():
    pts = [(40.0, -74.0), (40.0, -73.9), (40.0, -73.8)]
    lat, lon = optimize.weiszfeld(pts, [1, 1, 1])
    assert abs(lat - 40.0) < 1e-6 and abs(lon - (-73.9)) < 1e-4
    _lat2, lon2 = optimize.weiszfeld(pts, [5, 1, 1])  # heavy first point wins
    assert abs(lon2 - (-74.0)) < 1e-4


def test_prune_keeps_the_true_best_candidates():
    work = optimize.Target("work", 41.05, -73.54)
    anchors = [optimize.ResolvedAnchor("work", "address", "drive", 5.0, [work])]
    cands = [
        {"latitude": 41.05 + 0.001 * i, "longitude": -73.54 + 0.0013 * (i % 7), "composite": 50.0}
        for i in range(40)
    ] + [{"latitude": 41.9, "longitude": -74.4, "composite": 90.0}] * 3  # far away
    kept = optimize.prune_candidates(cands, anchors, keep=10)
    assert len(kept) < len(cands)
    assert not any(c["latitude"] > 41.5 for c in kept)
    near = sorted(cands[:40], key=lambda c: (c["latitude"] - 41.05) ** 2 + (c["longitude"] + 73.54) ** 2)
    assert all(c in kept for c in near[:10])


def test_apply_precomputed_replaces_estimates(monkeypatch):
    from api import routing_data

    anchors = [optimize.ResolvedAnchor("gym", "category", "walk", 3.0, [optimize.Target("g", 41.0, -73.5)], category="gym")]
    cands = [{"latitude": 41.0, "longitude": -73.5, "geohash": "dr7abc", "composite": 1.0}]
    ev = optimize.evaluate(cands, anchors)
    monkeypatch.setattr(routing_data, "travel_slots", lambda c, g, cat, k: {"dr7abc": ("walk", 7.5)})
    optimize.apply_precomputed(object(), cands, anchors, ev, [0])
    assert ev.minutes[0][0] == 7.5 and ev.approx[0][0] is False
    monkeypatch.setattr(routing_data, "travel_slots", lambda c, g, cat, k: {"dr7abc": ("drive", 3.0)})
    ev2 = optimize.evaluate(cands, anchors)
    optimize.apply_precomputed(object(), cands, anchors, ev2, [0])
    assert ev2.approx[0][0] is True  # mode mismatch: keep the estimate


def _factor_candidates(iy, ix0):
    # Cell i: grocery falls with i, gym rises with i; the all-factor composite favours high i.
    rows = []
    for i in range(14):
        row = {
            "geo_entity_id": f"00000000-0000-0000-0000-{i:012d}",
            "composite_score": 50 + i,
            "formatted_address": f"cell {i}",
            "latitude": cellgrid.cell_center(iy, ix0 + i)[0],
            "longitude": cellgrid.cell_center(iy, ix0 + i)[1],
        }
        row["grocery_score"] = 90.0 - 5 * i
        row["gym_score"] = 10.0 + 5 * i
        rows.append(row)
    return rows


@pytest.fixture
def factor_client(client, monkeypatch):
    iy, _ = cellgrid.cell_index(40.7, -74.0)
    ix0 = cellgrid.cell_index(40.7, -74.0)[1] - 6
    rows = _factor_candidates(iy, ix0)
    monkeypatch.setattr(main, "get_scored_candidates_in_box", lambda c, box, v: [dict(r) for r in rows])
    return client


ANCHOR = [{"label": "a", "latitude": 40.7, "longitude": -74.0, "maxTravelMinutes": 13, "mode": "walk"}]


def test_triangulate_factors_change_ranking_and_score(factor_client):
    default = factor_client.post("/v1/triangulate", json={"anchors": ANCHOR}).json()["results"]
    picked = factor_client.post(
        "/v1/triangulate", json={"anchors": ANCHOR, "factors": "grocery"}
    ).json()["results"]
    assert default[0]["compositeScore"] >= default[-1]["compositeScore"]
    assert default[0]["address"] == "cell 8"  # highest composite_score inside the area
    assert picked[0]["address"] != default[0]["address"]
    scores = [r["compositeScore"] for r in picked]
    assert scores == sorted(scores, reverse=True)
    assert picked[0]["compositeScore"] == round(90.0 - 5 * int(picked[0]["address"].split()[1]), 1)


def test_triangulate_weights_blend_selected_factors(factor_client):
    r = factor_client.post(
        "/v1/triangulate",
        json={"anchors": ANCHOR, "factors": "grocery,gym", "weights": "grocery:1,gym:1"},
    ).json()["results"]
    assert all(x["compositeScore"] == 50.0 for x in r)  # (90-5i + 10+5i) / 2


def test_triangulate_drops_candidates_without_selected_sub_scores(factor_client):
    r = factor_client.post("/v1/triangulate", json={"anchors": ANCHOR, "factors": "transit"})
    assert r.status_code == 200 and r.json()["results"] == []


def test_triangulate_invalid_factor_is_400(factor_client):
    r = factor_client.post("/v1/triangulate", json={"anchors": ANCHOR, "factors": "nope"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_request"


def test_candidates_sql_selects_every_factor_column():
    from api.factors import FACTOR_COLUMNS
    from api.triangulate_sql import build_candidates_sql

    sql, _ = build_candidates_sql(None, "v")
    assert all(f"s.{col}" in sql for col in FACTOR_COLUMNS.values())


# --- results are moved onto land (Pier 26 sat in the Hudson cell next to it) -------------------
def test_triangulate_fixed_keeps_land_cells_at_land_points_and_drops_water(client, monkeypatch):
    seen = {}

    def fake_land(conn, points):
        seen["points"] = list(points)
        # The first cell is water; the rest have a land point a little to the north.
        return [None] + [(lat + 0.0005, lon) for lat, lon in points[1:]]

    monkeypatch.setattr(main.slim_areas, "land_points", fake_land)
    anchors = [
        {"label": "a", "latitude": 40.7, "longitude": -74.0, "maxTravelMinutes": 13, "mode": "walk"},
        {"label": "b", "latitude": 40.7, "longitude": -74.0, "maxTravelMinutes": 13, "mode": "walk"},
    ]  # fmt: skip
    body = client.post("/v1/triangulate", json={"anchors": anchors, "limit": 3}).json()
    # Over-fetched so a dropped result is replaced, then trimmed to the limit.
    assert len(seen["points"]) > 3
    assert len(body["results"]) == 3
    water = seen["points"][0]
    for result in body["results"]:
        assert (result["latitude"], result["longitude"]) != water
    moved = {(round(lat + 0.0005, 6), lon) for lat, lon in seen["points"][1:]}
    assert all((round(r["latitude"], 6), r["longitude"]) in moved for r in body["results"])
    assert all("inOverlap" not in r for r in body["results"])


def test_triangulate_fixed_is_503_when_land_cannot_be_checked(client, monkeypatch):
    def broken(conn, points):
        raise main.slim_areas.LandCheckUnavailable("no table")

    monkeypatch.setattr(main.slim_areas, "land_points", broken)
    anchors = [
        {"label": "a", "latitude": 40.7, "longitude": -74.0, "maxTravelMinutes": 13, "mode": "walk"},
        {"label": "b", "latitude": 40.7, "longitude": -74.0, "maxTravelMinutes": 13, "mode": "walk"},
    ]  # fmt: skip
    r = client.post("/v1/triangulate", json={"anchors": anchors, "limit": 3})
    assert r.status_code == 503 and r.json()["code"] == "land_check_unavailable"


def test_snap_to_land_distance_cutoff_and_failures():
    from api import slim_areas

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params):
            self.params = params

        def fetchall(self):
            return self.rows

    class Conn:
        def __init__(self, rows):
            self.rows = rows

        def transaction(self):
            return Cursor([])

        def cursor(self):
            return Cursor(self.rows)

    rows = [
        {"ord": 1, "lat": 40.7187, "lon": -74.0166, "dist_m": 120.0},
        {"ord": 2, "lat": 40.0, "lon": -74.0, "dist_m": 2000.0},  # 1.2 mi from any area
    ]
    out = slim_areas.snap_to_land(Conn(rows), [(40.7222, -74.018), (40.0, -74.2)])
    assert out == [(40.7187, -74.0166), None]
    assert slim_areas.snap_to_land(Conn(rows), []) == []

    class Broken:
        def transaction(self):
            raise RuntimeError("no table")

    assert slim_areas.snap_to_land(Broken(), [(40.7, -74.0)]) is None


class _LandConn:
    """Fake connection whose KNN query returns the given rows (ord, lat, lon, dist_m)."""

    def __init__(self, rows):
        self.rows = rows

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params):
        self.params = params

    def fetchall(self):
        return self.rows


def test_land_points_treats_far_points_and_cell_changes_as_water():
    from api import slim_areas

    iy, ix = cellgrid.cell_index(40.7, -74.0)
    c1 = cellgrid.cell_center(iy, ix)
    c2 = cellgrid.cell_center(iy, ix + 1)
    c3 = cellgrid.cell_center(iy, ix + 2)
    c4 = cellgrid.cell_center(iy, ix + 3)
    mi = 1609.344
    rows = [
        {"ord": 1, "lat": c1[0], "lon": c1[1], "dist_m": 0.0},  # inside an area
        {"ord": 2, "lat": c2[0] + 0.001, "lon": c2[1], "dist_m": 0.1 * mi},  # close, same cell
        {"ord": 3, "lat": c3[0], "lon": c3[1], "dist_m": 0.16 * mi},  # beyond 0.15 mi
        {"ord": 4, "lat": c4[0] + 0.01, "lon": c4[1], "dist_m": 0.1 * mi},  # left its cell
    ]
    out = slim_areas.land_points(_LandConn(rows), [c1, c2, c3, c4])
    assert out == [c1, (c2[0] + 0.001, c2[1]), None, None]
    assert slim_areas.land_points(_LandConn(rows), []) == []


def test_land_points_raises_when_the_query_fails():
    import pytest as _pytest

    from api import slim_areas

    class Broken:
        def transaction(self):
            raise RuntimeError("no table")

    with _pytest.raises(slim_areas.LandCheckUnavailable):
        slim_areas.land_points(Broken(), [(40.7, -74.0)])
