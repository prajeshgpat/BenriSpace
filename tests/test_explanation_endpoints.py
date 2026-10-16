"""Explanation endpoints and the grounding helpers chat uses (no network, no
database). Explanations are rule-based only; no endpoint here calls the LLM."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api import grounding, main
from tests.test_api_area import CLICK, make_aggregate, make_area


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
    aggregate = make_aggregate()
    aggregate["composite_score"] = 63.6
    monkeypatch.setattr(main, "get_area_aggregate", lambda c, a, v: aggregate)
    score_row = dict(aggregate, weights_version="v2-handtuned")
    monkeypatch.setattr(main, "get_latest_score", lambda c, i, v: score_row)
    return TestClient(main.app)


# --- endpoints --------------------------------------------------------------


def test_score_explanation_is_rule_based(client):
    r = client.get(f"/v1/score/{uuid4()}/explanation")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "rules"
    assert "strongest factor" in body["explanation"]


def test_area_explanation_is_rule_based(client):
    r = client.get("/v1/area/explanation", params={"lat": CLICK[0], "lon": CLICK[1]})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=300"
    body = r.json()
    assert body["source"] == "rules" and body["areaId"] == 3
    assert "This area's strongest factor" in body["explanation"]


def test_area_explanation_errors(client, monkeypatch):
    assert client.get("/v1/area/explanation").status_code == 400
    assert client.get("/v1/area/explanation", params={"lat": 95, "lon": 1}).status_code == 400
    r = client.get("/v1/area/explanation", params={"lat": 10, "lon": 10})
    assert r.status_code == 422 and r.json()["code"] == "out_of_coverage"
    monkeypatch.setattr(main, "get_area_candidates", lambda c, la, lo: [])
    r = client.get("/v1/area/explanation", params={"lat": CLICK[0], "lon": CLICK[1]})
    assert r.status_code == 404 and r.json()["code"] == "area_not_found"


# --- grounding --------------------------------------------------------------


def test_numbers_drop_thousands_separators():
    assert grounding.numbers("1,200 people, 0.2 mi and 64/100") == {"1200", "0.2", "64", "100"}


def test_unknown_proper_nouns_rejects_invented_names():
    haystack = grounding.norm("Key Food is 0.2 mi away; Joe’s Market too")
    assert not grounding.unknown_proper_nouns("Close to Key Food and Joe's Market.", haystack)
    assert grounding.unknown_proper_nouns("Close to Trader Joe's.", haystack)


def test_unknown_proper_nouns_ignores_sentence_starts_and_allowed_words():
    haystack = grounding.norm("nothing named")
    assert not grounding.unknown_proper_nouns("Grocery is close. Tradeoff: slow transit.", haystack)
    assert not grounding.unknown_proper_nouns("Walk there. Tip: go early.", haystack)
