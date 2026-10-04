"""Named places (migration 0004): the writer ingestion jobs share and the
reader the API uses. Distances are computed in Python (haversine) after a
lat/lon box prefilter; user-facing distances go through common.units."""

import math
from collections.abc import Iterable
from dataclasses import dataclass

from common.geo import haversine_m
from common.units import M_PER_MI

# Every category the places table may hold (scoring category keys).
PLACE_CATEGORIES = (
    "grocery", "gym", "cafe", "restaurant", "bar", "gas_station",
    "convenience_store", "school", "transit", "whole_foods", "starbucks", "target",
    "shopping", "park",
)  # fmt: skip


@dataclass(frozen=True)
class Place:
    source: str
    source_id: str
    category: str
    name: str
    latitude: float
    longitude: float
    brand: str | None = None


def clean_name(name: str | None) -> str | None:
    """Trimmed name, or None when missing/blank (such POIs are not stored)."""
    if name is None:
        return None
    name = " ".join(str(name).split())
    return name or None


def replace_places(conn, source_prefix: str, places: Iterable[Place]) -> int:
    """Replaces every row whose source starts with `source_prefix` ('osm',
    'nces', 'gtfs') with `places`, in one transaction. Refuses an empty list
    (a failed fetch must not wipe the table). Returns the rows written."""
    rows = [
        (p.source, p.source_id, p.category, p.name, p.brand, p.latitude, p.longitude)
        for p in places
    ]
    if not rows:
        raise ValueError(f"no places for {source_prefix!r}; refusing to delete existing rows")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "delete from places where source = %s or source like %s",
                (source_prefix, source_prefix + ":%"),
            )
            cur.executemany(
                "insert into places (source, source_id, category, name, brand, latitude, longitude) "
                "values (%s, %s, %s, %s, %s, %s, %s) "
                "on conflict (source, source_id, category) do nothing",
                rows,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


def bbox_around(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lon, max_lon) covering radius_m around a point."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.01, math.cos(math.radians(lat))))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def compass(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> str:
    """8-point compass direction from one point to another ('NE')."""
    y = math.sin(math.radians(to_lon - from_lon)) * math.cos(math.radians(to_lat))
    x = math.cos(math.radians(from_lat)) * math.sin(math.radians(to_lat)) - math.sin(
        math.radians(from_lat)
    ) * math.cos(math.radians(to_lat)) * math.cos(math.radians(to_lon - from_lon))
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((bearing + 22.5) // 45) % 8]


def nearby_places(
    conn, lat: float, lon: float, category: str, radius_mi: float = 1.0, limit: int = 5
) -> list[dict]:
    """Closest named places of one category within radius_mi, nearest first.
    Each dict has name, brand, category, latitude, longitude, distance_m, direction."""
    radius_m = radius_mi * M_PER_MI
    min_lat, max_lat, min_lon, max_lon = bbox_around(lat, lon, radius_m)
    with conn.cursor() as cur:
        cur.execute(
            "select name, brand, category, latitude, longitude from places "
            "where category = %s and latitude between %s and %s and longitude between %s and %s",
            (category, min_lat, max_lat, min_lon, max_lon),
        )
        rows = list(cur)
    found = []
    for r in rows:
        d = haversine_m(lat, lon, r["latitude"], r["longitude"])
        if d <= radius_m:
            found.append(
                {
                    **r,
                    "distance_m": d,
                    "direction": compass(lat, lon, r["latitude"], r["longitude"]),
                }
            )
    found.sort(key=lambda p: p["distance_m"])
    return found[:limit]


def normalize_name(text: str | None) -> str:
    """Lower-cased, apostrophe-free, whitespace-collapsed text for brand
    matching ("Trader Joe's" -> "trader joes")."""
    if not text:
        return ""
    for quote in ("'", "’", "`"):
        text = text.replace(quote, "")
    return " ".join(text.lower().split())


def name_matches(query: str, name: str | None, brand: str | None) -> bool:
    """Case-insensitive substring match of `query` on a place's name or brand."""
    needle = normalize_name(query)
    return bool(needle) and (needle in normalize_name(name) or needle in normalize_name(brand))


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def places_by_brand_in_box(
    conn, query: str, min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[dict]:
    """Places whose name or brand contains `query` (case-insensitive, ignoring
    apostrophes) inside a lat/lon box. Dicts: name, brand, category, latitude,
    longitude. The box prefilter runs first so the text match sees few rows."""
    needle = normalize_name(query)
    if not needle:
        return []
    pattern = f"%{_like_escape(needle)}%"
    strip = "replace(replace(lower({col}), '''', ''), chr(8217), '')"
    with conn.cursor() as cur:
        cur.execute(
            "select name, brand, category, latitude, longitude from places "
            "where latitude between %s and %s and longitude between %s and %s "
            f"and ({strip.format(col='name')} like %s or {strip.format(col='brand')} like %s)",
            (min_lat, max_lat, min_lon, max_lon, pattern, pattern),
        )
        rows = [dict(r) for r in cur]
    return [r for r in rows if name_matches(query, r["name"], r["brand"])]


def places_by_category_in_box(
    conn, category: str, min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[dict]:
    """Every place of one category inside a lat/lon box."""
    with conn.cursor() as cur:
        cur.execute(
            "select name, brand, category, latitude, longitude from places "
            "where category = %s and latitude between %s and %s and longitude between %s and %s",
            (category, min_lat, max_lat, min_lon, max_lon),
        )
        return [dict(r) for r in cur]
