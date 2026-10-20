# ruff: noqa: F401, F811  (the imported `client` fixture is shadowed by locals)
"""Priority-aware /improve, /similar and explanations (no network, no database)."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api import improve, main, similar
from api.explain import build_explanation
from api.mapdata import InvalidMapRequest
from api.metro_stats import ColumnStats, get_stats
from api.priorities import TOGGLEABLE_FACTORS, parse_priorities
from api.schemas import SubScores
from scoring.similarity import SIMILARITY_COLUMNS
from tests.test_api_area import CLICK
from tests.test_api_improve import LAT, LON, OWN, aggregate, cell, miles_lat
from tests.test_api_improve import FakeConn as ImproveConn
from tests.test_api_similar import cand, scores
from tests.test_explanation_endpoints import client  # (fixture reused from the explanation tests)

# --- parsing ----------------------------------------------------------------


def test_default_is_all_thirteen_factors_none_hidden():
    p = parse_priorities(None)
    assert not p.explicit
    assert len(p.factors) == 13 == len(TOGGLEABLE_FACTORS)
    assert {"shopping", "recreation", "gasConvenience", "traffic"} <= set(p.factors)


def test_explicit_factors_contract_order_weights_and_errors():
    p = parse_priorities("transit, cafe", "cafe:3,grocery:9")
    assert p.explicit and p.factors == ["cafe", "transit"]
    assert p.spec.weights == {"cafe": 3.0, "transit": 14.0}  # grocery override ignored
    assert p.ordered_by_weight() == ["transit", "cafe"]  # heaviest first
    assert p.cache_part == "cafe:3,transit:14"
    assert parse_priorities(None, "cafe:2").explicit
    for bad in ("", "cafe,", "nope"):
        with pytest.raises(InvalidMapRequest):
            parse_priorities(bad)
    with pytest.raises(InvalidMapRequest):
        parse_priorities("cafe", "cafe:0")


def test_composite_ignores_null_and_unselected():
    p = parse_priorities("grocery,gym")  # default weights 14 and 9
    assert p.composite_from_keys({"grocery": 80, "gym": 50, "cafe": 0}) == pytest.approx(
        (80 * 14 + 50 * 9) / 23
    )
    assert p.composite_from_keys({"grocery": 80, "gym": None}) == 80.0
    assert p.composite_from_keys({"cafe": 10}) is None


@pytest.mark.parametrize("path", ["/v1/improve", "/v1/similar", "/v1/area/explanation"])
def test_bad_factors_is_400(path):
    r = TestClient(main.app).get(path, params={"lat": LAT, "lon": LON, "factors": "bogus"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_request"


# --- improve ----------------------------------------------------------------


@pytest.fixture
def imp(monkeypatch):
    state = {"agg": aggregate(grocery=41.0, cafe=60.0, gym=20.0), "cells": []}
    monkeypatch.setattr(main, "get_connection", lambda: ImproveConn())
    monkeypatch.setattr(main, "_resolve_area", lambda la, lo: ({"id": 1}, state["agg"], {}, {}))
    monkeypatch.setattr(main, "get_scored_cells_in_bbox", lambda c, *a: state["cells"])
    monkeypatch.setattr(improve, "places_for_factor", lambda *a: [])
    return state, TestClient(main.app)


def get_improve(client, **params):
    return client.get("/v1/improve", params={"lat": LAT, "lon": LON, **params}).json()


def test_improve_only_considers_selected_factors(imp):
    _, client = imp
    body = get_improve(client, factors="grocery,cafe")
    assert [s["factor"] for s in body["suggestions"]] == ["grocery", "cafe"]  # gym (20) skipped
    assert body["priorities"] == ["grocery", "cafe"]
    default = get_improve(client)
    assert default["suggestions"][0]["factor"] == "gym"
    assert len(default["priorities"]) == 13


def test_improve_no_weak_selected_factor_gives_empty_suggestions_but_best_nearby(imp):
    state, client = imp
    # Selected transit/restaurant are 90; the weak ones are not selected.
    state["cells"] = [cell(miles_lat(0.5), 50, transit=99.0, restaurant=99.0)]
    body = get_improve(client, factors="transit,restaurant")
    assert body["suggestions"] == []
    # Selected composite: area 90 -> neighbour 99 (gain 9) although stored composite is lower.
    assert body["bestNearby"]["compositeScore"] == 99
    assert body["bestNearby"]["compositeGain"] == 9
    assert body["composite"] == 90.0


def test_best_nearby_uses_selected_composite_not_stored(imp):
    state, client = imp
    state["agg"] = aggregate(grocery=50.0, transit=50.0)
    state["cells"] = [
        # Stored composite is huge but it is worse on the selected factor.
        cell(miles_lat(0.4), 99, grocery=40.0, transit=40.0),
        cell(miles_lat(0.6), 60, grocery=60.0, transit=60.0),
        cell(miles_lat(0.2), 99, geohash=OWN, grocery=99.0, transit=99.0),
    ]
    body = get_improve(client, factors="grocery,transit")
    assert body["bestNearby"]["compositeScore"] == 60 and body["bestNearby"]["compositeGain"] == 10
    # Without `factors` the stored composite (99 vs 70) still drives it.
    assert get_improve(client)["bestNearby"]["compositeScore"] == 99


def test_legacy_keys_alias_and_non_place_factors_are_never_suggestions(imp):
    state, client = imp
    state["agg"] = aggregate(road=1.0, emergency_corridor=1.0, airport=1.0)
    body = get_improve(client, factors="road,premiumRetail,grocery")
    assert body["priorities"] == ["grocery", "shopping", "traffic"]
    assert all(
        s["factor"] not in ("traffic", "emergencyCorridor", "airport") for s in body["suggestions"]
    )
    assert not {"traffic", "emergencyCorridor", "airport"} & set(improve.IMPROVABLE)
    assert {"shopping", "recreation", "gasConvenience"} <= set(improve.IMPROVABLE)


# --- similar ----------------------------------------------------------------


@pytest.fixture
def sim(monkeypatch):
    state = {"target": scores(), "cands": [], "limit": None, "stats": {}}
    monkeypatch.setattr(main, "get_connection", lambda: ImproveConn())
    monkeypatch.setattr(
        main, "get_geo_entity_by_geohash", lambda c, g: {"id": "g1", "metro_area": "nyc"}
    )
    monkeypatch.setattr(main, "fetch_target", lambda c, i, v: state["target"])

    def neighbours(c, i, v, metro, limit, spread=None):
        state["limit"] = limit
        return state["cands"]

    monkeypatch.setattr(main, "fetch_neighbours", neighbours)
    monkeypatch.setattr(main, "get_stats", lambda c, v, m: state["stats"])
    monkeypatch.setattr(similar, "area_label", lambda c, la, lo: None)
    return state, TestClient(main.app)


def test_similar_reranks_by_selected_factors_and_threshold_six(sim):
    state, client = sim
    stats = {c: ColumnStats(50.0, 10.0, tuple(range(101))) for c in SIMILARITY_COLUMNS}
    state["stats"] = stats
    state["cands"] = [
        # Nearest on the full profile but very different on transit.
        cand(miles_lat(2.0), 0.5, transit=90.0),
        # Farther on the full profile, identical on transit/cafe, differs only on gym (unselected).
        cand(miles_lat(4.0), 3.0, gym=80.0, cafe=57.0),
    ]
    body = client.get(
        "/v1/similar", params={"lat": LAT, "lon": LON, "k": 2, "factors": "transit,cafe"}
    ).json()
    assert state["limit"] == 200  # widest pool when re-ranking
    assert body["priorities"] == ["cafe", "transit"]
    first, second = body["results"]
    assert first["distanceLabel"] == "4.0 mi"  # re-ranked ahead of the full-profile winner
    # cafe +7 passes the new threshold of 6; unselected gym (+30) is not reported.
    assert [d["factor"] for d in first["differences"]] == ["cafe"]
    assert first["summary"] == "7 points better for cafes."
    assert second["differences"][0]["factor"] == "transit"


def test_similar_without_factors_keeps_distance_order(sim):
    state, client = sim
    state["cands"] = [cand(miles_lat(2.0), 0.5, transit=90.0), cand(miles_lat(4.0), 3.0)]
    body = client.get("/v1/similar", params={"lat": LAT, "lon": LON, "k": 2}).json()
    assert body["results"][0]["distanceLabel"] == "2.0 mi"
    assert state["limit"] == 40
    assert len(body["priorities"]) == 13


def test_rerank_uses_z_scores_and_missing_scores_are_average():
    pri = parse_priorities("school")
    stats = {"school_score": ColumnStats(50.0, 10.0, tuple(range(101)))}
    target = scores(school=None)  # imputed to the mean -> z 0
    out = similar.rerank(
        target,
        [{"school_score": 80.0, "dist": 9.0}, {"school_score": 55.0, "dist": 9.0}],
        pri,
        stats,
    )
    # z = 0.5 and 3.0 -> weighted by 13/1 for a single factor
    assert [c["school_score"] for c in out] == [55.0, 80.0]
    assert out[0]["dist"] == pytest.approx((13 * 0.25) ** 0.5)


def test_differences_threshold_is_six():
    assert similar.DIFF_MIN_POINTS == 6


# --- metro stats ------------------------------------------------------------


def test_percentile_and_median():
    st = ColumnStats(50.0, 10.0, tuple(float(i) for i in range(101)))
    assert st.percentile(0) == 0 and st.percentile(50) == 50 and st.percentile(100) == 100
    assert st.median == 50


def test_get_stats_degrades_without_a_database():
    assert get_stats(None, "no-such-version") is None


# --- rule-based explanations ----------------------------------------------

SUBS = SubScores(grocery=91.4, transit=72.0, gas_convenience=12.0, cafe=99.0)
NEAREST = {"grocery": 300.0, "transit": 2000.0, "cafe": 100.0}


def test_rule_based_fallback_leads_with_priorities():
    text = build_explanation(SUBS, NEAREST, ["transit", "cafe"])
    assert text.startswith("For your priorities, cafe access is strongest (99/100)")
    assert "transit access is weakest (72/100)" in text.split(".")[0] + "."
    assert build_explanation(SUBS, NEAREST).startswith("This location's strongest")


# --- explanation endpoints --------------------------------------------------


def test_explanation_endpoints_speak_to_priorities(client):
    r = client.get(
        "/v1/area/explanation", params={"lat": CLICK[0], "lon": CLICK[1], "factors": "cafe,transit"}
    )
    body = r.json()
    assert body["priorities"] == ["cafe", "transit"] and body["source"] == "rules"
    assert body["explanation"].startswith("For your priorities,")
    r = client.get(f"/v1/score/{uuid4()}/explanation", params={"factors": "gym"})
    assert r.json()["priorities"] == ["gym"]
    # No factors: the plain rule-based text, 13 priorities echoed.
    body = client.get("/v1/area/explanation", params={"lat": CLICK[0], "lon": CLICK[1]}).json()
    assert body["explanation"].startswith("This area's strongest") and len(body["priorities"]) == 13
