"""GET /v1/suggest. Photon is never called: fixtures under tests/fixtures are
real Photon responses captured 2026-10-02 (see the query in each name), and the
provider call is monkeypatched for route tests."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api import suggest as suggest_mod
from api.main import app
from api.suggest import (
    SuggestUnavailable,
    TTLCache,
    build_candidate,
    clean_suggestions,
    in_coverage,
    photon_params,
)
from common.coverage import BOUNDING_BOXES, union_bbox

FIXTURES = Path(__file__).parent / "fixtures"
client = TestClient(app)


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"photon_{name}.json").read_text())["features"]


def labels(name: str, q: str, limit: int = 10) -> list[str]:
    return [s.label for s in clean_suggestions(load(name), q, limit)]


def feature(lon, lat, **props) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


@pytest.fixture(autouse=True)
def fresh_cache():
    suggest_mod._cache.clear()


@pytest.fixture(autouse=True)
def no_locationiq_key(monkeypatch):
    # .env is loaded on import; tests must never reach a real provider.
    monkeypatch.delenv(suggest_mod.LOCATIONIQ_KEY_ENV, raising=False)


# --- coverage -----------------------------------------------------------------


def test_ingestion_grid_uses_the_shared_coverage_boxes():
    # Both the grid the data is built on and the area suggestions are limited
    # to must come from the same list.
    from ingestion import grid

    assert grid.BOUNDING_BOXES is BOUNDING_BOXES


def test_union_bbox_encloses_every_box():
    min_lon, min_lat, max_lon, max_lat = union_bbox()
    for _, lat0, lat1, lon0, lon1 in BOUNDING_BOXES:
        assert min_lat <= lat0 < lat1 <= max_lat
        assert min_lon <= lon0 < lon1 <= max_lon


def test_provider_request_is_restricted_and_biased_to_the_metro():
    params = photon_params("350 5th ave", 5)
    min_lon, min_lat, max_lon, max_lat = union_bbox()
    assert params["bbox"] == f"{min_lon},{min_lat},{max_lon},{max_lat}"
    assert in_coverage(params["lat"], params["lon"])
    assert params["limit"] >= 5


def test_features_outside_the_covered_area_are_dropped():
    boston = feature(-71.0636, 42.3554, name="Boston Common", type="house", osm_key="leisure")
    assert clean_suggestions([boston], "boston common", 5) == []


# --- label building and noise handling ----------------------------------------


def test_radio_station_pois_at_one_address_collapse_to_the_address():
    # Real Photon output: Empire State Building plus five radio-tower POIs, all at 350 5th Ave.
    assert labels("350_5th_ave", "350 5th ave") == ["350 5th Avenue, New York, NY"]


def test_identical_street_labels_collapse():
    # Ten "Broadway" segments across Manhattan.
    assert labels("broadway", "broadway") == ["Broadway, New York, NY"]


def test_places_pois_and_addresses_get_clean_labels_without_stuttering():
    result = labels("hoboken", "hoboken")
    assert result[0] == "Hoboken, NJ"  # town, no "Hoboken, Hoboken"
    assert "Hoboken Terminal, Hoboken, NJ" in result
    assert "500 Park Avenue, Hoboken, NJ" in result  # library: address beats POI name
    assert len(result) == len({label.casefold() for label in result})


def test_nameless_houses_are_labelled_by_address_and_state_is_abbreviated():
    result = labels("100_main_st", "100 main st")
    assert "100 Main Street, Yonkers, NY" in result
    assert "100 Main Street, Fort Lee, NJ" in result
    assert "100 Main Street, Eastchester, NY" in result  # the two same-address twins merge
    assert sum(label == "100 Main Street, Eastchester, NY" for label in result) == 1


def test_connecticut_and_pennsylvania_abbreviate_and_unknown_states_fall_back_to_full_name():
    ct = build_candidate(feature(-73.17, 41.19, housenumber="5", street="Main St", city="Stamford", state="Connecticut"))
    pa = build_candidate(feature(-75.1, 40.0, housenumber="5", street="Main St", city="Easton", state="Pennsylvania"))
    other = build_candidate(feature(-74.0, 40.7, housenumber="5", street="Main St", city="Somewhere", state="Delaware"))
    assert ct.label == "5 Main St, Stamford, CT"
    assert pa.label == "5 Main St, Easton, PA"
    assert other.label == "5 Main St, Somewhere, Delaware"


def test_district_is_used_when_there_is_no_city_and_state_may_be_missing():
    c = build_candidate(feature(-74.0, 40.7, housenumber="1", street="A St", district="Manhattan"))
    assert c.label == "1 A St, Manhattan"


def test_features_without_a_usable_label_are_dropped():
    bad = [
        feature(-74.0, 40.7, osm_key="place", type="house", city="New York"),  # no name, no address
        feature(-74.0, 40.7, housenumber="9", city="New York"),  # number but no street or name
        feature(-74.0, 40.7, name="   "),
        {"type": "Feature", "properties": {"name": "x"}},  # no geometry
        feature("a", "b", name="Bad coords"),
        "not a dict",
    ]
    assert clean_suggestions(bad, "whatever", 5) == []


def test_near_identical_coordinates_are_merged_even_when_labels_differ():
    a = feature(-73.98566, 40.74844, housenumber="350", street="5th Avenue", city="New York", state="New York")
    b = feature(-73.98567, 40.74845, name="Empire State Building", type="house", osm_key="office", city="New York", state="New York")
    assert [s.label for s in clean_suggestions([a, b], "350 5th", 5)] == ["350 5th Avenue, New York, NY"]


def test_digit_led_queries_list_addresses_before_streets_and_pois():
    street = feature(-73.99, 40.75, name="5th Avenue", type="street", osm_key="highway", city="New York", state="New York")
    poi = feature(-73.95, 40.70, name="Fifth Ave Deli", city="New York", state="New York")
    addr = feature(-73.90, 40.80, housenumber="5", street="5th Avenue", city="New York", state="New York")
    result = clean_suggestions([poi, street, addr], "5 fifth", 5)
    assert [s.label for s in result] == [
        "5 5th Avenue, New York, NY",
        "5th Avenue, New York, NY",
        "Fifth Ave Deli, New York, NY",
    ]
    # Text queries keep the provider's relevance order.
    text = clean_suggestions([poi, street, addr], "fifth", 5)
    assert next(s.label for s in text) == "Fifth Ave Deli, New York, NY"


def test_limit_is_respected():
    assert len(clean_suggestions(load("hoboken"), "hoboken", 2)) == 2


# --- cache ----------------------------------------------------------------------


def test_ttl_cache_expires_and_evicts_least_recently_used():
    now = [0.0]
    cache = TTLCache(max_entries=2, ttl_s=10, clock=lambda: now[0])
    cache.put(("a", 1), [])
    cache.put(("b", 1), [])
    assert cache.get(("a", 1)) == []  # refreshes a
    cache.put(("c", 1), [])  # evicts b
    assert cache.get(("b", 1)) is None
    assert cache.get(("a", 1)) == []
    now[0] = 10.0
    assert cache.get(("a", 1)) is None


# --- route ---------------------------------------------------------------------


def test_route_returns_cleaned_suggestions_with_cache_headers(monkeypatch):
    monkeypatch.setattr(suggest_mod, "fetch_photon_features", lambda q, limit: load("350_5th_ave"))
    resp = client.get("/v1/suggest", params={"q": "  350   5th ave "})
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=300"
    assert resp.json() == {
        "suggestions": [
            {"label": "350 5th Avenue, New York, NY", "latitude": 40.7484421, "longitude": -73.9856589}
        ]
    }


def test_repeat_queries_hit_the_cache_not_the_provider(monkeypatch):
    calls = []

    def fake(q, limit):
        calls.append((q, limit))
        return load("hoboken")

    monkeypatch.setattr(suggest_mod, "fetch_photon_features", fake)
    client.get("/v1/suggest", params={"q": "Hoboken"})
    client.get("/v1/suggest", params={"q": " hoboken "})
    client.get("/v1/suggest", params={"q": "hoboken", "limit": 3})
    assert len(calls) == 2  # same normalized q+limit shares an entry; a new limit does not


@pytest.mark.parametrize("params", [{"q": "ab"}, {"q": "  a  "}, {}, {"q": "abc", "limit": 0}, {"q": "abc", "limit": 11}])
def test_route_rejects_bad_input_with_invalid_request(params):
    resp = client.get("/v1/suggest", params=params)
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    assert "cache-control" not in resp.headers


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("down"),
        httpx.HTTPStatusError("502", request=httpx.Request("GET", "x"), response=httpx.Response(502)),
        json.JSONDecodeError("bad", "", 0),
    ],
)
def test_provider_failures_become_503_never_500_and_are_not_cached(monkeypatch, failure):
    class FakeClient:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, *a, **k):
            if isinstance(failure, httpx.HTTPStatusError):
                raise failure
            if isinstance(failure, json.JSONDecodeError):
                return httpx.Response(200, content=b"<html>", request=httpx.Request("GET", "x"))
            raise failure

    monkeypatch.setattr(suggest_mod.httpx, "Client", FakeClient)
    resp = client.get("/v1/suggest", params={"q": "broadway"})
    assert resp.status_code == 503
    assert resp.json()["code"] == "suggest_unavailable"
    assert "cache-control" not in resp.headers
    assert suggest_mod._cache.get(("broadway", 5)) is None


def test_malformed_provider_payload_is_unavailable(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, *a, **k):
            return httpx.Response(200, json={"features": "nope"}, request=httpx.Request("GET", "x"))

    monkeypatch.setattr(suggest_mod.httpx, "Client", FakeClient)
    with pytest.raises(SuggestUnavailable):
        suggest_mod.suggest("broadway", 5)


# --- LocationIQ ---------------------------------------------------------------

LIQ_RESULTS = [
    {
        "lat": "40.7484421",
        "lon": "-73.9856589",
        "class": "building",
        "type": "yes",
        "address": {
            "name": "Empire State Building",
            "house_number": "350",
            "road": "5th Avenue",
            "city": "New York",
            "state": "New York",
        },
    },
    {
        "lat": "40.7484311",
        "lon": "-73.9856903",
        "class": "man_made",
        "type": "tower",
        "address": {
            "name": "WNEW-FM (New York)",
            "house_number": "350",
            "road": "5th Avenue",
            "city": "New York",
            "state": "New York",
        },
    },
    {
        "lat": "40.7580",
        "lon": "-73.9855",
        "class": "highway",
        "type": "primary",
        "address": {"name": "Broadway", "road": "Broadway", "town": "Hoboken", "state": "New Jersey"},
    },
    {"lat": "bad", "lon": "x", "address": {}},
    "junk",
]


def test_locationiq_results_clean_like_photon_ones():
    features = suggest_mod.locationiq_to_features(LIQ_RESULTS)
    labels = [s.label for s in clean_suggestions(features, "350 5th", 5)]
    assert labels == ["350 5th Avenue, New York, NY", "Broadway, Hoboken, NJ"]


def test_locationiq_non_list_payload_is_unavailable():
    with pytest.raises(suggest_mod.SuggestUnavailable):
        suggest_mod.locationiq_to_features({"error": "Invalid key"})


def _fake_client(response=None, error=None, seen=None):
    class FakeClient:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, url, params=None, headers=None):
            if seen is not None:
                seen.append((url, params))
            if error is not None:
                raise error
            return response

    return FakeClient


def _resp(status, payload):
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://x"))


def test_locationiq_is_used_when_a_key_is_set_and_photon_is_not_called(monkeypatch):
    monkeypatch.setenv(suggest_mod.LOCATIONIQ_KEY_ENV, "secret-key-123")
    seen = []
    monkeypatch.setattr(suggest_mod.httpx, "Client", _fake_client(_resp(200, LIQ_RESULTS), seen=seen))
    monkeypatch.setattr(
        suggest_mod, "fetch_photon_features", lambda q, limit: pytest.fail("Photon called")
    )
    resp = client.get("/v1/suggest", params={"q": "350 5th"})
    assert resp.status_code == 200
    assert resp.json()["suggestions"][0]["label"] == "350 5th Avenue, New York, NY"
    url, params = seen[0]
    assert url == suggest_mod.LOCATIONIQ_URL
    assert params["key"] == "secret-key-123" and params["bounded"] == 1


def test_locationiq_no_matches_404_is_an_empty_result_not_a_fallback(monkeypatch):
    monkeypatch.setenv(suggest_mod.LOCATIONIQ_KEY_ENV, "k")
    monkeypatch.setattr(
        suggest_mod.httpx, "Client", _fake_client(_resp(404, {"error": "Unable to geocode"}))
    )
    monkeypatch.setattr(
        suggest_mod, "fetch_photon_features", lambda q, limit: pytest.fail("Photon called")
    )
    resp = client.get("/v1/suggest", params={"q": "zzzzzz"})
    assert resp.status_code == 200 and resp.json() == {"suggestions": []}


@pytest.mark.parametrize(
    "response,error",
    [
        (_resp(429, {"error": "Rate Limited"}), None),
        (_resp(401, {"error": "Invalid key"}), None),
        (_resp(200, {"error": "weird"}), None),
        (None, httpx.ReadTimeout("slow")),
        (None, httpx.ConnectError("down")),
    ],
)
def test_locationiq_failures_fall_back_to_photon(monkeypatch, response, error):
    monkeypatch.setenv(suggest_mod.LOCATIONIQ_KEY_ENV, "k")
    monkeypatch.setattr(suggest_mod.httpx, "Client", _fake_client(response, error))
    monkeypatch.setattr(suggest_mod, "fetch_photon_features", lambda q, limit: load("350_5th_ave"))
    resp = client.get("/v1/suggest", params={"q": "350 5th"})
    assert resp.status_code == 200
    assert resp.json()["suggestions"][0]["label"] == "350 5th Avenue, New York, NY"


def test_the_api_key_never_appears_in_provider_error_messages(monkeypatch):
    secret = "super-secret-key-999"
    url_error = httpx.ConnectError(f"failed for https://api.locationiq.com/v1/autocomplete?key={secret}")
    monkeypatch.setattr(suggest_mod.httpx, "Client", _fake_client(error=url_error))
    with pytest.raises(suggest_mod.SuggestUnavailable) as caught:
        suggest_mod.fetch_locationiq_features(secret, "q", 5)
    assert secret not in str(caught.value)
    status_error = httpx.HTTPStatusError(
        f"401 for url https://x?key={secret}",
        request=httpx.Request("GET", "https://x"),
        response=httpx.Response(401),
    )
    monkeypatch.setattr(suggest_mod.httpx, "Client", _fake_client(_resp(401, {})))
    with pytest.raises(suggest_mod.SuggestUnavailable) as caught:
        suggest_mod.fetch_locationiq_features(secret, "q", 5)
    assert secret not in str(caught.value) and secret not in repr(status_error.__cause__)
