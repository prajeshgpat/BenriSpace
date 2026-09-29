"""**Phase 1 approximation** for Phase 2's real Valhalla isochrones
(PHASES.md Phase 2: stand up Valhalla, compute true drive/transit/walk
isochrones per anchor, intersect/union them, rank precomputed scores that
fall inside). Valhalla's hosting location is explicitly undecided as of
this writing (PHASES.md Phase 2 Requirements: "Where Valhalla runs --
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
