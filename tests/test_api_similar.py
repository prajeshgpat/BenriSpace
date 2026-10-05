"""GET /v1/similar (fakes and monkeypatching, no database)."""

import pytest
from fastapi.testclient import TestClient

from api import main, similar
from api.similar import SIMILARITY_MAX_DIST, differences, similarity, spread_out, summary
from common.units import M_PER_MI
from scoring.similarity import SIMILARITY_COLUMNS

LAT, LON = 40.758, -73.9855
M_PER_DEG = 111_320.0


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def scores(**over):
    row = {c: 50.0 for c in SIMILARITY_COLUMNS}
    row.update({f"{k}_score": v for k, v in over.items()})
    return row


def cand(dlat, dist, composite=70.0, **over):
    return {
        "latitude": LAT + dlat, "longitude": LON, "dist": dist,
        "composite_score": composite, **scores(**over),
    }  # fmt: skip


def miles_lat(mi):
    return mi * M_PER_MI / M_PER_DEG


@pytest.fixture
def setup(monkeypatch):
    state = {"target": scores(), "cands": [], "limit": None}
    monkeypatch.setattr(main, "get_connection", lambda: FakeConn())
    monkeypatch.setattr(
        main, "get_geo_entity_by_geohash", lambda c, g: {"id": "g1", "metro_area": "nyc"}
    )
    monkeypatch.setattr(main, "fetch_target", lambda c, i, v: state["target"])

    def neighbours(c, i, v, metro, limit, spread=None):
        state["limit"] = limit
        return state["cands"]

    monkeypatch.setattr(main, "fetch_neighbours", neighbours)
    monkeypatch.setattr(similar, "area_label", lambda c, la, lo: "Area bounded by A and B")
    return state, TestClient(main.app)


def get(client, **params):
    return client.get("/v1/similar", params={"lat": LAT, "lon": LON, **params})


def test_similarity_bounds():
    assert similarity(0.0) == 100
    assert similarity(SIMILARITY_MAX_DIST / 2) == 50
    assert similarity(SIMILARITY_MAX_DIST) == 0
    assert similarity(SIMILARITY_MAX_DIST * 3) == 0


def test_differences_threshold_order_and_cap():
    target = scores()
    row = scores(transit=64.0, emergency_corridor=38.0, grocery=59.9, gym=70.0, cafe=61.0, bar=30.0)
    diffs = differences(target, row)
    assert [d["factor"] for d in diffs] == ["gym", "bar", "transit"]  # 20,20,14 ; cap 3
    assert diffs[0]["delta"] == 20 and diffs[1]["delta"] == -20
    assert all(abs(d["delta"]) >= 6 for d in diffs)
    # exactly 6 counts (threshold lowered from 10), 5.9 does not
    assert differences(target, scores(cafe=56.0))[0]["delta"] == 6
    assert differences(target, scores(cafe=55.9)) == []
    # null on either side is skipped; camelCase wire key
    assert differences(scores(school=None), scores(school=90.0)) == []
    assert differences(target, scores(emergency_corridor=20.0))[0]["factor"] == "emergencyCorridor"


def test_summary_sentence():
    diffs = [
        {"factor": "transit", "label": "transit", "delta": 14},
        {"factor": "emergencyCorridor", "label": "noise", "delta": -12},
    ]
    assert summary(diffs) == "14 points better for transit, 12 points weaker for noise."
    assert summary([]) == "Very similar across all factors."


def test_spread_out_min_separation_and_k():
    cands = [
        cand(miles_lat(0.5), 0.1),  # too close to the point
        cand(miles_lat(2.0), 0.2),  # kept
        cand(miles_lat(2.4), 0.3),  # within 1 mi of the kept one
        cand(miles_lat(4.0), 0.4),  # kept
        cand(miles_lat(6.0), 0.5),  # beyond k
    ]
    out = spread_out(LAT, LON, cands, 2, 1.0)
    assert [c["dist"] for c in out] == [0.2, 0.4]
    assert len(spread_out(LAT, LON, cands, 10, 0.0)) == 5
    assert len(spread_out(LAT, LON, cands, 10, 1.0)) == 3


def test_endpoint_shape_units_and_overfetch(setup):
    state, client = setup
    state["cands"] = [
        cand(miles_lat(2.0), 1.5, 72.4, transit=64.0, emergency_corridor=38.0),
        cand(miles_lat(2.2), 1.6),
        cand(miles_lat(4.0), 9.0),
    ]
    resp = get(client, k=2)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=300"
    assert state["limit"] == 40
    body = resp.json()
    assert body["minSeparationMi"] == 1.0
    assert len(body["results"]) == 2
    first = body["results"][0]
    assert first["direction"] == "N"
    assert first["distanceLabel"] == "2.0 mi"
    assert first["similarity"] == 75
    assert first["compositeScore"] == 72
    assert first["areaLabel"] == "Area bounded by A and B"
    assert first["differences"] == [
        {"factor": "transit", "label": "transit", "delta": 14},
        {"factor": "emergencyCorridor", "label": "noise", "delta": -12},
    ]
    assert first["summary"] == "14 points better for transit, 12 points weaker for noise."
    assert body["results"][1]["similarity"] == 0
    assert "distanceMi" not in first and "distanceKm" not in first


def test_overfetch_cap():
    assert similar.overfetch_limit(10) == 200
    assert similar.overfetch_limit(5) == 100
    assert similar.overfetch_limit(1) == 20


def test_area_label_null(setup, monkeypatch):
    state, client = setup
    monkeypatch.setattr(similar, "area_label", lambda c, la, lo: None)
    state["cands"] = [cand(miles_lat(2.0), 1.0)]
    assert get(client).json()["results"][0]["areaLabel"] is None


@pytest.mark.parametrize(
    "params",
    [{"k": 0}, {"k": 11}, {"minSeparationMi": -1}, {"minSeparationMi": 10.5}, {"k": "x"}],
)
def test_bad_params_400(setup, params):
    _, client = setup
    resp = get(client, **params)
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"


def test_missing_lat_400(setup):
    _, client = setup
    assert client.get("/v1/similar", params={"lon": LON}).status_code == 400


def test_out_of_coverage_422(setup):
    _, client = setup
    resp = client.get("/v1/similar", params={"lat": 34.05, "lon": -118.24})
    assert resp.status_code == 422
    assert resp.json()["code"] == "out_of_coverage"


def test_no_score_row_404(setup):
    state, client = setup
    state["target"] = None
    resp = get(client)
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_differences_cover_the_13_factor_columns_with_wire_keys():
    target = scores()
    row = {**scores(), "shopping_score": 80.0, "gas_convenience_score": 20.0, "road_score": 75.0}
    target.update(shopping_score=50.0, gas_convenience_score=50.0, road_score=50.0)
    diffs = differences(target, row)
    assert [(d["factor"], d["delta"]) for d in diffs] == [
        ("shopping", 30), ("gasConvenience", -30), ("traffic", 25),
    ]  # fmt: skip
    assert [d["label"] for d in diffs] == ["shopping", "gas and convenience", "traffic"]
    # restricted to selected columns
    assert [d["factor"] for d in differences(target, row, ["shopping_score"])] == ["shopping"]


def test_similar_queries_read_legacy_columns_for_v2_rows():
    assert (
        "coalesce(s.shopping_score, s.premium_retail_score) as shopping_score"
        in similar._SCORE_SELECT
    )
    assert (
        "coalesce(s.recreation_score, s.trail_popularity_score) as recreation_score"
        in similar._SCORE_SELECT
    )
    assert "s.gas_convenience_score" in similar._SCORE_SELECT


def test_metro_stats_cover_the_13_factors_through_legacy_fallbacks():
    from api import metro_stats

    sql = metro_stats._sql(False)
    assert len(metro_stats.STATS_COLUMNS) == 13
    assert "coalesce(s.shopping_score, s.premium_retail_score)" in sql
    assert "s.gas_convenience_score" in sql and "s.road_score" in sql
