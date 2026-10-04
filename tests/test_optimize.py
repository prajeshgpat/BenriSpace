"""POST /v1/optimize and common/ors.py: no network, no database."""

import contextlib

import httpx
import pytest
from fastapi.testclient import TestClient

from api import main, optimize
from common import ors
from common.places import name_matches, normalize_name
from common.units import M_PER_MI

WORK = (41.0534, -73.5387)  # Stamford


def cell(dlat, dlon, composite=50.0, **extra):
    return {
        "latitude": WORK[0] + dlat,
        "longitude": WORK[1] + dlon,
        "composite": composite,
        "neighborhood": None,
        "area_label": None,
        **extra,
    }


def place(name, dlat, dlon, category="grocery", brand=None):
    return {
        "name": name,
        "brand": brand,
        "category": category,
        "latitude": WORK[0] + dlat,
        "longitude": WORK[1] + dlon,
    }


@pytest.fixture
def client(monkeypatch):
    @contextlib.contextmanager
    def fake_conn():
        yield object()

    monkeypatch.setattr(main, "get_connection", fake_conn)
    monkeypatch.setattr(optimize, "geocode_address", lambda q: WORK)
    monkeypatch.setattr(ors, "api_key", lambda: None)  # ORS off unless a test turns it on
    ors.clear_cache()
    return TestClient(main.app)


def stub(monkeypatch, cells, brands=None, categories=None):
    monkeypatch.setattr(optimize, "fetch_candidates", lambda *a, **k: list(cells))
    monkeypatch.setattr(
        optimize, "places_by_brand_in_box", lambda conn, q, *box: (brands or {}).get(q, [])
    )
    monkeypatch.setattr(
        optimize, "places_by_category_in_box", lambda conn, c, *box: (categories or {}).get(c, [])
    )


WORK_ANCHOR = {"kind": "address", "query": "123 Main St, Stamford"}


# ---------------------------------------------------------------- matching helpers


def test_brand_matching_ignores_case_and_apostrophes():
    assert normalize_name("Trader Joe’s") == "trader joes"
    assert name_matches("trader joe", "Trader Joe's", None)
    assert name_matches("TRADER JOES", "Trader Joe's", None)
    assert name_matches("planet", "Gym", "Planet Fitness")
    assert not name_matches("whole foods", "Trader Joe's", "Trader Joe's")
    assert not name_matches("  ", "Trader Joe's", None)


# ------------------------------------------------------------------ pure engine


def anchors_for(*pairs):
    return [
        optimize.ResolvedAnchor(q, "brand", "drive", trips, [optimize.Target(q, lat, lon)])
        for q, trips, lat, lon in pairs
    ]


def test_estimate_minutes_per_mode():
    mi = M_PER_MI
    assert optimize.estimate_minutes(mi, "walk") == pytest.approx(1.3 / 3 * 60)
    assert optimize.estimate_minutes(mi, "drive") == pytest.approx(1.3 / 25 * 60 + 2)
    assert optimize.estimate_minutes(mi, "transit") == pytest.approx(1.3 / 15 * 60)


def test_nearest_branch_per_candidate_uses_grid_index():
    targets = [optimize.Target(f"t{i}", 41.0 + i * 0.01, -73.5) for i in range(100)]
    cands = [cell(-0.0534 + 0.0123, 0.0387), cell(0.5, 0.0)]
    cands[0]["latitude"], cands[0]["longitude"] = 41.2345, -73.5
    cands[1]["latitude"], cands[1]["longitude"] = 40.9, -73.5
    idx, _ = optimize.nearest_targets(cands, targets)
    assert idx == [23, 0]


def test_nearest_branch_selected_per_candidate():
    a = optimize.ResolvedAnchor(
        "tj",
        "brand",
        "drive",
        1,
        [
            optimize.Target("West", WORK[0], WORK[1] - 0.1),
            optimize.Target("East", WORK[0], WORK[1] + 0.1),
        ],
    )
    cands = [cell(0, -0.09), cell(0, 0.09)]
    res = optimize.build_results(cands, [a], 2, use_ors=False)
    by_lon = {r.longitude: r.anchors[0].name for r in res}
    assert by_lon[round(cands[0]["longitude"], 5)] == "West"
    assert by_lon[round(cands[1]["longitude"], 5)] == "East"


def test_cost_ranking_and_composite_tiebreak():
    anchors = anchors_for(("work", 5, *WORK))
    near, far = cell(0.0, 0.02, 10), cell(0.0, 0.2, 99)
    res = optimize.build_results([far, near], anchors, 2, use_ors=False)
    assert [r.longitude for r in res] == [round(near["longitude"], 5), round(far["longitude"], 5)]
    # equal cost -> higher composite first
    a, b = cell(0.0, 0.1, 20), cell(0.0, -0.1, 80)
    res = optimize.build_results([a, b], anchors, 2, use_ors=False)
    assert res[0].score == 80


def test_weekly_minutes_is_trips_times_round_trip():
    anchors = anchors_for(("work", 5, *WORK))
    res = optimize.build_results([cell(0, 0)], anchors, 1, use_ors=False)
    # on top of the anchor: only the 2 min drive overhead, 5 trips x 2 x 2
    assert res[0].weekly_minutes == 20
    assert res[0].anchors[0].minutes == 2
    assert res[0].anchors[0].approx is True


def test_results_spread_at_least_a_mile():
    anchors = anchors_for(("work", 5, *WORK))
    cands = [cell(0, 0.001 * i) for i in range(10)] + [cell(0.0, 0.05)]
    res = optimize.build_results(cands, anchors, 3, use_ors=False)
    assert len(res) == 2  # one tight cluster + the cell ~2.6 mi away
    from common.geo import haversine_m

    assert (
        haversine_m(res[0].latitude, res[0].longitude, res[1].latitude, res[1].longitude) > M_PER_MI
    )


# ---------------------------------------------------------------- ORS refinement


def ors_on(monkeypatch, matrix):
    monkeypatch.setattr(ors, "api_key", lambda: "k")
    calls = []

    def fake(mode, sources, dests):
        calls.append((mode, len(sources), len(dests)))
        return matrix(mode, sources, dests)

    monkeypatch.setattr(ors, "matrix_minutes", fake)
    return calls


def test_ors_refinement_reranks_with_real_minutes(monkeypatch):
    anchors = anchors_for(("work", 5, *WORK))
    a, b = cell(0, 0.05), cell(0, -0.08)  # a is nearer by straight line
    # real minutes: a is across the water (60), b is quick (5)
    calls = ors_on(
        monkeypatch,
        lambda mode, src, dst: [[60.0 if s[1] > WORK[1] else 5.0] for s in src],
    )
    res = optimize.build_results([a, b], anchors, 2)
    assert calls == [("drive", 2, 1)]  # one matrix call for the mode
    assert res[0].longitude == round(b["longitude"], 5)
    assert res[0].anchors[0].approx is False
    assert res[0].anchors[0].minutes == 7  # 5 + 2 min parking overhead


def test_ors_failure_keeps_estimates(monkeypatch):
    anchors = anchors_for(("work", 5, *WORK))
    ors_on(monkeypatch, lambda *a: None)
    res = optimize.build_results([cell(0, 0.05)], anchors, 1)
    assert res[0].anchors[0].approx is True


def test_ors_partial_null_pairs_keep_estimate(monkeypatch):
    anchors = anchors_for(("work", 1, *WORK))
    ors_on(monkeypatch, lambda *a: [[None]])
    res = optimize.build_results([cell(0, 0.05)], anchors, 1)
    assert res[0].anchors[0].approx is True


def test_transit_never_calls_ors(monkeypatch):
    anchors = anchors_for(("work", 1, *WORK))
    anchors[0].mode = "transit"
    calls = ors_on(monkeypatch, lambda *a: [[1.0]])
    res = optimize.build_results([cell(0, 0.05)], anchors, 1)
    assert calls == []
    assert res[0].anchors[0].approx is True


def test_pool_shrinks_to_respect_element_cap(monkeypatch):
    targets = [optimize.Target(f"p{i}", WORK[0] + i * 0.0005, WORK[1] + 0.5) for i in range(200)]
    a = optimize.ResolvedAnchor("g", "category", "walk", 1, targets)
    # candidates, each nearest to a different place: 25 sources x up to 25 dests
    cands = [cell(i * 0.0005, 0.5 + 0.0 + i * 0.0001) for i in range(40)]
    monkeypatch.setattr(ors, "MAX_ELEMENTS", 10)
    calls = ors_on(monkeypatch, lambda m, s, d: [[3.0] * len(d) for _ in s])
    optimize.build_results(cands, [a], 1)
    _, n_src, n_dst = calls[0]
    assert n_src * n_dst <= 10 or n_src == 1


# --------------------------------------------------------------- ors client


class FakeResp:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self.payload


def test_ors_client_posts_once_and_caches(monkeypatch):
    ors.clear_cache()
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "secret-key")
    seen = []

    def fake_post(url, json, headers, timeout):
        seen.append((url, json, headers, timeout))
        return FakeResp({"durations": [[600.0, None]]})

    monkeypatch.setattr(ors.httpx, "post", fake_post)
    src, dst = [(41.0, -73.5)], [(41.1, -73.5), (41.2, -73.5)]
    assert ors.matrix_minutes("drive", src, dst) == [[10.0, None]]
    url, body, headers, timeout = seen[0]
    assert url.endswith("/matrix/driving-car")
    assert body["locations"][0] == [-73.5, 41.0]  # lon, lat
    assert body["metrics"] == ["duration"] and timeout == 8.0
    assert headers["Authorization"] == "secret-key"
    # the null pair is not cached, so a repeat call still goes out; a fully cached one does not
    ors.matrix_minutes("walk", src, dst[:1])
    assert seen[-1][0].endswith("/matrix/foot-walking")
    n = len(seen)
    assert ors.matrix_minutes("drive", src, dst[:1]) == [[10.0]]
    assert len(seen) == n


def test_ors_client_failures_return_none(monkeypatch):
    ors.clear_cache()
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "secret-key")

    def boom(*a, **k):
        raise httpx.ConnectTimeout("t")

    monkeypatch.setattr(ors.httpx, "post", boom)
    assert ors.matrix_minutes("drive", [(41.0, -73.5)], [(41.1, -73.5)]) is None
    monkeypatch.setattr(ors.httpx, "post", lambda *a, **k: FakeResp({}, status=429))
    assert ors.matrix_minutes("drive", [(41.0, -73.5)], [(41.1, -73.5)]) is None
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "")
    assert ors.matrix_minutes("drive", [(41.0, -73.5)], [(41.2, -73.5)]) is None


def test_ors_client_element_cap_and_modes(monkeypatch):
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "k")
    called = []
    monkeypatch.setattr(ors.httpx, "post", lambda *a, **k: called.append(1))
    pts = [(41.0 + i * 0.001, -73.5) for i in range(60)]
    assert ors.matrix_minutes("drive", pts, pts) is None  # 3600 > 3500
    assert ors.matrix_minutes("transit", pts[:1], pts[:1]) is None
    assert called == []


# ------------------------------------------------------------------- the route


def test_route_end_to_end_with_assumptions_and_units(client, monkeypatch):
    cells = [cell(0.0, 0.03, 60), cell(0.0, -0.2, 90)]
    stub(
        monkeypatch,
        cells,
        brands={"trader joe": [place("Trader Joe's", 0.0, 0.04, "grocery", "Trader Joe's")]},
        categories={"gym": [place("Fit Club", 0.0, 0.02, "gym")]},
    )
    r = client.post(
        "/v1/optimize",
        json={
            "anchors": [
                WORK_ANCHOR,
                {"kind": "brand", "query": "trader joe"},
                {"kind": "category", "query": "gym", "mode": "walk"},
            ],
            "limit": 2,
        },
    )
    assert r.status_code == 200
    body = r.json()
    best = body["results"][0]
    assert best["longitude"] == round(cells[0]["longitude"], 5)
    assert best["score"] == 60 and best["neighborhood"] is None
    work, tj, gym = best["anchors"]
    assert (work["kind"], work["mode"], work["approx"]) == ("address", "drive", True)
    assert tj["name"] == "Trader Joe's" and gym["mode"] == "walk"
    assert gym["distanceLabel"].endswith(("ft", "mi")) and "km" not in gym["distanceLabel"]
    assert body["assumptions"][0] == "Assumed 5 work trips/week by car"
    assert "Assumed 1 trip/week to trader joe by car" in body["assumptions"]
    assert "Assumed 3 trips/week to gym on foot" in body["assumptions"]
    assert body["unresolved"] == []
    expected = sum(t * 2 * x["minutes"] for t, x in zip((5, 1, 3), best["anchors"], strict=True))
    assert abs(best["weeklyMinutes"] - expected) <= 5  # per-anchor minutes are rounded


def test_brand_gym_default_trips_from_matched_category(client, monkeypatch):
    stub(
        monkeypatch,
        [cell(0, 0.01)],
        brands={"planet fitness": [place("Planet Fitness", 0, 0.02, "gym")]},
    )
    r = client.post(
        "/v1/optimize",
        json={"anchors": [WORK_ANCHOR, {"kind": "brand", "query": "planet fitness"}]},
    )
    assert "Assumed 3 trips/week to planet fitness by car" in r.json()["assumptions"]


def test_explicit_trips_have_no_assumption_and_transit_note(client, monkeypatch):
    stub(monkeypatch, [cell(0, 0.01)])
    r = client.post(
        "/v1/optimize",
        json={
            "anchors": [{**WORK_ANCHOR, "tripsPerWeek": 2, "mode": "transit"}],
            "defaultMode": "walk",
        },
    )
    body = r.json()
    assert all("Assumed" not in a for a in body["assumptions"])
    assert optimize.TRANSIT_NOTE in body["assumptions"]
    assert body["results"][0]["anchors"][0]["mode"] == "transit"


def test_unresolved_anchors_reported(client, monkeypatch):
    stub(monkeypatch, [cell(0, 0.01)])
    r = client.post(
        "/v1/optimize",
        json={
            "anchors": [
                WORK_ANCHOR,
                {"kind": "brand", "query": "nonexistent mart"},
                {"kind": "category", "query": "spaceport"},
            ]
        },
    )
    body = r.json()
    assert [u["query"] for u in body["unresolved"]] == ["nonexistent mart", "spaceport"]
    assert len(body["results"]) == 1 and len(body["results"][0]["anchors"]) == 1


def test_geocode_failure_is_unresolved(client, monkeypatch):
    stub(monkeypatch, [cell(0, 0.01)])
    monkeypatch.setattr(optimize, "geocode_address", lambda q: None)
    r = client.post("/v1/optimize", json={"anchors": [WORK_ANCHOR]})
    assert r.status_code == 200
    assert r.json()["results"] == [] and r.json()["unresolved"][0]["query"] == WORK_ANCHOR["query"]


def test_brands_only_centres_on_matches(client, monkeypatch):
    stub(
        monkeypatch,
        [cell(0, 0.01)],
        brands={"trader joe": [place("Trader Joe's", 0, 0.02)]},
    )
    r = client.post("/v1/optimize", json={"anchors": [{"kind": "brand", "query": "trader joe"}]})
    assert r.status_code == 200 and len(r.json()["results"]) == 1


def test_out_of_coverage_is_422(client, monkeypatch):
    stub(monkeypatch, [])
    r = client.post(
        "/v1/optimize",
        json={
            "anchors": [
                {"kind": "address", "query": "Boston", "latitude": 42.36, "longitude": -71.06}
            ]
        },
    )
    assert r.status_code == 422 and r.json()["code"] == "out_of_coverage"


def test_category_only_is_400(client, monkeypatch):
    stub(monkeypatch, [])
    r = client.post("/v1/optimize", json={"anchors": [{"kind": "category", "query": "gym"}]})
    assert r.status_code == 400 and r.json()["code"] == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        {"anchors": []},
        {"anchors": [WORK_ANCHOR], "radiusMi": 31},
        {"anchors": [WORK_ANCHOR], "radiusMi": 0},
        {"anchors": [WORK_ANCHOR], "limit": 11},
        {"anchors": [WORK_ANCHOR], "limit": 0},
        {"anchors": [WORK_ANCHOR], "defaultMode": "bike"},
        {"anchors": [{"kind": "planet", "query": "x"}]},
        {"anchors": [{"kind": "brand", "query": "  "}]},
        {"anchors": [{**WORK_ANCHOR, "tripsPerWeek": 0}]},
        {"anchors": [{**WORK_ANCHOR, "latitude": 41.0}]},
        {"anchors": [WORK_ANCHOR], "factors": "notafactor"},
        {"anchors": [WORK_ANCHOR], "weights": "gym:-1"},
        {"anchors": [WORK_ANCHOR] * 7},
    ],
)
def test_invalid_requests_are_400(client, monkeypatch, payload):
    stub(monkeypatch, [cell(0, 0.01)])
    r = client.post("/v1/optimize", json=payload)
    assert r.status_code == 400 and r.json()["code"] == "invalid_request"


def test_priorities_change_the_tiebreak(client, monkeypatch):
    # fetch_candidates normally applies the priorities; check the request is parsed.
    seen = {}

    def fake(conn, lat, lon, radius, prio):
        seen["factors"] = prio.factors
        return [cell(0, 0.01)]

    stub(monkeypatch, [])
    monkeypatch.setattr(optimize, "fetch_candidates", fake)
    client.post(
        "/v1/optimize",
        json={"anchors": [WORK_ANCHOR], "factors": ["gym", "grocery"], "weights": {"gym": 20}},
    )
    assert seen["factors"] == ["grocery", "gym"]
