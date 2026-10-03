"""AI explanations: evidence, grounding validation and endpoint wiring
(no network, no database)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api import ai_explain, main
from api.schemas import SubScores
from tests.test_api_area import CLICK, make_aggregate, make_area

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
SUBS = SubScores(grocery=91.4, transit=72.0, gas_station=12.0)
NEAREST = {"grocery": 300.0, "transit": 2000.0, "gasStation": None}


def evidence():
    return ai_explain.build_evidence(SUBS, NEAREST, 63.6, "this location", "v2-handtuned")


GOOD = {
    "summary": "This spot scores 64 overall. Grocery access is strong at 91.",
    "strengths": ["Grocery access 91 with a store about 0.2 mi away"],
    "weaknesses": ["Distance from gas stations is only 12"],
}


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- evidence ---------------------------------------------------------------


def test_evidence_shape_and_no_metric_units():
    ev = evidence()
    assert ev["composite"] == 64
    assert {f["factor"] for f in ev["factors"]} == {"grocery", "transit", "gasStation"}
    by = {f["factor"]: f for f in ev["factors"]}
    assert by["grocery"]["score"] == 91 and by["grocery"]["nearest"] == "0.2 mi"
    assert by["transit"]["nearest"] == "1.2 mi"
    assert by["gasStation"]["nearest"] is None
    dumped = str(ev).lower()
    assert "km" not in dumped and "meter" not in dumped and "_m" not in dumped


# --- validation -------------------------------------------------------------


def test_validate_accepts_grounded():
    assert ai_explain.validate_output(GOOD, evidence())


def test_validate_rejects_invented_number():
    bad = dict(GOOD, summary="This spot scores 64 overall with 5 cafes nearby.")
    assert not ai_explain.validate_output(bad, evidence())


@pytest.mark.parametrize("text", ["A store is 2 km away", "It is 300 meters away", "about 300 m away"])
def test_validate_rejects_metric(text):
    assert not ai_explain.validate_output(dict(GOOD, summary=text), evidence())


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {"summary": 5, "strengths": [], "weaknesses": []},
        {"summary": "ok", "strengths": "x", "weaknesses": []},
        {"summary": "ok", "strengths": [1], "weaknesses": []},
        {"summary": "x" * 651, "strengths": [], "weaknesses": []},
        {"summary": "ok", "strengths": ["x" * 141], "weaknesses": []},
        {"summary": "ok", "strengths": ["a"] * 3, "weaknesses": []},
    ],
)
def test_validate_rejects_bad_shape(bad):
    assert not ai_explain.validate_output(bad, evidence())


def test_format_explanation():
    assert ai_explain.format_explanation(GOOD).startswith("This spot scores 64 overall.")
    assert " Strengths: Grocery access 91" in ai_explain.format_explanation(GOOD)
    assert ai_explain.format_explanation({"summary": "Hi.", "strengths": [], "weaknesses": []}) == "Hi."


def test_ai_explanation_none_when_llm_none(monkeypatch):
    monkeypatch.setattr(ai_explain, "complete_json", lambda *a, **k: None)
    assert ai_explain.ai_explanation(None, "k", SUBS, NEAREST, 63.6, "x", "v") is None


def test_ai_explanation_rejects_ungrounded_even_if_returned(monkeypatch):
    monkeypatch.setattr(
        ai_explain, "complete_json", lambda *a, **k: dict(GOOD, summary="Score 77 here.")
    )
    assert ai_explain.ai_explanation(None, "k", SUBS, NEAREST, 63.6, "x", "v") is None


# --- endpoints --------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    calls = []

    def fake_llm(*args, **kwargs):
        calls.append(kwargs.get("kind"))
        return {
            "summary": "Scores 64 overall; grocery access is 90.",
            "strengths": ["Grocery store about 0.2 mi away"],
            "weaknesses": ["Most other factors sit near 60"],
        }

    monkeypatch.setattr(ai_explain, "complete_json", fake_llm)
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
    c = TestClient(main.app)
    c.llm_calls = calls
    return c


def test_score_explanation_ai(client):
    r = client.get(f"/v1/score/{uuid4()}/explanation")
    assert r.status_code == 200
    assert r.json()["source"] == "ai"
    assert "Strengths:" in r.json()["explanation"]


def test_score_explanation_falls_back_to_rules(client, monkeypatch):
    monkeypatch.setattr(ai_explain, "complete_json", lambda *a, **k: None)
    body = client.get(f"/v1/score/{uuid4()}/explanation").json()
    assert body["source"] == "rules"
    assert "strongest factor" in body["explanation"]


def test_area_explanation_ai(client):
    r = client.get("/v1/area/explanation", params={"lat": CLICK[0], "lon": CLICK[1]})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=300"
    body = r.json()
    assert body["source"] == "ai" and body["areaId"] == 3
    assert client.llm_calls == ["explanation"]


def test_area_explanation_falls_back_to_rules(client, monkeypatch):
    monkeypatch.setattr(ai_explain, "complete_json", lambda *a, **k: None)
    body = client.get(
        "/v1/area/explanation", params={"lat": CLICK[0], "lon": CLICK[1]}
    ).json()
    assert body["source"] == "rules"
    assert "This area's strongest factor" in body["explanation"]


def test_area_explanation_errors(client, monkeypatch):
    assert client.get("/v1/area/explanation").status_code == 400
    assert client.get("/v1/area/explanation", params={"lat": 95, "lon": 1}).status_code == 400
    r = client.get("/v1/area/explanation", params={"lat": 10, "lon": 10})
    assert r.status_code == 422 and r.json()["code"] == "out_of_coverage"
    monkeypatch.setattr(main, "get_area_candidates", lambda c, la, lo: [])
    r = client.get("/v1/area/explanation", params={"lat": CLICK[0], "lon": CLICK[1]})
    assert r.status_code == 404 and r.json()["code"] == "area_not_found"


def test_area_endpoint_makes_no_llm_call(client):
    r = client.get("/v1/area", params={"lat": CLICK[0], "lon": CLICK[1]})
    assert r.status_code == 200
    assert client.llm_calls == []
