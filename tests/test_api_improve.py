"""GET /v1/improve (fakes and monkeypatching, no database)."""

import pytest
from fastapi.testclient import TestClient

from api import improve, main
from api.improve import best_nearby, weak_factors
from common.geo import encode as geohash_encode
from common.units import M_PER_MI

LAT, LON = 40.758, -73.9855
OWN = geohash_encode(LAT, LON, precision=6)
M_PER_DEG = 111_320.0


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def aggregate(**scores):
    base = {c: 90.0 for c in (
        "grocery", "gym", "cafe", "restaurant", "bar", "transit", "school", "premium_retail",
        "gas_station", "convenience_store", "road", "emergency_corridor", "airport",
        "trail_popularity",
    )}  # fmt: skip
    base.update(scores)
    row = {f"{k}_score": v for k, v in base.items()}
    row.update(composite_score=70.0, weights_version="v2-handtuned")
    return row


def cell(dlat, composite, geohash="x", **scores):
    row = {f"{k}_score": v for k, v in scores.items()}
    row.update(latitude=LAT + dlat, longitude=LON, composite_score=composite, geohash=geohash)
    return row


def miles_lat(mi):
    return mi * M_PER_MI / M_PER_DEG


def place(name, dlat=0.0, brand=None):
    return {
        "name": name, "brand": brand, "category": "x", "distance_mi": 0.3,
        "distance_label": "0.3 mi", "direction": "W", "latitude": LAT, "longitude": LON,
    }  # fmt: skip


@pytest.fixture
def setup(monkeypatch):
    state = {"agg": aggregate(grocery=41.0, cafe=60.0, gym=20.0), "cells": [], "places": {}}
    monkeypatch.setattr(main, "get_connection", lambda: FakeConn())
    monkeypatch.setattr(main, "_resolve_area", lambda la, lo: ({"id": 1}, state["agg"], {}, {}))
    monkeypatch.setattr(main, "get_scored_cells_in_bbox", lambda c, *a: state["cells"])
    monkeypatch.setattr(
        improve, "places_for_factor", lambda c, la, lo, f, r, n: state["places"].get(f, [])
    )
    return state, TestClient(main.app)


def get(client, **params):
    return client.get("/v1/improve", params={"lat": LAT, "lon": LON, **params})


def test_weak_selection_order_and_skips_negative(setup):
    state, client = setup
    # Negative factors are very low but must never be suggested.
    state["agg"] = aggregate(
        grocery=41.0, cafe=60.0, gym=20.0, gas_station=1.0, road=2.0, airport=3.0, bar=75.0
    )
    body = get(client).json()
    assert [s["factor"] for s in body["suggestions"]] == ["gym", "grocery", "cafe"]
    assert [s["score"] for s in body["suggestions"]] == [20, 41, 60]
    assert get(client, maxSuggestions=1).json()["suggestions"][0]["factor"] == "gym"
    assert body["composite"] == 70.0 and body["radiusMi"] == 1.0
    assert body["suggestions"][0]["label"] == "Gym"


def test_weak_factors_threshold_and_none():
    scores = {"grocery": 74.9, "gym": 75.0, "cafe": None, "premiumRetail": 10, "gasStation": 0}
    # premiumRetail is never its own suggestion
    assert [k for k, _ in weak_factors(scores, 5)] == ["grocery"]


def test_no_weak_factors(setup):
    state, client = setup
    state["agg"] = aggregate()
    assert get(client).json()["suggestions"] == []


def test_places_empty_and_tip(setup):
    state, client = setup
    state["places"] = {"grocery": [place("Aldi", brand="Aldi")]}
    body = get(client, maxSuggestions=2).json()
    gym, grocery = body["suggestions"]
    assert gym["places"] == []
    assert gym["tip"] == "Gym is your weakest factor (20)."
    assert grocery["places"][0]["name"] == "Aldi"
    assert set(grocery["places"][0]) == {
        "name", "brand", "distanceMi", "distanceLabel", "direction", "latitude", "longitude",
    }  # fmt: skip
    assert grocery["tip"] == (
        "Grocery is a weak spot (41). The closest option is Aldi, 0.3 mi west."
    )
    assert grocery["betterArea"] is None


def test_better_area_threshold_and_choice(setup):
    state, client = setup
    state["cells"] = [
        cell(miles_lat(0.3), 80, grocery=50.0),  # +9: below threshold
        cell(miles_lat(0.4), 72, grocery=60.0),  # +19
        cell(miles_lat(0.5), 75, grocery=60.0),  # +19, higher composite -> wins
        cell(miles_lat(0.2), 99, geohash=OWN, grocery=99.0),  # own cell ignored
        cell(miles_lat(2.0), 99, grocery=99.0),  # outside radius
    ]
    body = get(client, maxSuggestions=2).json()
    grocery = next(s for s in body["suggestions"] if s["factor"] == "grocery")
    better = grocery["betterArea"]
    assert better["factorScore"] == 60 and better["factorGain"] == 19
    assert better["compositeScore"] == 75 and better["compositeGain"] == 5
    assert better["direction"] == "N" and better["distanceMi"] == 0.5
    assert better["distanceLabel"] == "0.5 mi"
    assert "The area about 0.5 mi north scores 60 on grocery." in grocery["tip"]
    gym = next(s for s in body["suggestions"] if s["factor"] == "gym")
    assert gym["betterArea"] is None  # cells have no gym score


def test_best_nearby_threshold(setup):
    state, client = setup
    state["cells"] = [
        cell(miles_lat(0.3), 72.9),
        cell(miles_lat(0.6), 73.0),
        cell(-miles_lat(0.2), 71),
    ]
    nb = get(client).json()["bestNearby"]
    assert nb == {
        "latitude": pytest.approx(LAT + miles_lat(0.6)),
        "longitude": LON,
        "direction": "N",
        "distanceLabel": "0.6 mi",
        "compositeScore": 73,
        "compositeGain": 3,
    }
    state["cells"] = [cell(miles_lat(0.3), 72.9)]
    assert get(client).json()["bestNearby"] is None


def test_best_nearby_feet_label():
    n = [(cell(0.0002, 90), 22.0)]
    assert best_nearby(n, LAT, LON, 70)["distance_label"] == "50 ft"


def test_no_metric_keys(setup):
    state, client = setup
    state["cells"] = [cell(miles_lat(0.5), 90, grocery=90.0)]
    state["places"] = {"grocery": [place("Aldi")]}
    text = get(client).text.lower()
    assert '_m"' not in text and "meters" not in text and "km" not in text
    assert "public" in get(client).headers["cache-control"]


@pytest.mark.parametrize(
    "params",
    [{"radiusMi": 0}, {"radiusMi": 3.5}, {"maxSuggestions": 0}, {"maxSuggestions": 6}, {"lat": 91}],
)
def test_400(setup, params):
    r = get(setup[1], **params)
    assert r.status_code == 400 and r.json()["code"] == "invalid_request"


def test_422_out_of_coverage(monkeypatch):
    monkeypatch.setattr(main, "in_coverage", lambda la, lo: False)
    r = TestClient(main.app).get("/v1/improve", params={"lat": 0, "lon": 0})
    assert r.status_code == 422 and r.json()["code"] == "out_of_coverage"


def test_404_and_cell_fallback(setup, monkeypatch):
    state, client = setup
    not_found = main._error(404, "area_not_found", "none")
    monkeypatch.setattr(main, "_resolve_area", lambda la, lo: not_found)
    monkeypatch.setattr(main, "get_geo_entity_by_geohash", lambda c, g: {"id": "g1"})
    monkeypatch.setattr(main, "get_latest_score", lambda c, i, v: None)
    r = get(client)
    assert r.status_code == 404 and r.json()["code"] == "area_not_found"
    monkeypatch.setattr(main, "get_latest_score", lambda c, i, v: state["agg"])
    r = get(client)
    assert r.status_code == 200 and r.json()["suggestions"][0]["factor"] == "gym"
