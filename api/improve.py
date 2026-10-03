"""GET /v1/improve: deterministic "what could improve this score" suggestions.
Pure functions over already-fetched rows; distances are imperial on the wire."""

from api.places import places_for_factor
from api.priorities import TOGGLEABLE_FACTORS, Priorities
from common.geo import haversine_m
from common.places import bbox_around, compass
from common.units import M_PER_MI, format_distance, m_to_mi

WEAK_BELOW = 75
BETTER_AREA_MIN_GAIN = 10
BEST_NEARBY_MIN_GAIN = 3
MAX_PLACES = 3

# Positive, place-based factors only: wire key -> (score column, label).
IMPROVABLE: dict[str, tuple[str, str]] = {
    "grocery": ("grocery_score", "Grocery"),
    "gym": ("gym_score", "Gym"),
    "cafe": ("cafe_score", "Cafe"),
    "restaurant": ("restaurant_score", "Restaurant"),
    "bar": ("bar_score", "Bar"),
    "transit": ("transit_score", "Transit"),
    "school": ("school_score", "School"),
}
# premiumRetail is an underlying metric with no toggle of its own, so it is never
# suggested as a pill; it only feeds the composite.

_WORDS = {
    "N": "north", "NE": "northeast", "E": "east", "SE": "southeast",
    "S": "south", "SW": "southwest", "W": "west", "NW": "northwest",
}  # fmt: skip


def weak_factors(
    sub_scores: dict, limit: int, selected: list[str] | None = None
) -> list[tuple[str, float]]:
    """Lowest-scoring improvable factors below WEAK_BELOW, ascending (ties
    keep IMPROVABLE order). `sub_scores` maps wire keys to scores; `selected`
    (wire keys) restricts the candidates, None means no restriction."""
    weak = [
        (key, float(sub_scores[key]))
        for key in IMPROVABLE
        if (selected is None or key in selected)
        and sub_scores.get(key) is not None
        and float(sub_scores[key]) < WEAK_BELOW
    ]
    weak.sort(key=lambda item: item[1])  # stable
    return weak[:limit]


def _with_selected_composite(cells: list[dict], priorities: Priorities) -> list[dict]:
    """Cells with composite_score replaced by the selected-factor composite
    (cells with no selected score are dropped)."""
    out = []
    for cell in cells:
        value = priorities.composite_from_columns(cell)
        if value is not None:
            out.append({**cell, "composite_score": value})
    return out


def neighbour_cells(cells: list[dict], lat: float, lon: float, radius_mi: float, own_geohash: str):
    """(cell, distance_m) for scored cells within the radius, excluding the
    cell under the point."""
    radius_m = radius_mi * M_PER_MI
    out = []
    for cell in cells:
        if cell.get("geohash") == own_geohash or cell.get("composite_score") is None:
            continue
        d = haversine_m(lat, lon, cell["latitude"], cell["longitude"])
        if d <= radius_m:
            out.append((cell, d))
    return out


def _round(value: float) -> int:
    return int(value + 0.5)


def best_area_for_factor(neighbours, lat, lon, column, base_score, base_composite) -> dict | None:
    best = None
    for cell, d in neighbours:
        value = cell.get(column)
        if value is None or float(value) - base_score < BETTER_AREA_MIN_GAIN:
            continue
        key = (float(value), float(cell["composite_score"]))
        if best is None or key > best[0]:
            best = (key, cell, d)
    if best is None:
        return None
    _, cell, d = best
    return {
        "latitude": cell["latitude"],
        "longitude": cell["longitude"],
        "direction": compass(lat, lon, cell["latitude"], cell["longitude"]),
        "distance_mi": round(m_to_mi(d), 2),
        "distance_label": format_distance(d),
        "factor_score": _round(float(cell[column])),
        "factor_gain": _round(float(cell[column]) - base_score),
        "composite_score": _round(float(cell["composite_score"])),
        "composite_gain": _round(float(cell["composite_score"]) - base_composite),
    }


def best_nearby(neighbours, lat, lon, base_composite) -> dict | None:
    best = None
    for cell, d in neighbours:
        gain = float(cell["composite_score"]) - base_composite
        if gain >= BEST_NEARBY_MIN_GAIN and (best is None or gain > best[0]):
            best = (gain, cell, d)
    if best is None:
        return None
    gain, cell, d = best
    return {
        "latitude": cell["latitude"],
        "longitude": cell["longitude"],
        "direction": compass(lat, lon, cell["latitude"], cell["longitude"]),
        "distance_label": format_distance(d),
        "composite_score": _round(float(cell["composite_score"])),
        "composite_gain": _round(gain),
    }


def build_tip(label: str, score: float, rank: int, places: list[dict], better: dict | None) -> str:
    lead = "is your weakest factor" if rank == 0 else "is a weak spot"
    parts = [f"{label} {lead} ({_round(score)})."]
    if places:
        p = places[0]
        parts.append(
            f"The closest option is {p['name']}, {p['distance_label']} {_WORDS[p['direction']]}."
        )
    if better:
        parts.append(
            f"The area about {better['distance_label']} {_WORDS[better['direction']]} "
            f"scores {better['factor_score']} on {label.lower()}."
        )
    return " ".join(parts)


def build_improve(
    conn,
    lat,
    lon,
    radius_mi,
    max_suggestions,
    sub_scores: dict,
    composite: float,
    cells,
    own_geohash,
    priorities: Priorities | None = None,
) -> dict:
    """With an explicit `priorities`, only selected factors can be suggested and
    the composite (the area's and every neighbour cell's) is the weighted
    average over the selected factors; otherwise the stored composites are used."""
    selected = None
    if priorities is not None:
        selected = priorities.factors
        if priorities.explicit:
            own = priorities.composite_from_keys(sub_scores)
            composite = composite if own is None else round(own, 1)
            cells = _with_selected_composite(cells, priorities)
    neighbours = neighbour_cells(cells, lat, lon, radius_mi, own_geohash)
    suggestions = []
    for rank, (key, score) in enumerate(weak_factors(sub_scores, max_suggestions, selected)):
        column, label = IMPROVABLE[key]
        places = [
            {
                k: p[k]
                for k in (
                    "name",
                    "brand",
                    "distance_mi",
                    "distance_label",
                    "direction",
                    "latitude",
                    "longitude",
                )
            }
            for p in places_for_factor(conn, lat, lon, key, radius_mi, MAX_PLACES)
        ]
        better = best_area_for_factor(neighbours, lat, lon, column, score, composite)
        suggestions.append(
            {
                "factor": key,
                "label": label,
                "score": _round(score),
                "places": places,
                "better_area": better,
                "tip": build_tip(label, score, rank, places, better),
            }
        )
    return {
        "composite": composite,
        "radius_mi": radius_mi,
        "suggestions": suggestions,
        "best_nearby": best_nearby(neighbours, lat, lon, composite),
        "priorities": list(selected if selected is not None else TOGGLEABLE_FACTORS),
    }


def search_box(lat: float, lon: float, radius_mi: float) -> tuple[float, float, float, float]:
    return bbox_around(lat, lon, radius_mi * M_PER_MI)
