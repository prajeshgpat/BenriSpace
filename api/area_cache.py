"""Tiny in-process TTL caches for GET /v1/area (AREAS_TABLE=areas_slim).

Three layers, all 5 minutes (a Lambda instance is warm for about that long; the data
changes on ingestion runs, not per request):
  * point -> area      keyed by the click rounded to ~1 m: the polygon lookup;
  * area -> scores     keyed by (area id, weights version, priorities): the mean of the
                       sample-point scores, which does not depend on where in the area
                       the user clicked;
  * geohash -> cell    the click cell's geo_entity + feature_store row.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

TTL_S = 300.0
MAX_ENTRIES = 2048


class TTLCache:
    def __init__(self, ttl_s: float = TTL_S, max_entries: int = MAX_ENTRIES, clock=time.monotonic):
        self.ttl_s, self.max_entries, self._clock = ttl_s, max_entries, clock
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            expires, value = hit
            if expires <= self._clock():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def put(self, key, value):
        with self._lock:
            self._data[key] = (self._clock() + self.ttl_s, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


POINT_AREA = TTLCache()
AREA_SCORES = TTLCache()
CELLS = TTLCache()


def point_key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 5), round(lon, 5))


def scores_key(area_id, weights_version: str, priorities: list[str] | None = None) -> tuple:
    return (area_id, weights_version, tuple(priorities or ()))


def clear_all() -> None:
    for c in (POINT_AREA, AREA_SCORES, CELLS):
        c.clear()
