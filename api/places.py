"""GET /v1/places helpers: API factor keys -> places categories, and the
imperial response rows (no metric units leave the API)."""

from common.places import nearby_places
from common.units import format_distance, m_to_mi

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
