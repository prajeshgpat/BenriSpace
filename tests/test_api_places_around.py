"""GET /v1/places/around (fake connection, no database)."""

import pytest
from fastapi.testclient import TestClient

from api import main
from api.places import PIN_FACTORS, pin_factors, places_around

LAT, LON = 40.758, -73.9855


def row(name, category, dlat, dlon=0.0, brand=None):
    return {
        "name": name,
        "brand": brand,
        "category": category,
        "latitude": LAT + dlat,
        "longitude": LON + dlon,
    }


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.queries.append((sql, params))
        # Filter by the category list like the real query; the radius is
        # enforced by the Python haversine pass.
        self.rows = [r for r in self.conn.rows if r["category"] in params[0]]

    def __iter__(self):
        return iter(self.rows)


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self)


def test_pin_factors_filters_unknown_and_legacy():
    assert pin_factors(None) == list(PIN_FACTORS)
    assert pin_factors([]) == list(PIN_FACTORS)
    assert pin_factors(["bar", "airport", "traffic", "gasStation", "cafe", "bar"]) == [
        "cafe",
        "bar",
    ]
    assert pin_factors(["airport"]) == []


def test_places_around_one_query_and_trims_per_factor():
    rows = [row(f"Cafe{i}", "cafe", 0.0005 * (i + 1)) for i in range(5)]
    rows += [row("Shell", "gas_station", 0.001), row("Deli", "convenience_store", 0.0002)]
    rows += [row("FarBar", "bar", 0.5)]  # outside the radius
    conn = FakeConn(rows)
    out = places_around(conn, LAT, LON, ["cafe", "gasConvenience", "bar"], 0.5, 3)
    assert len(conn.queries) == 1
    assert [p["name"] for p in out if p["factor"] == "cafe"] == ["Cafe0", "Cafe1", "Cafe2"]
    gas = [p["name"] for p in out if p["factor"] == "gasConvenience"]
    assert gas == ["Deli", "Shell"]
    assert not [p for p in out if p["factor"] == "bar"]


def test_places_around_no_factors_skips_query():
    conn = FakeConn([])
    assert places_around(conn, LAT, LON, [], 0.5, 5) == []
    assert conn.queries == []


@pytest.fixture
def make_client(monkeypatch):
    def make(rows):
        monkeypatch.setattr(main, "get_connection", lambda: FakeConn(rows))
        return TestClient(main.app)

    return make


def test_endpoint_shape_and_cache(make_client):
    client = make_client([row("Joe", "cafe", 0.001, brand="Joe")])
    r = client.get("/v1/places/around", params={"lat": LAT, "lon": LON, "factors": "cafe,airport"})
    assert r.status_code == 200
    body = r.json()
    assert body["radiusMi"] == 0.5
    assert set(body["places"][0]) == {
        "factor", "name", "brand", "category", "latitude", "longitude", "distanceMi",
    }  # fmt: skip
    assert body["places"][0]["factor"] == "cafe"
    assert "public" in r.headers["cache-control"]


def test_endpoint_bounds_and_coverage(make_client):
    client = make_client([])
    base = {"lat": LAT, "lon": LON}
    assert client.get("/v1/places/around", params={**base, "radiusMi": 3}).status_code == 400
    assert client.get("/v1/places/around", params={**base, "radiusMi": 0.05}).status_code == 400
    assert client.get("/v1/places/around", params={**base, "perFactor": 31}).status_code == 400
    r = client.get("/v1/places/around", params={"lat": 10, "lon": 10})
    assert r.status_code == 422
    assert client.get("/v1/places/around", params=base).status_code == 200
