"""GET /v1/reverse: coordinates -> a short readable address.

Primary provider is LocationIQ when LOCATIONIQ_API_KEY is set; Photon's
keyless /reverse is the fallback. Both are normalised to one small property
dict so a single label builder serves them, and the label vocabulary
(abbreviated states, "number street, locality, ST") matches /v1/suggest.
"""

import logging
import math
import os

import common.config  # noqa: F401  (loads .env so LOCATIONIQ_API_KEY works in local runs)
from api.geocoding import USER_AGENT
from api.suggest import (
    LOCALITY_FIELDS,
    LOCATIONIQ_KEY_ENV,
    STATE_ABBREVIATIONS,
    SuggestUnavailable,
    TTLCache,
    _clean,
    in_coverage,
)
from common.lazy import lazy_module

httpx = lazy_module("httpx")

LOCATIONIQ_REVERSE_URL = "https://us1.locationiq.com/v1/reverse"
LOCATIONIQ_TIMEOUT_S = 3.0
PHOTON_REVERSE_URL = "https://photon.komoot.io/reverse"
PHOTON_TIMEOUT_S = 8.0
ZOOM = 18  # building level
NEIGHBOURHOOD_FIELDS = ("neighbourhood", "suburb", "quarter", "hamlet")

logger = logging.getLogger(__name__)


class ReverseUnavailable(SuggestUnavailable):
    """Every reverse-geocoding provider failed."""


def cache_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 4), round(lon, 4))


def build_label(props: dict) -> str | None:
    """props: housenumber, street, area (neighbourhood), locality, state."""
    housenumber = _clean(props.get("housenumber"))
    street = _clean(props.get("street"))
    area = _clean(props.get("area"))
    locality = _clean(props.get("locality"))
    if street:
        first = f"{housenumber} {street}" if housenumber else street
    elif area:
        first = area
    else:
        return None

    parts = [first]
    if locality and locality.casefold() != first.casefold():
        parts.append(locality)
    state = _clean(props.get("state"))
    if state:
        abbreviated = STATE_ABBREVIATIONS.get(state, state)
        if abbreviated.casefold() != parts[-1].casefold():
            parts.append(abbreviated)
    return ", ".join(parts)


def locationiq_props(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ReverseUnavailable("unexpected LocationIQ payload")
    address = payload.get("address")
    if not isinstance(address, dict):
        return {}
    return {
        "housenumber": address.get("house_number"),
        "street": address.get("road"),
        "area": next((address[f] for f in NEIGHBOURHOOD_FIELDS if address.get(f)), None),
        "locality": next((address[f] for f in LOCALITY_FIELDS if address.get(f)), None),
        "state": address.get("state"),
    }


def photon_props(payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ReverseUnavailable("unexpected Photon payload")
    for feature in payload["features"]:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if isinstance(props, dict):
            return {
                "housenumber": props.get("housenumber"),
                "street": props.get("street"),
                "area": props.get("locality") or props.get("district") or props.get("name"),
                "locality": props.get("city") or props.get("district") or props.get("locality"),
                "state": props.get("state"),
            }
    return {}


def fetch_locationiq(api_key: str, lat: float, lon: float) -> dict:
    params = {
        "key": api_key,
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
        "zoom": ZOOM,
        "normalizecity": 1,
        "accept-language": "en",
    }
    # Never put the exception text in the message: httpx includes the request
    # URL, and the key is in its query string.
    try:
        with httpx.Client(timeout=LOCATIONIQ_TIMEOUT_S) as client:
            resp = client.get(
                LOCATIONIQ_REVERSE_URL, params=params, headers={"User-Agent": USER_AGENT}
            )
        if resp.status_code == 404:  # LocationIQ's "Unable to geocode"
            return {}
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPStatusError as exc:
        raise ReverseUnavailable(f"LocationIQ HTTP {exc.response.status_code}") from None
    except (httpx.HTTPError, ValueError) as exc:
        raise ReverseUnavailable(f"LocationIQ {type(exc).__name__}") from None
    return locationiq_props(payload)


def fetch_photon(lat: float, lon: float) -> dict:
    try:
        with httpx.Client(timeout=PHOTON_TIMEOUT_S) as client:
            resp = client.get(
                PHOTON_REVERSE_URL,
                params={"lat": lat, "lon": lon, "lang": "en", "limit": 1},
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        raise ReverseUnavailable(f"Photon HTTP {exc.response.status_code}") from None
    except (httpx.HTTPError, ValueError) as exc:
        raise ReverseUnavailable(f"Photon {type(exc).__name__}") from None
    return photon_props(payload)


def fetch_props(lat: float, lon: float) -> dict:
    api_key = os.environ.get(LOCATIONIQ_KEY_ENV, "").strip()
    if api_key:
        try:
            return fetch_locationiq(api_key, lat, lon)
        except ReverseUnavailable as exc:
            logger.warning("reverse: %s; falling back to Photon", exc)
    return fetch_photon(lat, lon)


_cache = TTLCache()
_MISSING = ""  # cached "no usable label" (a successful, empty answer)


def reverse(lat: float, lon: float) -> str | None:
    """Label for the point, or None when the providers know of nothing usable.
    Raises ReverseUnavailable when providers fail; failures are never cached."""
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    key = cache_key(lat, lon)
    cached = _cache.get(key)
    if cached is not None:
        return cached or None
    label = build_label(fetch_props(key[0], key[1]))
    _cache.put(key, label or _MISSING)  # type: ignore[arg-type]
    return label


__all__ = ["ReverseUnavailable", "build_label", "in_coverage", "reverse"]
