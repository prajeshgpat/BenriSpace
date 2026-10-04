"""Address -> lat/lon geocoding for GET /score's `address` query param and
POST /triangulate's anchor `address` field.

**Phase 1 design call, not specified in PROJECT.md/PHASES.md** -- flagging
here (and in the implementation report) for review: this uses **OSM
Nominatim** (https://nominatim.openstreetmap.org/search), free and
keyless, same OSM family already used for POI ingestion (Overpass) and
road classification. No API key/account setup is needed to unblock this
endpoint today, unlike a paid geocoder (Google/Mapbox) which would add
another PHASES.md "Requirements from you" item. If Nominatim's rate limits
or match quality turn out to be a problem at real usage volume, swapping
the implementation of geocode_address() below is a one-file change --
nothing else in api/ imports Nominatim specifics directly.

Respecting Nominatim's usage policy
(https://operations.osmfoundation.org/policies/nominatim/):
- Identify the app via a descriptive User-Agent (required -- see
  USER_AGENT below).
- Max ~1 request/second, no bulk/batch geocoding. This module only ever
  geocodes one address per incoming API request (a single user action),
  never a loop over many addresses, so it stays well within policy.
"""

import os

import httpx

LOCATIONIQ_SEARCH_URL = "https://us1.locationiq.com/v1/search"
LOCATIONIQ_KEY_ENV = "LOCATIONIQ_API_KEY"
# West, south, east, north of the covered metro (biases ambiguous matches).
METRO_VIEWBOX = "-75.3,39.8,-71.7,42.1"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "BenriSpace/0.1 (Phase 1 MVP; contact: prajeshgpat@gmail.com)"


def _locationiq_geocode(address: str, timeout: float) -> tuple[float, float] | None:
    """LocationIQ forward search (the same key as autocomplete); None on any failure."""
    key = os.environ.get(LOCATIONIQ_KEY_ENV, "").strip()
    if not key:
        return None
    params = {
        "key": key, "q": address, "format": "json", "limit": 1,
        "countrycodes": "us", "viewbox": METRO_VIEWBOX,
    }  # fmt: skip
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(LOCATIONIQ_SEARCH_URL, params=params)
            resp.raise_for_status()
            results = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(results, list) or not results:
        return None
    try:
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def geocode_address(address: str, *, timeout: float = 5.0) -> tuple[float, float] | None:
    """Returns (lat, lon) for the top match -- LocationIQ first when its key is
    set (better street-address matching), then OSM Nominatim --  or None if the address
    doesn't resolve (or the request fails outright -- treated the same as
    "unresolvable" by callers, which return a 400 either way).

    Network call, not unit tested directly -- the pure logic downstream of
    it (geohash lookup, bbox fallback, response building, isochrone-circle
    math) is what's covered in tests/test_api.py.
    """
    point = _locationiq_geocode(address, timeout)
    if point is not None:
        return point
    params = {"q": address, "format": "jsonv2", "limit": 1}
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(NOMINATIM_URL, params=params, headers=headers)
            resp.raise_for_status()
            results = resp.json()
    except httpx.HTTPError:
        return None

    if not results:
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])
