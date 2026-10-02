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

import sys
import time

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
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
