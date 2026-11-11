"""tune="auto": pure algorithm tests plus route tests with reach and the score fetch faked."""

import contextlib

import pytest
from fastapi.testclient import TestClient

from api import main, reach
from api import triangulate as tri
from common import cellgrid

IY, IX = cellgrid.cell_index(40.7, -74.0)


def cell(dx):
    return (IY, IX + dx)


def merged_from(per_mode):
    return tri.merge_modes(per_mode)


def test_merge_modes_prefers_walk_over_equally_short_ride():
    m = merged_from({"transit": {cell(0): 8.0}, "walk": {cell(0): 10.0}})
    assert m[cell(0)] == (10.0, "walk", 10.0)  # 8 + 5 = 13 perceived beats 10


def test_merge_modes_keeps_actual_minutes_of_the_chosen_mode():
    m = merged_from({"drive": {cell(0): 10.0}, "walk": {cell(0): 25.0}})
    assert m[cell(0)] == (13.0, "drive", 10.0)


def test_merge_modes_includes_cells_reached_by_one_mode_only():
    m = merged_from({"transit": {cell(1): 20.0}, "walk": {cell(0): 4.0}})
    assert set(m) == {cell(0), cell(1)}


def test_feasible_cells_are_reachable_from_every_anchor():
    a = merged_from({"walk": {cell(0): 1.0, cell(1): 2.0}})
    b = merged_from({"walk": {cell(1): 3.0, cell(2): 4.0}})
    assert tri.feasible_cells([a, b]) == {cell(1)}


def _anchors_with_worst(worst):
    """Two anchors whose cells have the given worst-case actual minutes."""
    a = merged_from({"walk": {cell(i): w for i, w in enumerate(worst)}})
    b = merged_from({"walk": {cell(i): 1.0 for i in range(len(worst))}})
    return [a, b]


def all_land(keys):
    return {k: cellgrid.cell_center(*k) for k in keys}


def tuned(merged, is_land=all_land, ceiling=45):
    return tri.tuned_land_minutes(merged, tri.feasible_cells(merged), ceiling, is_land)[0]


def test_tuned_minutes_is_smallest_five_minute_step_with_enough_cells():
    assert tuned(_anchors_with_worst([3, 9, 11, 12, 30])) == 15


def test_tuned_minutes_floors_at_five_and_accepts_exact_multiples():
    assert tuned(_anchors_with_worst([0, 1, 2, 5])) == 5


def test_tuned_minutes_is_none_when_too_few_cells_overlap():
    assert tuned(_anchors_with_worst([3, 4, 5])) is None


def test_tuned_minutes_is_none_beyond_the_ceiling():
    assert tuned(_anchors_with_worst([3, 4, 5, 50])) is None


def test_tuned_minutes_ignores_water_cells():
    # Four cells at 5 min are all water; land only appears at 15 min.
    merged = _anchors_with_worst([4, 4, 4, 4, 14, 14, 14, 14])
    water = {cell(i) for i in range(4)}
    calls = []

    def is_land(keys):
        calls.append(list(keys))
        return {k: None if k in water else cellgrid.cell_center(*k) for k in keys}

    minutes, land = tri.tuned_land_minutes(merged, tri.feasible_cells(merged), 45, is_land)
    assert minutes == 15
    assert set(land) == {cell(i) for i in range(4, 8)}
    # One query per step that has new cells, never re-checking a cell.
    assert len(calls) == 2 and not set(calls[0]) & set(calls[1])


def test_default_trips_per_week():
    assert [tri.default_trips(i) for i in range(3)] == [5, 2, 2]


def owner_example():
    """A = near work (work walk 5, gym transit 10); B = middle (work transit 5, gym transit 5)."""
    work = merged_from({"walk": {cell(0): 5.0, cell(1): 20.0}, "transit": {cell(1): 5.0}})
    gym = merged_from({"transit": {cell(0): 10.0, cell(1): 5.0}})
    return [work, gym]


def test_owner_example_costs_with_default_weights():
    merged = owner_example()
    costs = tri.cell_costs(merged, tri.feasible_cells(merged), [5, 2])
    assert costs[cell(0)] == 5 * 5 + 2 * (10 + 5) == 55
    assert costs[cell(1)] == 5 * (5 + 5) + 2 * (5 + 5) == 70


def test_owner_example_near_work_ranks_above_middle_on_equal_scores():
    merged = owner_example()
    costs = tri.cell_costs(merged, tri.feasible_cells(merged), [5, 2])
    band = tri.cost_band(costs)
    assert set(band) == {cell(0), cell(1)}  # 70 <= 55 * 1.25 + 10
    candidates = [
        {
            **dict(zip(("latitude", "longitude"), cellgrid.cell_center(*cell(i)))),
            "composite_score": 60.0,
        }
        for i in (1, 0)
    ]
    ranked = tri.rank_by_score_then_cost(candidates, band, 10)
    assert [cellgrid.cell_index(r["latitude"], r["longitude"]) for r in ranked] == [
        cell(0),
        cell(1),
    ]
    assert tri.cell_travel(merged, cell(0)) == [("walk", 5), ("transit", 10)]


def test_cost_band_drops_cells_far_above_the_cheapest():
    band = tri.cost_band({cell(0): 40.0, cell(1): 60.0, cell(2): 61.0})
    assert set(band) == {cell(0), cell(1)}  # limit = 40 * 1.25 + 10 = 60


def test_higher_score_beats_lower_cost():
    band = {cell(0): 10.0, cell(1): 50.0}
    rows = [
        {"latitude": cellgrid.cell_center(*cell(i))[0], "longitude": cellgrid.cell_center(*cell(i))[1],
         "composite_score": s}
        for i, s in ((0, 50.0), (1, 80.0))
    ]  # fmt: skip
    assert tri.rank_by_score_then_cost(rows, band, 5)[0]["composite_score"] == 80.0


def test_estimate_cells_minutes_grow_with_distance():
    cells = tri.estimate_cells(40.7, -74.0, "walk", 30)
    assert len(cells) > 1 and max(cells.values()) <= 30
    assert cells[cellgrid.cell_index(40.7, -74.0)] < 5


# ------------------------------------------------------------------ route


@pytest.fixture
def auto_client(monkeypatch):
    @contextlib.contextmanager
    def fake_conn():
        yield object()

    def candidates(conn, box, version):
        rows = []
        for i in range(-12, 13):
            la, lo = cellgrid.cell_center(*cell(i))
            rows.append({"geo_entity_id": f"00000000-0000-0000-0000-{i + 20:012d}",
                         "composite_score": 60.0, "formatted_address": f"c{i}",
                         "latitude": la, "longitude": lo})  # fmt: skip
        return rows

    monkeypatch.setattr(main, "get_connection", fake_conn)
    monkeypatch.setattr(main, "get_scored_candidates_in_box", candidates)
    monkeypatch.setattr(main.slim_areas, "land_points", lambda conn, pts: list(pts))
    return TestClient(main.app)


def anchor(dx, **extra):
    lat, lon = cellgrid.cell_center(*cell(dx))
    return {"label": f"a{dx}", "latitude": lat, "longitude": lon, "mode": "walk", **extra}


def fake_reach(monkeypatch):
    def fn(conn, lat, lon, mode, minutes):
        dx = cellgrid.cell_index(lat, lon)[1] - IX
        return reach.Reach(
            {cell(i): abs(i - dx) * 3.0 for i in range(dx - 12, dx + 13)
             if abs(i - dx) * 3.0 <= minutes}, mode, minutes
        )  # fmt: skip

    monkeypatch.setattr(reach, "reach", fn)


def test_auto_returns_tuned_minutes_travel_and_overlap(auto_client, monkeypatch):
    fake_reach(monkeypatch)
    body = {"anchors": [anchor(-3, tripsPerWeek=3), anchor(3, tripsPerWeek=3)], "tune": "auto"}
    data = auto_client.post("/v1/triangulate", json=body).json()
    # worst minutes: i=0 is 9, i=+-1 is 12, i=+-2 is 15, so 4 cells first fit at 15
    assert data["tunedMinutes"] == 15
    assert all(i["minutes"] == 15 for i in data["isochrones"])
    assert data["combined"]["cellCount"] == 5  # cells -2..2 are within 15 of both
    top = next(r for r in data["results"] if r["address"] == "c0")
    assert [t["label"] for t in top["travel"]] == ["a-3", "a3"]
    assert all(t["mode"] == "walk" and isinstance(t["minutes"], int) for t in top["travel"])
    assert [t["minutes"] for t in top["travel"]] == [9, 9]
    assert all("inOverlap" not in r for r in data["results"])


def result_cells(data):
    return [cellgrid.cell_index(r["latitude"], r["longitude"]) for r in data["results"]]


def test_auto_results_are_only_overlap_cells_even_when_a_cheaper_cell_is_outside(
    auto_client, monkeypatch
):
    fake_reach(monkeypatch)
    # c-3 (the main address) is the cheapest cell but 18 min from a3: outside the 15 min overlap.
    body = {"anchors": [anchor(-3), anchor(3, tripsPerWeek=1)], "tune": "auto", "limit": 20}
    data = auto_client.post("/v1/triangulate", json=body).json()
    assert data["tunedMinutes"] == 15
    assert data["results"] and set(result_cells(data)) <= {cell(i) for i in range(-2, 3)}
    assert len(set(result_cells(data))) == len(data["results"])


def test_auto_never_returns_a_water_cell_and_uses_the_land_point(auto_client, monkeypatch):
    fake_reach(monkeypatch)
    water = cellgrid.cell_center(*cell(0))

    def land(conn, pts):
        return [None if p == water else (p[0] + 0.0005, p[1]) for p in pts]

    monkeypatch.setattr(main.slim_areas, "land_points", land)
    body = {"anchors": [anchor(-3, tripsPerWeek=3), anchor(3, tripsPerWeek=3)], "tune": "auto"}
    data = auto_client.post("/v1/triangulate", json=body).json()
    assert cell(0) not in result_cells(data)
    assert data["results"]
    for r in data["results"]:
        centre = cellgrid.cell_center(*cellgrid.cell_index(r["latitude"], r["longitude"]))
        assert round(r["latitude"] - centre[0], 6) == 0.0005
    assert data["combined"]["cellCount"] == 4  # the water cell is not drawn either


def test_auto_returns_null_tuned_minutes_when_anchors_are_too_far(auto_client, monkeypatch):
    fake_reach(monkeypatch)
    body = {"anchors": [anchor(-12), anchor(12)], "tune": "auto"}
    r = auto_client.post("/v1/triangulate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["tunedMinutes"] is None and data["results"] == []
    assert data["combined"]["geometry"] is None
    assert len(data["isochrones"]) == 2


def test_auto_estimate_fallback_is_marked(auto_client, monkeypatch):
    monkeypatch.setattr(reach, "reach", lambda *a, **k: None)
    body = {"anchors": [anchor(-1), anchor(1)], "tune": "auto"}
    data = auto_client.post("/v1/triangulate", json=body).json()
    assert data["tunedMinutes"] is not None
    assert {i["method"] for i in data["isochrones"]} == {"estimate"}


def _unavailable(conn, pts):
    raise main.slim_areas.LandCheckUnavailable("no table")


def test_auto_is_503_when_land_cannot_be_checked(auto_client, monkeypatch):
    fake_reach(monkeypatch)
    monkeypatch.setattr(main.slim_areas, "land_points", _unavailable)
    body = {"anchors": [anchor(-3), anchor(3)], "tune": "auto"}
    r = auto_client.post("/v1/triangulate", json=body)
    assert r.status_code == 503 and r.json()["code"] == "land_check_unavailable"


def test_fixed_is_503_when_land_cannot_be_checked(auto_client, monkeypatch):
    fake_reach(monkeypatch)
    monkeypatch.setattr(main.slim_areas, "land_points", _unavailable)
    body = {"anchors": [anchor(-2, maxTravelMinutes=15), anchor(2, maxTravelMinutes=15)]}
    r = auto_client.post("/v1/triangulate", json=body)
    assert r.status_code == 503 and r.json()["code"] == "land_check_unavailable"


def test_fixed_fills_travel(auto_client, monkeypatch):
    fake_reach(monkeypatch)
    body = {"anchors": [anchor(-2, maxTravelMinutes=15), anchor(2, maxTravelMinutes=15)]}
    data = auto_client.post("/v1/triangulate", json=body).json()
    assert data["tunedMinutes"] is None
    top = data["results"][0]
    assert len(top["travel"]) == 2 and all(t["mode"] == "walk" for t in top["travel"])


def test_fixed_omits_travel_for_estimate_anchors(auto_client, monkeypatch):
    monkeypatch.setattr(reach, "reach", lambda *a, **k: None)
    body = {"anchors": [anchor(-1, maxTravelMinutes=20), anchor(1, maxTravelMinutes=20)]}
    data = auto_client.post("/v1/triangulate", json=body).json()
    assert data["results"] and all(r.get("travel") is None for r in data["results"])
