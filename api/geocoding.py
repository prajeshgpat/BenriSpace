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

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "BenriSpace/0.1 (Phase 1 MVP; contact: prajeshgpat@gmail.com)"


def geocode_address(address: str, *, timeout: float = 5.0) -> tuple[float, float] | None:
    """Returns (lat, lon) for Nominatim's top match, or None if the address
    doesn't resolve (or the request fails outright -- treated the same as
    "unresolvable" by callers, which return a 400 either way).

    Network call, not unit tested directly -- the pure logic downstream of
    it (geohash lookup, bbox fallback, response building, isochrone-circle
    math) is what's covered in tests/test_api.py.
    """
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
