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
