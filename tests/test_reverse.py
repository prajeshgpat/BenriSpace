"""GET /v1/reverse. Providers are never called: payloads are realistic
LocationIQ / Photon responses (captured 2026-10-02) served by a fake client."""

import httpx
import pytest
from fastapi.testclient import TestClient

from api import reverse as reverse_mod
from api.main import app
from api.reverse import ReverseUnavailable, build_label, cache_key, locationiq_props, photon_props

client = TestClient(app)
KEY = "secret-key-123"

LIQ_HOUSE = {
    "display_name": "14A, Rock Street, Jersey City, Hudson County, New Jersey, 07306, USA",
    "address": {
        "house_number": "14A",
        "road": "Rock Street",
        "city": "Jersey City",
        "county": "Hudson County",
        "state": "New Jersey",
        "postcode": "07306",
        "country_code": "us",
    },
}
LIQ_POI = {
    "address": {
        "bank": "Santander",
        "house_number": "9",
        "road": "Journal Square Concourse",
        "neighbourhood": "Hilltop",
        "hamlet": "Bergen Square",
        "village": "Journal Square",
        "city": "Jersey City",
        "state": "New Jersey",
    }
}
LIQ_ROAD = {"address": {"road": "Rock Street", "city": "Jersey City", "state": "New Jersey"}}
LIQ_HOOD = {"address": {"neighbourhood": "Hilltop", "city": "Jersey City", "state": "New Jersey"}}
LIQ_NOTHING = {"address": {"county": "Hudson County", "state": "New Jersey"}}
PHOTON_HOUSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "housenumber": "14A",
                "street": "Rock Street",
                "locality": "Hilltop",
                "district": "Bergen Square",
                "city": "Jersey City",
                "state": "New Jersey",
            },
            "geometry": {"type": "Point", "coordinates": [-74.0619852, 40.7276713]},
        }
    ],
}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    reverse_mod._cache.clear()
    monkeypatch.delenv(reverse_mod.LOCATIONIQ_KEY_ENV, raising=False)


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", f"https://x.test/?key={KEY}")
            raise httpx.HTTPStatusError(
                "boom", request=req, response=httpx.Response(self.status_code, request=req)
            )


def fake_client(routes: dict, calls: list):
    """routes: URL -> Resp or Exception."""

    class Fake:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, url, params=None, headers=None):
            calls.append((url, params))
            outcome = routes[url]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    return Fake


def install(monkeypatch, routes):
    calls: list = []
    monkeypatch.setattr(reverse_mod.httpx, "Client", fake_client(routes, calls))
    return calls


def get(lat=40.7276, lon=-74.062):
    return client.get("/v1/reverse", params={"lat": lat, "lon": lon})


# --- label building -----------------------------------------------------------


def test_house_number_road_locality_state_abbreviated():
    assert build_label(locationiq_props(LIQ_HOUSE)) == "14A Rock Street, Jersey City, NJ"


def test_locality_prefers_city_over_village_and_hamlet():
    assert build_label(locationiq_props(LIQ_POI)) == "9 Journal Square Concourse, Jersey City, NJ"


def test_no_house_number_uses_the_road():
    assert build_label(locationiq_props(LIQ_ROAD)) == "Rock Street, Jersey City, NJ"


def test_no_road_uses_the_neighbourhood():
    assert build_label(locationiq_props(LIQ_HOOD)) == "Hilltop, Jersey City, NJ"


def test_nothing_usable_is_none():
    assert build_label(locationiq_props(LIQ_NOTHING)) is None
    assert build_label({}) is None


def test_unknown_states_are_left_as_is_and_duplicates_dropped():
    assert (
        build_label({"street": "Main St", "locality": "Main St", "state": "Ohio"})
        == "Main St, Ohio"
    )


def test_photon_label():
    assert build_label(photon_props(PHOTON_HOUSE)) == "14A Rock Street, Jersey City, NJ"
    assert photon_props({"features": []}) == {}


def test_malformed_payloads_are_unavailable():
    with pytest.raises(ReverseUnavailable):
        locationiq_props([])
    with pytest.raises(ReverseUnavailable):
        photon_props({"nope": 1})


def test_cache_key_rounds_to_four_decimals():
    assert cache_key(40.727649, -74.061951) == (40.7276, -74.0620)


# --- route --------------------------------------------------------------------


def test_route_uses_locationiq_when_keyed(monkeypatch):
    monkeypatch.setenv(reverse_mod.LOCATIONIQ_KEY_ENV, KEY)
    calls = install(monkeypatch, {reverse_mod.LOCATIONIQ_REVERSE_URL: Resp(200, LIQ_HOUSE)})
    resp = get()
    assert resp.status_code == 200
    assert resp.json() == {
        "label": "14A Rock Street, Jersey City, NJ",
        "latitude": 40.7276,
        "longitude": -74.062,
    }
    assert resp.headers["cache-control"] == "public, max-age=300"
    assert [c[0] for c in calls] == [reverse_mod.LOCATIONIQ_REVERSE_URL]
    assert calls[0][1]["zoom"] == 18 and calls[0][1]["format"] == "json"


def test_route_uses_photon_without_a_key(monkeypatch):
    calls = install(monkeypatch, {reverse_mod.PHOTON_REVERSE_URL: Resp(200, PHOTON_HOUSE)})
    assert get().json()["label"] == "14A Rock Street, Jersey City, NJ"
    assert [c[0] for c in calls] == [reverse_mod.PHOTON_REVERSE_URL]


def test_no_usable_label_is_200_with_null_and_cached(monkeypatch):
    monkeypatch.setenv(reverse_mod.LOCATIONIQ_KEY_ENV, KEY)
    calls = install(monkeypatch, {reverse_mod.LOCATIONIQ_REVERSE_URL: Resp(200, LIQ_NOTHING)})
    assert get().json()["label"] is None
    assert get().json()["label"] is None
    assert len(calls) == 1


def test_locationiq_404_unable_to_geocode_is_null_not_fallback(monkeypatch):
    monkeypatch.setenv(reverse_mod.LOCATIONIQ_KEY_ENV, KEY)
    calls = install(monkeypatch, {reverse_mod.LOCATIONIQ_REVERSE_URL: Resp(404, {})})
    resp = get()
    assert resp.status_code == 200 and resp.json()["label"] is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "outcome",
    [
        Resp(429, {}),
        Resp(401, {}),
        Resp(500, {}),
        httpx.ReadTimeout("t"),
        Resp(200, ValueError("bad")),
    ],
)
def test_locationiq_failures_fall_back_to_photon(monkeypatch, outcome):
    monkeypatch.setenv(reverse_mod.LOCATIONIQ_KEY_ENV, KEY)
    calls = install(
        monkeypatch,
        {
            reverse_mod.LOCATIONIQ_REVERSE_URL: outcome,
            reverse_mod.PHOTON_REVERSE_URL: Resp(200, PHOTON_HOUSE),
        },
    )
    resp = get()
    assert resp.status_code == 200
    assert resp.json()["label"] == "14A Rock Street, Jersey City, NJ"
    assert [c[0] for c in calls] == [
        reverse_mod.LOCATIONIQ_REVERSE_URL,
        reverse_mod.PHOTON_REVERSE_URL,
    ]


def test_all_providers_failing_is_503_and_not_cached(monkeypatch):
    monkeypatch.setenv(reverse_mod.LOCATIONIQ_KEY_ENV, KEY)
    calls = install(
        monkeypatch,
        {
            reverse_mod.LOCATIONIQ_REVERSE_URL: Resp(429, {}),
            reverse_mod.PHOTON_REVERSE_URL: httpx.ConnectTimeout("t"),
        },
    )
    resp = get()
    assert resp.status_code == 503
    assert resp.json()["code"] == "reverse_unavailable"
    assert "cache-control" not in resp.headers
    get()
    assert len(calls) == 4  # second request retried both providers


def test_key_never_appears_in_error_text(monkeypatch):
    monkeypatch.setenv(reverse_mod.LOCATIONIQ_KEY_ENV, KEY)
    url_error = httpx.ConnectError(f"failed for https://us1.locationiq.com/v1/reverse?key={KEY}")
    install(monkeypatch, {reverse_mod.LOCATIONIQ_REVERSE_URL: url_error})
    with pytest.raises(ReverseUnavailable) as caught:
        reverse_mod.fetch_locationiq(KEY, 40.7, -74.0)
    assert KEY not in str(caught.value) and "key=" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    install(monkeypatch, {reverse_mod.LOCATIONIQ_REVERSE_URL: Resp(401, {})})
    with pytest.raises(ReverseUnavailable) as caught:
        reverse_mod.fetch_locationiq(KEY, 40.7, -74.0)
    assert KEY not in str(caught.value)


def test_nearby_points_share_a_cache_entry(monkeypatch):
    calls = install(monkeypatch, {reverse_mod.PHOTON_REVERSE_URL: Resp(200, PHOTON_HOUSE)})
    get(40.727601, -74.061998)
    get(40.727649, -74.061951)
    assert len(calls) == 1
    get(40.7290, -74.0620)
    assert len(calls) == 2


def test_out_of_coverage_is_422_without_calling_providers(monkeypatch):
    calls = install(monkeypatch, {})
    resp = get(34.05, -118.24)
    assert resp.status_code == 422
    assert resp.json()["code"] == "out_of_coverage"
    assert calls == []


def test_bad_parameters_are_400():
    assert client.get("/v1/reverse", params={"lat": "x", "lon": 1}).status_code == 400
    assert client.get("/v1/reverse", params={"lat": 95, "lon": 1}).status_code == 400
    assert client.get("/v1/reverse").status_code == 400
