"""openrouteservice Matrix API client (free tier: 40 matrix calls/min,
2,000/day, 3,500 elements per call). Best-effort: every failure (no key,
timeout, quota, bad payload) returns None so callers keep their estimates.

The key comes from OPENROUTESERVICE_API_KEY and is never logged or returned.
"""

import os
import threading
from collections import OrderedDict

from common.lazy import lazy_module

httpx = lazy_module("httpx")

MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/{profile}"
PROFILES = {"drive": "driving-car", "walk": "foot-walking"}
TIMEOUT_S = 8.0
MAX_ELEMENTS = 3500
CACHE_SIZE = 20_000
COORD_DECIMALS = 4  # ~11 m

Point = tuple[float, float]  # (lat, lon)

_cache: OrderedDict[tuple, float] = OrderedDict()
_lock = threading.Lock()


def _key(profile: str, src: Point, dst: Point) -> tuple:
    return (
        profile,
        round(src[0], COORD_DECIMALS),
        round(src[1], COORD_DECIMALS),
        round(dst[0], COORD_DECIMALS),
        round(dst[1], COORD_DECIMALS),
    )


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _cache_get(k: tuple) -> float | None:
    with _lock:
        value = _cache.get(k)
        if value is not None:
            _cache.move_to_end(k)
        return value


def _cache_put(k: tuple, value: float) -> None:
    with _lock:
        _cache[k] = value
        _cache.move_to_end(k)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def api_key() -> str | None:
    key = os.environ.get("OPENROUTESERVICE_API_KEY", "").strip()
    return key or None


def matrix_minutes(
    mode: str, sources: list[Point], destinations: list[Point]
) -> list[list[float | None]] | None:
    """Travel minutes [source][destination] for `mode` ('walk' or 'drive'), or
    None when unavailable. Individual unroutable pairs are None. Makes at most
    one HTTP call, and none when every pair is cached; refuses (None) more than
    MAX_ELEMENTS elements."""
    profile = PROFILES.get(mode)
    if profile is None or not sources or not destinations:
        return None
    if len(sources) * len(destinations) > MAX_ELEMENTS:
        return None
    cached = [[_cache_get(_key(profile, s, d)) for d in destinations] for s in sources]
    if all(v is not None for row in cached for v in row):
        return [[v / 60.0 for v in row] for row in cached]  # type: ignore[operator]
    key = api_key()
    if key is None:
        return None
    locations = [[s[1], s[0]] for s in sources] + [[d[1], d[0]] for d in destinations]
    body = {
        "locations": locations,
        "sources": list(range(len(sources))),
        "destinations": list(range(len(sources), len(locations))),
        "metrics": ["duration"],
    }
    try:
        resp = httpx.post(
            MATRIX_URL.format(profile=profile),
            json=body,
            headers={"Authorization": key, "Content-Type": "application/json"},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        durations = resp.json()["durations"]
        if len(durations) != len(sources) or any(len(r) != len(destinations) for r in durations):
            return None
        out: list[list[float | None]] = []
        for i, row in enumerate(durations):
            out_row: list[float | None] = []
            for j, seconds in enumerate(row):
                if isinstance(seconds, (int, float)) and seconds >= 0:
                    _cache_put(_key(profile, sources[i], destinations[j]), float(seconds))
                    out_row.append(float(seconds) / 60.0)
                else:
                    out_row.append(None)
            out.append(out_row)
        return out
    except Exception:  # noqa: BLE001 - best-effort; never surface (or risk leaking) details
        return None
