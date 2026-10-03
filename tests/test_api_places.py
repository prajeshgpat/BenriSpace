"""GET /v1/places (fake connection, no database)."""

import pytest
from fastapi.testclient import TestClient

from api import main
from common.units import M_PER_MI

LAT, LON = 40.758, -73.9855


class FakeCursor:
    def __init__(self, rows_by_category):
        self.rows_by_category = rows_by_category
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.rows = list(self.rows_by_category.get(params[0], []))

    def __iter__(self):
        return iter(self.rows)


class FakeConn:
    def __init__(self, rows_by_category):
        self.rows_by_category = rows_by_category
        self.categories = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self.rows_by_category)


def row(name, category, dlat, brand=None):
    # dlat degrees north of the query point: ~111,320 m per degree.
    return {
        "name": name,
        "brand": brand,
        "category": category,
        "latitude": LAT + dlat,
        "longitude": LON,
    }


@pytest.fixture
def make_client(monkeypatch):
    def make(rows):
        monkeypatch.setattr(main, "get_connection", lambda: FakeConn(rows))
        return TestClient(main.app)

    return make


def test_feet_and_miles_labels(make_client):
    near = 100 / 111_320  # ~100 m = ~328 ft
    far = 0.4 * M_PER_MI / 111_320
    client = make_client({"cafe": [row("Far", "cafe", far), row("Near", "cafe", near)]})
    r = client.get("/v1/places", params={"lat": LAT, "lon": LON, "factor": "cafe"})
    assert r.status_code == 200
    body = r.json()
    assert body["factor"] == "cafe" and body["radiusMi"] == 1.0
    assert [p["name"] for p in body["places"]] == ["Near", "Far"]
    assert body["places"][0]["distanceLabel"] == "350 ft"
    assert body["places"][0]["distanceMi"] == 0.06
    assert body["places"][1]["distanceLabel"] == "0.4 mi"
    assert body["places"][1]["distanceMi"] == 0.4
    assert body["places"][0]["direction"] == "N"
    assert set(body["places"][0]) == {
        "name", "brand", "category", "distanceMi", "distanceLabel", "direction",
        "latitude", "longitude",
    }  # fmt: skip
    assert "public" in r.headers["cache-control"]


def test_empty_results(make_client):
    client = make_client({})
    r = client.get("/v1/places", params={"lat": LAT, "lon": LON, "factor": "grocery"})
    assert r.status_code == 200
    assert r.json()["places"] == []


def test_category_mapping(make_client):
    client = make_client({"gas_station": [row("Shell", "gas_station", 0.001, "Shell")]})
    r = client.get("/v1/places", params={"lat": LAT, "lon": LON, "factor": "gasStation"})
    assert r.json()["places"][0]["brand"] == "Shell"


def test_premium_retail_merges_nearest_first_and_limits(make_client):
    client = make_client(
        {
            "whole_foods": [row("WF", "whole_foods", 0.004)],
            "starbucks": [row("SB1", "starbucks", 0.001), row("SB2", "starbucks", 0.006)],
            "target": [row("T", "target", 0.002)],
        }
    )
    params = {"lat": LAT, "lon": LON, "factor": "premiumRetail", "radiusMi": 2}
    r = client.get("/v1/places", params=params)
    assert [p["name"] for p in r.json()["places"]] == ["SB1", "T", "WF", "SB2"]
    r = client.get("/v1/places", params={**params, "limit": 2})
    assert [p["name"] for p in r.json()["places"]] == ["SB1", "T"]


def test_radius_excludes_far_places(make_client):
    client = make_client({"bar": [row("Far", "bar", 0.05)]})  # ~3.5 mi
    r = client.get("/v1/places", params={"lat": LAT, "lon": LON, "factor": "bar"})
    assert r.json()["places"] == []


@pytest.mark.parametrize(
    "extra",
    [
        {"factor": "noise"},
        {"factor": "cafe", "radiusMi": 0},
        {"factor": "cafe", "radiusMi": 5.1},
        {"factor": "cafe", "limit": 0},
        {"factor": "cafe", "limit": 21},
        {"factor": "cafe", "lat": 91},
    ],
)
def test_bad_requests(make_client, extra):
    client = make_client({})
    r = client.get("/v1/places", params={"lat": LAT, "lon": LON, **extra})
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_request"


def test_out_of_coverage(make_client):
    client = make_client({})
    r = client.get("/v1/places", params={"lat": 34.05, "lon": -118.24, "factor": "cafe"})
    assert r.status_code == 422
    assert r.json()["code"] == "out_of_coverage"
