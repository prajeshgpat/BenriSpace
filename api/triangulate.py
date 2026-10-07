"""**Phase 1 approximation** for Phase 2's real Valhalla isochrones
(docs/ROADMAP.md Phase 2: stand up Valhalla, compute true drive/transit/walk
isochrones per anchor, intersect/union them, rank precomputed scores that
fall inside). Valhalla's hosting location is explicitly undecided as of
this writing (docs/ROADMAP.md Phase 2 Requirements: "Where Valhalla runs --
deferred by you to this phase"), so there's no isochrone service to call
yet.

This module approximates each anchor's isochrone as a **circle**: radius =
`maxTravelMinutes * assumed_avg_speed` for the anchor's travel mode,
membership tested with straight-line (haversine) distance via
common.geo.haversine_m -- not real road-network travel time. This is a
coarse placeholder by design (a circle ignores water crossings, highway
access, actual congestion, etc.) but keeps the endpoint's contract shape
(TriangulateRequest -> ranked RankedAddress list) fully functional today.

**Swap point for Phase 2**: replace `anchor_to_circle()` (issue a real
Valhalla isochrone request, get back a polygon) and `point_in_circle()`
(point-in-polygon test instead of a radius check) below. `rank_candidates()`'s
signature (candidates + resolved "isochrone membership" objects +
combine_mode + limit -> ranked list) stays the same, so api/main.py's route
handler doesn't need to change shape, only what it imports.

Assumed average speeds (documented, hand-tuned placeholders -- a Phase 2
TODO to replace with real routing, not measured against actual NYC-metro
traffic data):
- drive: 40 km/h -- mixed local/arterial/highway blend
- transit: 25 km/h -- bus/rail blend including wait/transfer overhead
- walk: 4.8 km/h -- ~3 mph, standard walking-speed assumption
"""

from dataclasses import dataclass

from common.geo import haversine_m

ASSUMED_SPEED_KMH: dict[str, float] = {
    "drive": 40.0,
    "transit": 25.0,
    "walk": 4.8,
}

DEFAULT_MODE = "drive"
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


def anchor_cells(conn, lat: float, lon: float, mode: str | None, minutes: int | None):
    """(set of cell keys, effective minutes, method) for one anchor."""
    from api import isochrone, reach

    mode = mode or DEFAULT_MODE
    mins = reach.clamp_minutes(mode, minutes if minutes is not None else DEFAULT_MAX_TRAVEL_MINUTES)
    got = reach.reach(conn, lat, lon, mode, mins)
    if got is not None:
        return set(got.cells), int(mins), "network"
    circle = anchor_to_circle(lat, lon, int(mins), mode)
    return isochrone.disc_cells(lat, lon, circle.radius_m), int(mins), "estimate"


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
