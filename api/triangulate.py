"""POST /v1/triangulate: the best places inside the overlap (or union) of several anchors'
travel-time areas.

Each anchor becomes a set of reachable grid cells from the precomputed road-network cell graph
(`anchor_cells`, api/reach.py, migration 0022); `intersect` and `union` are exact set
operations on those cells, and `rank_in_cells` ranks the stored scores inside. An anchor with
no routing data falls back to a straight-line circle (`anchor_to_circle`: radius =
minutes x the mode's assumed speed, haversine membership), expressed as the cells inside it so
both kinds combine exactly. `rank_candidates` is the older circle-only ranking, now
used only by tests.
"""

from collections.abc import Callable
from dataclasses import dataclass

from common.cellgrid import CellKey, cell_center, cell_index
from common.geo import haversine_m

ASSUMED_SPEED_KMH: dict[str, float] = {
    "drive": 40.0,
    "transit": 25.0,
    "walk": 4.8,
}

DEFAULT_MODE = "drive"

# ---- tune = "auto" (see the "auto" section below). All tunables live here.
# Longest trip, in minutes, per mode (the same caps as the web steppers).
AUTO_MAX_MINUTES: dict[str, int] = {"walk": 30, "transit": 45, "drive": 60}
# Minutes are searched in steps of this size.
AUTO_STEP_MIN = 5
# Perceived minutes = actual minutes + this penalty. Transit minutes already include the
# expected wait for the first train; the penalty stands for transfers, reliability and fare,
# and for drive getting to and parking the car, so a short walk is preferred to an equally
# short ride. Internal: never shown to users.
MODE_PENALTY_MIN: dict[str, float] = {"walk": 0.0, "transit": 5.0, "drive": 3.0}
# Fewest shared cells that count as a neighborhood (about 1 sq mi).
MIN_OVERLAP_CELLS = 4
# Places to live are kept when cost <= cheapest cost * COST_BAND_RATIO + COST_BAND_SLACK.
COST_BAND_RATIO = 1.25
COST_BAND_SLACK = 10.0
# One-way trips per week when the anchor does not say: the main address (work), the others.
DEFAULT_TRIPS_MAIN = 5
DEFAULT_TRIPS_OTHER = 2
# Server-side default isochrone time budget when an anchor omits
# maxTravelMinutes, per openapi.yaml's AnchorPoint.maxTravelMinutes
# description ("Defaults to a server-side default if omitted").
DEFAULT_MAX_TRAVEL_MINUTES = 20


@dataclass(frozen=True)
class AnchorCircle:
    """A resolved anchor: lat/lon plus its placeholder isochrone radius in
    meters."""

    latitude: float
    longitude: float
    radius_m: float


def anchor_to_circle(
    latitude: float, longitude: float, max_travel_minutes: int | None, mode: str | None
) -> AnchorCircle:
    """Builds the placeholder circle for one already-resolved anchor
    (lat/lon known -- geocoding, if the anchor came in as an address,
    happens before this is called)."""
    mode = mode or DEFAULT_MODE
    minutes = max_travel_minutes if max_travel_minutes is not None else DEFAULT_MAX_TRAVEL_MINUTES
    speed_kmh = ASSUMED_SPEED_KMH.get(mode, ASSUMED_SPEED_KMH[DEFAULT_MODE])
    radius_m = speed_kmh * 1000.0 / 60.0 * minutes
    return AnchorCircle(latitude=latitude, longitude=longitude, radius_m=radius_m)


def point_in_circle(lat: float, lon: float, circle: AnchorCircle) -> bool:
    return haversine_m(lat, lon, circle.latitude, circle.longitude) <= circle.radius_m


def rank_candidates(
    candidates: list[dict],
    circles: list[AnchorCircle],
    combine_mode: str = "intersect",
    limit: int = 50,
) -> list[dict]:
    """candidates: rows with at least latitude/longitude/composite_score
    (e.g. from common.db.iter_latest_scored_geo_entities). Filters to those
    within all circles (combine_mode="intersect", the contract default) or
    any circle ("union"), then returns the top `limit` sorted by
    composite_score descending. An empty circle list (shouldn't happen --
    TriangulateRequest requires >=1 anchor -- but handled defensively)
    returns all candidates unranked-by-membership, just score-sorted."""
    if not circles:
        matched = list(candidates)
    elif combine_mode == "union":
        matched = [
            c
            for c in candidates
            if any(point_in_circle(c["latitude"], c["longitude"], circle) for circle in circles)
        ]
    else:  # "intersect" (contract default)
        matched = [
            c
            for c in candidates
            if all(point_in_circle(c["latitude"], c["longitude"], circle) for circle in circles)
        ]
    matched.sort(key=lambda c: c["composite_score"], reverse=True)
    return matched[:limit]


# ----------------------------------------------------------------------------- real isochrones
# Phase 4: anchors become reachable-cell sets from the precomputed road-network cell graph
# (api/reach.py). An anchor with no routing data (area not precomputed yet) falls back to the
# circle above, expressed as the cells inside it, so both kinds intersect / union exactly.


def anchor_reach(conn, lat: float, lon: float, mode: str | None, minutes: int | None):
    """(cell -> minutes dict or None for the estimate, effective minutes, method)."""
    from api import reach

    mode = mode or DEFAULT_MODE
    mins = reach.clamp_minutes(mode, minutes if minutes is not None else DEFAULT_MAX_TRAVEL_MINUTES)
    got = reach.reach(conn, lat, lon, mode, mins)
    if got is not None:
        return got.cells, int(mins), "network"
    return None, int(mins), "estimate"


def anchor_cells(conn, lat: float, lon: float, mode: str | None, minutes: int | None):
    """(set of cell keys, effective minutes, method) for one anchor."""
    from api import isochrone

    timed, mins, method = anchor_reach(conn, lat, lon, mode, minutes)
    if timed is not None:
        return set(timed), mins, method
    circle = anchor_to_circle(lat, lon, mins, mode)
    return isochrone.disc_cells(lat, lon, circle.radius_m), mins, method


def shape_for(cells: set, label: str | None, mode: str, minutes: int, method: str, lat: float):
    from api import isochrone

    return {
        "label": label,
        "mode": mode,
        "minutes": minutes,
        "method": method,
        "cell_count": len(cells),
        "area_sq_mi": round(isochrone.area_sq_mi(len(cells), lat), 2),
        "geometry": isochrone.cells_to_geometry(cells),
    }


def cells_box(cells: set) -> tuple[float, float, float, float] | None:
    """(min_lat, max_lat, min_lon, max_lon) covering the cells."""
    from common.cellgrid import cell_bounds

    if not cells:
        return None
    bounds = [cell_bounds(iy, ix) for iy, ix in cells]
    return (
        min(b[0] for b in bounds),
        max(b[2] for b in bounds),
        min(b[1] for b in bounds),
        max(b[3] for b in bounds),
    )


def rank_in_cells(candidates: list[dict], cells: set, limit: int, spec=None) -> list[dict]:
    """Top `limit` candidates inside `cells` by composite_score. With a ScoreSpec, each
    candidate's composite_score is first recomputed over the selected factors (rounded like
    the map) and candidates with no selected sub-score are dropped."""
    from common.cellgrid import cell_index

    inside = [c for c in candidates if cell_index(c["latitude"], c["longitude"]) in cells]
    if spec is not None:
        from api.mapdata import SCORE_DECIMALS, composite_from_row

        rescored = []
        for c in inside:
            value = composite_from_row(c, spec)
            if value is not None:
                rescored.append({**c, "composite_score": round(value, SCORE_DECIMALS)})
        inside = rescored
    inside.sort(key=lambda c: c["composite_score"], reverse=True)
    return inside[:limit]


# ----------------------------------------------------------------------------- tune = "auto"
# Pure functions (no database): they take the per-mode reach dicts (cell -> minutes).
# A "merged" anchor maps cell -> (perceived minutes, chosen mode, actual minutes).

Merged = dict[CellKey, tuple[float, str, float]]


def auto_modes(mode: str) -> list[str]:
    """The anchor's mode plus walking (a short walk beats a short ride)."""
    return [mode] if mode == "walk" else [mode, "walk"]


def auto_cap(mode: str) -> int:
    return AUTO_MAX_MINUTES[mode]


def default_trips(index: int) -> int:
    return DEFAULT_TRIPS_MAIN if index == 0 else DEFAULT_TRIPS_OTHER


def estimate_cells(lat: float, lon: float, mode: str, cap: int) -> dict[CellKey, float]:
    """Straight-line fallback: the cells inside the circle, minutes = distance / assumed speed."""
    from api import isochrone

    speed_m_min = ASSUMED_SPEED_KMH[mode] * 1000.0 / 60.0
    cells = isochrone.disc_cells(lat, lon, speed_m_min * cap)
    return {
        key: min(float(cap), haversine_m(lat, lon, *cell_center(*key)) / speed_m_min)
        for key in cells
    }


def merge_modes(per_mode: dict[str, dict[CellKey, float]]) -> Merged:
    """Per cell, the mode with the lowest perceived minutes (ties: fewer actual minutes)."""
    merged: Merged = {}
    for mode, cells in per_mode.items():
        penalty = MODE_PENALTY_MIN[mode]
        for key, minutes in cells.items():
            candidate = (minutes + penalty, mode, minutes)
            current = merged.get(key)
            if current is None or (candidate[0], candidate[2]) < (current[0], current[2]):
                merged[key] = candidate
    return merged


def feasible_cells(merged: list[Merged]) -> set[CellKey]:
    """Cells reachable from every anchor."""
    if not merged:
        return set()
    keys = set(merged[0])
    for m in merged[1:]:
        keys &= m.keys()
    return keys


def worst_minutes(merged: list[Merged], key: CellKey) -> float:
    return max(m[key][2] for m in merged)


def tuned_land_minutes(
    merged: list[Merged],
    feasible: set[CellKey],
    ceiling: int,
    is_land: Callable[[list[CellKey]], dict[CellKey, tuple[float, float] | None]],
) -> tuple[int | None, dict[CellKey, tuple[float, float]]]:
    """Smallest multiple of AUTO_STEP_MIN (up to `ceiling`) at which at least MIN_OVERLAP_CELLS
    feasible LAND cells have every anchor within it, and those land cells with their land
    point. Water cells never count. Each step land-checks only the cells that newly fit
    (one `is_land` call per step); (None, {}) when no step has enough land cells."""
    worst = {key: worst_minutes(merged, key) for key in feasible}
    land: dict[CellKey, tuple[float, float]] = {}
    checked: set[CellKey] = set()
    for minutes in range(AUTO_STEP_MIN, ceiling + 1, AUTO_STEP_MIN):
        fresh = [k for k, w in worst.items() if w <= minutes and k not in checked]
        if fresh:
            checked.update(fresh)
            land.update({k: p for k, p in is_land(fresh).items() if p is not None})
        if len(land) >= MIN_OVERLAP_CELLS:
            return minutes, land
    return None, {}


def cells_within(merged: Merged, minutes: int) -> set[CellKey]:
    return {key for key, (_p, _m, actual) in merged.items() if actual <= minutes}


def cell_costs(
    merged: list[Merged], feasible: set[CellKey], trips: list[int]
) -> dict[CellKey, float]:
    """Weekly-trip-weighted perceived minutes to all anchors (lower is better)."""
    return {key: sum(w * m[key][0] for w, m in zip(trips, merged, strict=True)) for key in feasible}


def cost_band(costs: dict[CellKey, float]) -> dict[CellKey, float]:
    """The cells cheap enough to live in: within a ratio and slack of the cheapest."""
    if not costs:
        return {}
    limit = min(costs.values()) * COST_BAND_RATIO + COST_BAND_SLACK
    return {key: cost for key, cost in costs.items() if cost <= limit}


def cell_travel(merged: list[Merged], key: CellKey) -> list[tuple[str, int]]:
    """(chosen mode, actual minutes rounded) per anchor, in request order."""
    return [(m[key][1], round(m[key][2])) for m in merged]


def rank_by_score_then_cost(
    candidates: list[dict], band: dict[CellKey, float], limit: int, spec=None
) -> list[dict]:
    """Candidates inside the band by composite score descending, cost ascending on ties."""
    ranked = rank_in_cells(candidates, set(band), len(candidates), spec)
    ranked.sort(
        key=lambda c: (-c["composite_score"], band[cell_index(c["latitude"], c["longitude"])])
    )
    seen: set[CellKey] = set()
    unique = []
    for c in ranked:
        key = cell_index(c["latitude"], c["longitude"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique[:limit]


def fixed_travel(
    timed: list[dict[CellKey, float] | None], labels: list[str], modes: list[str], key: CellKey
) -> list[dict] | None:
    """Travel entries for tune="fixed" (each anchor's own mode); None when any anchor has no
    minutes for the cell (estimate fallback, or a union result outside its area)."""
    out = []
    for cells, label, mode in zip(timed, labels, modes, strict=True):
        minutes = None if cells is None else cells.get(key)
        if minutes is None:
            return None
        out.append({"label": label, "mode": mode, "minutes": round(minutes)})
    return out
