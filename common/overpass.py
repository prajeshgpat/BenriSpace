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


def make_client() -> httpx.Client:
    """A client pre-configured with the required User-Agent, for callers
    that reuse one client across many queries (e.g. roads.py)."""
    return httpx.Client(headers=HTTP_HEADERS)


def post_overpass_query(query: str, timeout: float, client: httpx.Client | None = None) -> dict:
    """POSTs a query to Overpass, retrying on 429 with backoff. Does NOT
    retry on timeouts or other errors -- callers with their own
    size/complexity-reduction fallback (e.g. roads.py's bbox quadrant
    splitting) handle those themselves; this only owns the rate-limit
    concern, which is orthogonal."""
    post = client.post if client is not None else httpx.post
    extra = {} if client is not None else {"headers": HTTP_HEADERS}

    for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 2):
        resp = post(OVERPASS_URL, data={"data": query}, timeout=timeout, **extra)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        if attempt > MAX_RATE_LIMIT_RETRIES:
            resp.raise_for_status()  # retries exhausted -- raise the 429
        retry_after = float(resp.headers.get("Retry-After", DEFAULT_RETRY_AFTER_S))
        print(
            f"[overpass] 429 rate limited, waiting {retry_after:.0f}s "
            f"(attempt {attempt}/{MAX_RATE_LIMIT_RETRIES})",
            file=sys.stderr,
        )
        time.sleep(retry_after)

    raise RuntimeError("unreachable")  # loop always returns or raises above
