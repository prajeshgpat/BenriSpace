import httpx
import pytest

from common.geo import haversine_m
from ingestion import airports as airports_mod
from ingestion.airports import (
    TIER1_AIRPORTS,
    Airport,
    HaversineFallbackRouter,
    ValhallaRouter,
    get_router,
    nearest_airport,
)


def test_tier1_airports_are_nyc_metro_only():
    # See module docstring: JFK/LGA/EWR are the tier-1 commercial airports
    # actually inside the v1 NYC-metro radius, not PROJECT.md's illustrative
    # Dulles/SFO examples.
    codes = {a.code for a in TIER1_AIRPORTS}
    assert codes == {"JFK", "LGA", "EWR"}
    for airport in TIER1_AIRPORTS:
        assert isinstance(airport.lat, float)
        assert isinstance(airport.lon, float)


def test_haversine_fallback_matches_assumed_speed_math():
    router = HaversineFallbackRouter()
    origin = (40.7128, -74.0060)  # lower Manhattan
    dest = (40.6413, -73.7781)  # JFK
    minutes = router.drive_time_minutes(*origin, *dest)

    distance_km = haversine_m(*origin, *dest) / 1000.0
    expected_minutes = distance_km / HaversineFallbackRouter.ASSUMED_AVG_SPEED_KMH * 60.0

    assert minutes == pytest.approx(expected_minutes)
    assert minutes > 0


def test_haversine_fallback_zero_distance_is_zero_minutes():
    router = HaversineFallbackRouter()
    assert router.drive_time_minutes(40.75, -73.98, 40.75, -73.98) == 0.0


def test_nearest_airport_picks_closest_by_drive_time():
    router = HaversineFallbackRouter()
    lga = next(a for a in TIER1_AIRPORTS if a.code == "LGA")
    airport, minutes = nearest_airport(lga.lat + 0.002, lga.lon + 0.002, router)
    assert airport.code == "LGA"
    assert minutes < 5  # a point ~a few hundred meters from LGA


def test_nearest_airport_uses_custom_airport_list():
    router = HaversineFallbackRouter()
    custom = [Airport("A", "Alpha", 0.0, 0.0), Airport("B", "Beta", 5.0, 5.0)]
    airport, _minutes = nearest_airport(0.01, 0.01, router, airports=custom)
    assert airport.code == "A"


def test_get_router_picks_valhalla_when_url_set(monkeypatch):
    monkeypatch.setattr(airports_mod.config, "VALHALLA_URL", "http://valhalla.local:8002")
    router = get_router()
    assert isinstance(router, ValhallaRouter)
    assert router.base_url == "http://valhalla.local:8002"


def test_get_router_falls_back_when_url_unset(monkeypatch):
    monkeypatch.setattr(airports_mod.config, "VALHALLA_URL", None)
    router = get_router()
    assert isinstance(router, HaversineFallbackRouter)


def test_valhalla_router_sends_documented_request_shape(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(
            200,
            json={"trip": {"summary": {"time": 1500, "length": 25.0}}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    router = ValhallaRouter("http://valhalla.local:8002")
    minutes = router.drive_time_minutes(40.0, -73.0, 40.5, -73.5)

    assert captured["url"] == "http://valhalla.local:8002/route"
    assert captured["json"] == {
        "locations": [{"lat": 40.0, "lon": -73.0}, {"lat": 40.5, "lon": -73.5}],
        "costing": "auto",
        "units": "kilometers",
    }
    assert minutes == pytest.approx(25.0)  # 1500s / 60


def test_valhalla_router_strips_trailing_slash_from_base_url():
    router = ValhallaRouter("http://valhalla.local:8002/")
    assert router.base_url == "http://valhalla.local:8002"
