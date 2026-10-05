"""Shared Overpass API client for every OSM-based ingestion job
(osm_poi.py, roads.py, trails.py). Two real bugs found live (2026-09-29)
against the actual public Overpass instance, not hypothetical:

1. Overpass 406s httpx's default generic User-Agent -- an identifying one
   is required (matches api/geocoding.py's existing handling of the same
   requirement for Nominatim, OSM's sister service).
2. Overpass 429s (rate limited) after several large successive queries.
   The wrong response is to retry immediately, or worse, split into more
   requests and fire them right away (a real bug this replaces: a
   quadrant-splitting bbox retry strategy meant for timeouts was also
   catching 429s and immediately sending 4 requests instead of backing
   off). This module retries a 429 with the server's Retry-After (or a
   default backoff) BEFORE any caller-specific fallback logic (like
   roads.py's bbox splitting, which is about query complexity/timeout,
   a different problem) ever sees it.
"""

import os
import sys
import time
from collections.abc import Callable

import httpx

OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
HTTP_HEADERS = {"User-Agent": "BenriSpace-ingestion/1.0 (contact: prajeshgpat@gmail.com)"}

DEFAULT_RETRY_AFTER_S = 60.0
MAX_RATE_LIMIT_RETRIES = 3

# A gateway error (502/503/504) that comes back FAST means the public server
# is busy right now -- worth waiting and retrying. One that comes back slowly
# means the query itself was too big for the server's time limit, and
# retrying the same query just burns minutes; callers with a size-reduction
# fallback (roads.py / trails.py bbox splitting) should see that error.
BUSY_STATUSES = (502, 503, 504)
BUSY_MAX_ELAPSED_S = 30.0
BUSY_BACKOFF_S = 30.0
MAX_BUSY_RETRIES = 3


def make_client() -> httpx.Client:
    """A client pre-configured with the required User-Agent, for callers
    that reuse one client across many queries (e.g. roads.py)."""
    return httpx.Client(headers=HTTP_HEADERS)


def post_overpass_query(query: str, timeout: float, client: httpx.Client | None = None) -> dict:
    """POSTs a query to Overpass and returns the parsed JSON.

    Retries (with backoff) two transient conditions: 429 rate limiting
    (honouring Retry-After), and a *fast* 502/503/504 meaning the server is
    busy. Everything else -- timeouts, slow gateway errors, 4xx -- raises
    immediately so callers with their own size-reduction fallback (e.g.
    roads.py's bbox quadrant splitting) can handle it; that is a different
    problem from load."""
    post = client.post if client is not None else httpx.post
    extra = {} if client is not None else {"headers": HTTP_HEADERS}

    rate_limit_retries = 0
    busy_retries = 0
    while True:
        started = time.monotonic()
        resp = post(OVERPASS_URL, data={"data": query}, timeout=timeout, **extra)
        elapsed = time.monotonic() - started

        if resp.status_code == 429 and rate_limit_retries < MAX_RATE_LIMIT_RETRIES:
            rate_limit_retries += 1
            wait = float(resp.headers.get("Retry-After", DEFAULT_RETRY_AFTER_S))
            print(
                f"[overpass] 429 rate limited, waiting {wait:.0f}s "
                f"(retry {rate_limit_retries}/{MAX_RATE_LIMIT_RETRIES})",
                file=sys.stderr,
            )
            time.sleep(wait)
            continue

        if (
            resp.status_code in BUSY_STATUSES
            and elapsed < BUSY_MAX_ELAPSED_S
            and busy_retries < MAX_BUSY_RETRIES
        ):
            busy_retries += 1
            wait = BUSY_BACKOFF_S * busy_retries
            print(
                f"[overpass] {resp.status_code} after {elapsed:.0f}s (server busy), "
                f"waiting {wait:.0f}s (retry {busy_retries}/{MAX_BUSY_RETRIES})",
                file=sys.stderr,
            )
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.json()


def split_bbox(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[tuple[float, float, float, float]]:
    """Four quadrants as (min_lat, max_lat, min_lon, max_lon) tuples."""
    mid_lat = (min_lat + max_lat) / 2.0
    mid_lon = (min_lon + max_lon) / 2.0
    return [
        (min_lat, mid_lat, min_lon, mid_lon),
        (min_lat, mid_lat, mid_lon, max_lon),
        (mid_lat, max_lat, min_lon, mid_lon),
        (mid_lat, max_lat, mid_lon, max_lon),
    ]


def merge_overpass_elements(responses: list[dict]) -> dict:
    """Merges several Overpass JSON responses into one, de-duplicating
    elements by (type, id). Ways/relations that straddle a quadrant edge
    are returned by both quadrants' bbox filters; without de-duplication
    they would be double-counted."""
    seen: set[tuple[str | None, int | None]] = set()
    elements: list[dict] = []
    for data in responses:
        for el in data.get("elements", []):
            key = (el.get("type"), el.get("id"))
            if key[1] is not None:
                if key in seen:
                    continue
                seen.add(key)
            elements.append(el)
    return {"elements": elements}


def fetch_with_quadrant_split(
    fetch: Callable[[float, float, float, float], dict],
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    max_depth: int = 2,
    pause_s: float = 1.0,
    _depth: int = 0,
) -> dict:
    """Calls fetch(min_lat, max_lat, min_lon, max_lon) -> Overpass JSON. On a
    timeout / transport / HTTP error (429 and fast-busy are already retried
    inside post_overpass_query, so what arrives here is a size problem),
    splits the bbox into 4 quadrants and retries each, up to max_depth
    levels (4**max_depth tiles worst case), merging de-duplicated results."""
    try:
        return fetch(min_lat, max_lat, min_lon, max_lon)
    except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
        if _depth >= max_depth:
            raise
        print(
            f"[overpass] bbox ({min_lat},{min_lon},{max_lat},{max_lon}) failed at depth "
            f"{_depth} ({exc}); splitting into quadrants",
            file=sys.stderr,
        )
        parts = []
        for sub in split_bbox(min_lat, max_lat, min_lon, max_lon):
            time.sleep(pause_s)
            parts.append(fetch_with_quadrant_split(fetch, *sub, max_depth, pause_s, _depth + 1))
        return merge_overpass_elements(parts)
