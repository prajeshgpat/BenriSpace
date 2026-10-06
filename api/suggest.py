"""GET /v1/suggest: address autocomplete.

Primary provider is LocationIQ when LOCATIONIQ_API_KEY is set (fast, keyed,
autocomplete permitted); Photon (https://photon.komoot.io) is the keyless
fallback. Not Nominatim: its usage policy forbids autocomplete. Both are
OpenStreetMap-based and are normalised to the same feature shape so one
cleanup pipeline serves both. Results are cached in-process and one keystroke
never fans out into more than one provider call.
"""

import logging
import math
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import common.config  # noqa: F401  (loads .env so LOCATIONIQ_API_KEY works in local runs)
from api.geocoding import USER_AGENT
from api.schemas import Suggestion
from common.coverage import metro_center, union_bbox
from common.geo import haversine_m
from common.lazy import lazy_module

httpx = lazy_module("httpx")

PHOTON_URL = "https://photon.komoot.io/api/"
PROVIDER_TIMEOUT_S = 8.0
LOCATIONIQ_URL = "https://api.locationiq.com/v1/autocomplete"
LOCATIONIQ_TIMEOUT_S = 3.0
LOCATIONIQ_KEY_ENV = "LOCATIONIQ_API_KEY"
LOCATIONIQ_MAX_LIMIT = 20
LOCALITY_FIELDS = ("city", "town", "village", "hamlet", "suburb")

logger = logging.getLogger(__name__)
MIN_QUERY_LENGTH = 3

# Photon returns many near-duplicates (e.g. six POIs at one street address), so
# ask for more than we will show.
OVERFETCH_FACTOR = 3
OVERFETCH_MIN = 10
OVERFETCH_MAX = 20

NEAR_DUPLICATE_M = 25.0

STATE_ABBREVIATIONS = {
    "New York": "NY",
    "New Jersey": "NJ",
    "Connecticut": "CT",
    "Pennsylvania": "PA",
}

CACHE_TTL_S = 600.0
CACHE_MAX_ENTRIES = 300


class SuggestUnavailable(Exception):
    """The geocoding provider failed in any way (timeout, 5xx, bad payload)."""


def normalize_query(q: str) -> str:
    return " ".join(q.split())


@dataclass(frozen=True)
class _Candidate:
    label: str
    latitude: float
    longitude: float
    kind: str  # address | street | place | poi


_KIND_ORDER = {"address": 0, "street": 1, "place": 2, "poi": 3}


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _classify(props: dict) -> tuple[str, str] | None:
    """Returns (kind, first label line) or None when the feature has no
    usable name or address."""
    name = _clean(props.get("name"))
    housenumber = _clean(props.get("housenumber"))
    street = _clean(props.get("street"))

    if housenumber and street:
        # The address wins over a POI name at it: "WNEW-FM (New York)" is not
        # a place a user is looking for, "350 5th Avenue" is.
        return "address", f"{housenumber} {street}"
    if props.get("type") == "street" or props.get("osm_key") == "highway":
        return ("street", name) if name else None
    if props.get("osm_key") == "place" and props.get("type") != "house":
        return ("place", name) if name else None
    if name:
        return "poi", name
    return None


def build_candidate(feature: dict) -> _Candidate | None:
    props = feature.get("properties")
    coords = (feature.get("geometry") or {}).get("coordinates")
    if not isinstance(props, dict) or not isinstance(coords, list) or len(coords) < 2:
        return None
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None

    classified = _classify(props)
    if classified is None:
        return None
    kind, first_line = classified

    parts = [first_line]
    locality = _clean(props.get("city")) or _clean(props.get("district"))
    if locality is None and kind == "address":
        locality = _clean(props.get("locality"))
    if locality and locality.casefold() != first_line.casefold():
        parts.append(locality)
    state = _clean(props.get("state"))
    if state:
        abbreviated = STATE_ABBREVIATIONS.get(state, state)
        if abbreviated.casefold() != parts[-1].casefold():
            parts.append(abbreviated)

    return _Candidate(", ".join(parts), lat, lon, kind)


def in_coverage(lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = union_bbox()
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def clean_suggestions(features: list, q: str, limit: int) -> list[Suggestion]:
    """Photon features -> at most `limit` unique, in-coverage suggestions.

    Order is Photon's (relevance plus location bias), except that a query
    starting with a digit looks like a street address, so addresses are
    listed before streets, places and bare POIs.
    """
    candidates: list[_Candidate] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        candidate = build_candidate(feature)
        if candidate and in_coverage(candidate.latitude, candidate.longitude):
            candidates.append(candidate)

    if q[:1].isdigit():
        candidates.sort(key=lambda c: _KIND_ORDER[c.kind])  # stable

    kept: list[_Candidate] = []
    seen_labels: set[str] = set()
    for candidate in candidates:
        key = candidate.label.casefold()
        if key in seen_labels:
            continue
        if any(
            haversine_m(candidate.latitude, candidate.longitude, k.latitude, k.longitude)
            < NEAR_DUPLICATE_M
            for k in kept
        ):
            continue
        seen_labels.add(key)
        kept.append(candidate)
        if len(kept) == limit:
            break

    return [Suggestion(label=c.label, latitude=c.latitude, longitude=c.longitude) for c in kept]


def photon_params(q: str, limit: int) -> dict[str, str | int | float]:
    min_lon, min_lat, max_lon, max_lat = union_bbox()
    center_lat, center_lon = metro_center()
    return {
        "q": q,
        "limit": min(max(limit * OVERFETCH_FACTOR, OVERFETCH_MIN), OVERFETCH_MAX),
        "lat": center_lat,
        "lon": center_lon,
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "lang": "en",
    }


def fetch_photon_features(q: str, limit: int) -> list:
    try:
        with httpx.Client(timeout=PROVIDER_TIMEOUT_S) as client:
            resp = client.get(
                PHOTON_URL,
                params=photon_params(q, limit),
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            features = resp.json()["features"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise SuggestUnavailable(str(exc)) from exc
    if not isinstance(features, list):
        raise SuggestUnavailable("unexpected Photon payload")
    return features


def locationiq_to_features(results: object) -> list[dict]:
    """LocationIQ autocomplete results -> Photon-shaped GeoJSON features, so
    clean_suggestions handles both providers."""
    if not isinstance(results, list):
        raise SuggestUnavailable("unexpected LocationIQ payload")
    features = []
    for item in results:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        address = address if isinstance(address, dict) else {}
        try:
            lon, lat = float(item["lon"]), float(item["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        locality = next((address[f] for f in LOCALITY_FIELDS if address.get(f)), None)
        features.append(
            {
                "geometry": {"coordinates": [lon, lat]},
                "properties": {
                    "name": address.get("name"),
                    "housenumber": address.get("house_number"),
                    "street": address.get("road"),
                    "city": locality,
                    "state": address.get("state"),
                    "osm_key": item.get("class"),
                    "type": item.get("type"),
                },
            }
        )
    return features


def fetch_locationiq_features(api_key: str, q: str, limit: int) -> list[dict]:
    min_lon, min_lat, max_lon, max_lat = union_bbox()
    params = {
        "key": api_key,
        "q": q,
        "limit": min(max(limit * OVERFETCH_FACTOR, OVERFETCH_MIN), LOCATIONIQ_MAX_LIMIT),
        "viewbox": f"{min_lon},{max_lat},{max_lon},{min_lat}",
        "bounded": 1,
        "countrycodes": "us",
        "dedupe": 1,
        "normalizecity": 1,
    }
    # Never put the exception text in the message: httpx includes the request
    # URL, and the key is in its query string.
    try:
        with httpx.Client(timeout=LOCATIONIQ_TIMEOUT_S) as client:
            resp = client.get(LOCATIONIQ_URL, params=params, headers={"User-Agent": USER_AGENT})
        if resp.status_code == 404:  # LocationIQ's "no matches"
            return []
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPStatusError as exc:
        raise SuggestUnavailable(f"LocationIQ HTTP {exc.response.status_code}") from None
    except (httpx.HTTPError, ValueError) as exc:
        raise SuggestUnavailable(f"LocationIQ {type(exc).__name__}") from None
    return locationiq_to_features(payload)


def _photon_or_nothing(q: str, limit: int) -> list:
    try:
        return fetch_photon_features(q, limit)
    except SuggestUnavailable as exc:
        logger.warning("suggest: %s (LocationIQ results only)", exc)
        return []


def fetch_features(q: str, limit: int) -> list:
    """LocationIQ and Photon asked in parallel, LocationIQ's results first. LocationIQ
    autocomplete misses many house numbers and street-plus-town queries ("100 Washington St
    Hoboken", "Main St Montclair") that Photon finds, so Photon fills the list; then
    clean_suggestions de-duplicates, keeps the covered area and, for a query that starts
    with a number, lists exact addresses first. Without a key, or if LocationIQ fails,
    Photon alone."""
    api_key = os.environ.get(LOCATIONIQ_KEY_ENV, "").strip()
    if not api_key:
        return fetch_photon_features(q, limit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        photon = pool.submit(_photon_or_nothing, q, limit)
        try:
            primary = fetch_locationiq_features(api_key, q, limit)
        except SuggestUnavailable as exc:
            logger.warning("suggest: %s; falling back to Photon", exc)
            photon.cancel()
            return fetch_photon_features(q, limit)
        return primary + photon.result()


class TTLCache:
    """Small thread-safe LRU with per-entry expiry (handlers run in a thread
    pool, and a warm Lambda instance serves many requests)."""

    def __init__(
        self,
        max_entries: int = CACHE_MAX_ENTRIES,
        ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._max = max_entries
        self._ttl = ttl_s
        self._clock = clock
        self._data: OrderedDict[tuple, tuple[float, list[Suggestion]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> list[Suggestion] | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if self._clock() >= entry[0]:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return entry[1]

    def put(self, key: tuple, value: list[Suggestion]) -> None:
        with self._lock:
            self._data[key] = (self._clock() + self._ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_cache = TTLCache()


def suggest(q: str, limit: int) -> list[Suggestion]:
    """Raises SuggestUnavailable when the provider fails; failures are never
    cached."""
    q = normalize_query(q)
    key = (q.casefold(), limit)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    result = clean_suggestions(fetch_features(q, limit), q, limit)
    _cache.put(key, result)
    return result
