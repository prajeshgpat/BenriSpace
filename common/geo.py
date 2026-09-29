"""Geo utilities shared by grid generation, ingestion, and the API.

Precision choice (geohash6, ~1.22km x 0.61km per cell) is documented in
common/grid.py alongside the bounding boxes it's applied to — see that
module for the row-count/cost rationale.
"""

import math

import pygeohash as pgh

EARTH_RADIUS_M = 6_371_000


def encode(lat: float, lon: float, precision: int = 6) -> str:
    return pgh.encode(lat, lon, precision=precision)


def decode(geohash: str) -> tuple[float, float]:
    lat, lon = pgh.decode(geohash)
    return float(lat), float(lon)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters. Used wherever a routing engine
    isn't available yet (e.g. airport drive-time fallback pre-Valhalla)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
