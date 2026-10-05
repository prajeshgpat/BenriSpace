"""GET /v1/places helpers: API factor keys -> places categories, and the
imperial response rows (no metric units leave the API)."""

from common.geo import haversine_m
from common.places import bbox_around, nearby_places
from common.units import M_PER_MI, format_distance, m_to_mi

FACTOR_CATEGORIES: dict[str, tuple[str, ...]] = {
    "grocery": ("grocery",),
    "gym": ("gym",),
    "cafe": ("cafe",),
    "restaurant": ("restaurant",),
    "bar": ("bar",),
    "shopping": ("shopping",),
    "recreation": ("park",),
    "gasConvenience": ("gas_station", "convenience_store"),
    "transit": ("transit",),
    "school": ("school",),
    # Legacy keys keep their exact old meaning (brand rows / one kind of store).
    "gasStation": ("gas_station",),
    "convenienceStore": ("convenience_store",),
    "premiumRetail": ("whole_foods", "starbucks", "target"),
}


def places_for_factor(
    conn, lat: float, lon: float, factor: str, radius_mi: float, limit: int
) -> list[dict]:
    """Nearest places for a factor (merged nearest-first across categories),
    as dicts ready for the PlaceOut model. Raises KeyError for unknown factors."""
    found: list[dict] = []
    for category in FACTOR_CATEGORIES[factor]:
        found.extend(nearby_places(conn, lat, lon, category, radius_mi, limit))
    found.sort(key=lambda p: p["distance_m"])
    return [
        {
            "name": p["name"],
            "brand": p["brand"],
            "category": p["category"],
            "distance_mi": round(m_to_mi(p["distance_m"]), 2),
            "distance_label": format_distance(p["distance_m"]),
            "direction": p["direction"],
            "latitude": p["latitude"],
            "longitude": p["longitude"],
        }
        for p in found[:limit]
    ]


# Factors the map-pin endpoint serves: the place-based ones (no legacy keys).
PIN_FACTORS: tuple[str, ...] = (
    "grocery", "gym", "cafe", "restaurant", "bar", "shopping", "recreation",
    "gasConvenience", "transit", "school",
)  # fmt: skip


def pin_factors(requested: list[str] | None) -> list[str]:
    """Requested factor keys limited to PIN_FACTORS (unknown ones dropped,
    order and duplicates normalised); empty/None means every pin factor."""
    if not requested:
        return list(PIN_FACTORS)
    wanted = {f for f in requested if f in PIN_FACTORS}
    return [f for f in PIN_FACTORS if f in wanted]


def places_around(
    conn, lat: float, lon: float, factors: list[str], radius_mi: float, per_factor: int
) -> list[dict]:
    """Places behind several factors around a point in ONE query: a category
    filter plus lat/lon box, then haversine trimming to the nearest
    `per_factor` per factor. Rows are dicts for the PlaceAroundOut model."""
    category_factor = {c: f for f in factors for c in FACTOR_CATEGORIES[f]}
    if not category_factor:
        return []
    radius_m = radius_mi * M_PER_MI
    min_lat, max_lat, min_lon, max_lon = bbox_around(lat, lon, radius_m)
    with conn.cursor() as cur:
        cur.execute(
            "select name, brand, category, latitude, longitude from places "
            "where category = any(%s) and latitude between %s and %s "
            "and longitude between %s and %s",
            (list(category_factor), min_lat, max_lat, min_lon, max_lon),
        )
        rows = list(cur)
    by_factor: dict[str, list[tuple[float, dict]]] = {f: [] for f in factors}
    for r in rows:
        d = haversine_m(lat, lon, r["latitude"], r["longitude"])
        if d <= radius_m and r["category"] in category_factor:
            by_factor[category_factor[r["category"]]].append((d, r))
    out: list[dict] = []
    for factor in factors:
        nearest = sorted(by_factor[factor], key=lambda item: item[0])[:per_factor]
        for d, r in nearest:
            out.append(
                {
                    "factor": factor,
                    "name": r["name"],
                    "brand": r["brand"],
                    "category": r["category"],
                    "latitude": r["latitude"],
                    "longitude": r["longitude"],
                    "distance_mi": round(m_to_mi(d), 2),
                }
            )
    return out
