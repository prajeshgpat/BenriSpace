"""BenriSpace API -- FastAPI app implementing contracts/openapi.yaml's
three data endpoints: GET /score, GET /score/{geoEntityId}/explanation,
POST /triangulate.

**Phase 4 (auth + rate limiting) is intentionally NOT implemented here.**
Per PROJECT.md, that's a later addition on top of this app: a
Depends(...)-style auth dependency plus middleware checking `usage_counters`
(PHASES.md Phase 4). Route handlers below are kept as plain functions with
ordinary FastAPI parameter declarations (Query/path params, a Pydantic
request-body model) -- no custom dependency-injection container, no
module-level state touched at import time -- specifically so Phase 4 can
add an auth `Depends()` to each handler's signature and rate-limit
middleware to the app without restructuring anything here. Every DB
connection is opened per-request via `common.db.get_connection()`'s context
manager, never held at module scope, so `from api.main import app` works
without a live Postgres (see tests/test_api.py) and adding request-scoped
auth dependencies later is a purely additive change.

All three endpoints are unauthenticated for now per this task's scope --
the `security`/`401`/`429` parts of openapi.yaml are Phase 4, ignored here.
"""

from uuid import UUID

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.ai_explain import ai_explanation
from api.areas import (
    AREA_MAX_SQ_MI,
    SQ_M_PER_SQ_MI,
    area_explanation,
    bounded_by_text,
    build_area_response,
    pick_area,
)
from api.explain import build_explanation, nearest_m_by_factor, nearest_mi_by_factor
from api.geocoding import geocode_address
from api.lookup import (
    bbox_around,
    build_score_response,
    get_feature_row,
    nearest_geo_entity,
    sub_scores_from_score_row,
)
from api.mapdata import (
    InvalidMapRequest,
    build_cells_response,
    find_top,
    parse_bbox,
    parse_score_spec,
)
from api.places import FACTOR_CATEGORIES, places_for_factor
from api.reverse import ReverseUnavailable
from api.reverse import reverse as reverse_geocode
from api.schemas import (
    AnchorPoint,
    AreaExplanationResponse,
    AreaScoreResponse,
    Error,
    ExplanationResponse,
    MapCellsResponse,
    MapTopResponse,
    PlacesResponse,
    RankedAddress,
    ReverseResponse,
    ScoreResponse,
    SuggestResponse,
    TriangulateRequest,
    TriangulateResponse,
)
from api.suggest import MIN_QUERY_LENGTH, SuggestUnavailable, in_coverage, normalize_query
from api.suggest import suggest as suggest_addresses
from api.triangulate import anchor_to_circle, rank_candidates
from api.triangulate_sql import combined_bbox, get_scored_candidates_in_box
from common.config import CORS_ALLOWED_ORIGINS, SCORING_WEIGHTS_VERSION
from common.db import (
    get_area_aggregate,
    get_area_candidates,
    get_connection,
    get_geo_entities_in_bbox,
    get_geo_entity_by_geohash,
    get_latest_score,
    get_map_cells,
)
from common.geo import encode as geohash_encode
from common.units import mi_to_km

app = FastAPI(title="BenriSpace API", version="0.5.0")

# The frontend is a separate origin (benrispace.com / localhost:3000) from
# the API (api.benrispace.com / localhost:8000), so browsers need CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=["Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=Error(code=code, message=message).model_dump(by_alias=True, exclude_none=True),
    )


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422 `{detail: [...]}` body isn't in the contract --
    every error there is `{code, message}`, and bad input is a 400."""
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ()))
    detail = first.get("msg", "Invalid request")
    return _error(400, "invalid_request", f"{location}: {detail}" if location else detail)


def _resolve_anchor_latlon(anchor: AnchorPoint) -> tuple[float, float] | None:
    """Returns (lat, lon) for an anchor, geocoding its address if lat/lon
    weren't provided directly. Returns None if the anchor can't be
    resolved at all (no address and no lat/lon, or an address Nominatim
    can't geocode)."""
    if anchor.latitude is not None and anchor.longitude is not None:
        return anchor.latitude, anchor.longitude
    if anchor.address:
        return geocode_address(anchor.address)
    return None


@app.get(
    "/v1/score",
    response_model=ScoreResponse,
    responses={400: {"model": Error}, 404: {"model": Error}},
)
def get_score(
    address: str | None = Query(
        default=None, description="Free-text address. Mutually exclusive with lat/lon."
    ),
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
):
    if address and (lat is not None or lon is not None):
        return _error(400, "invalid_request", "Provide either address or lat/lon, not both.")
    if not address and (lat is None or lon is None):
        return _error(400, "invalid_request", "Provide address, or both lat and lon.")

    if address:
        geocoded = geocode_address(address)
        if geocoded is None:
            return _error(400, "unresolvable_address", f"Could not geocode address: {address!r}")
        lat, lon = geocoded

    # geohash6, same precision/convention as ingestion/grid.py's grid build.
    geohash = geohash_encode(lat, lon, precision=6)

    with get_connection() as conn:
        geo_entity = get_geo_entity_by_geohash(conn, geohash)
        if geo_entity is None:
            # Exact-cell miss -- fall back to a bounding-box query + nearest
            # by haversine in Python. Cheap: ~64k geo_entities metro-wide.
            min_lat, max_lat, min_lon, max_lon = bbox_around(lat, lon)
            candidates = get_geo_entities_in_bbox(conn, min_lat, max_lat, min_lon, max_lon)
            geo_entity = nearest_geo_entity(lat, lon, candidates)
        if geo_entity is None:
            return _error(
                404, "not_found", "No geo entity within ingestion coverage for this location."
            )

        score_row = get_latest_score(
            conn, str(geo_entity["id"]), SCORING_WEIGHTS_VERSION
        )
        if score_row is None:
            return _error(404, "not_found", "No score on file for this geo entity yet.")
        feature_row = get_feature_row(conn, str(geo_entity["id"]))

    return build_score_response(geo_entity, score_row, feature_row)


@app.get(
    "/v1/score/{geo_entity_id}/explanation",
    response_model=ExplanationResponse,
    responses={404: {"model": Error}},
)
def get_score_explanation(geo_entity_id: UUID):
    with get_connection() as conn:
        score_row = get_latest_score(conn, str(geo_entity_id), SCORING_WEIGHTS_VERSION)
        feature_row = get_feature_row(conn, str(geo_entity_id)) if score_row else None
    if score_row is None:
        return _error(404, "not_found", "No score on file for this geo entity.")

    sub_scores = sub_scores_from_score_row(score_row)
    # Phase 1 template placeholder, see api/explain.py. Distances are
    # metric internally and rendered in feet/miles.
    nearest_m = nearest_m_by_factor(feature_row)
    with get_connection() as conn:
        explanation = ai_explanation(
            conn,
            str(geo_entity_id),
            sub_scores,
            nearest_m,
            float(score_row["composite_score"]),
            "this location",
            score_row.get("weights_version") or SCORING_WEIGHTS_VERSION,
        )
    source = "ai"
    if explanation is None:
        explanation = build_explanation(sub_scores, nearest_m)
        source = "rules"
    return ExplanationResponse(
        geo_entity_id=geo_entity_id,
        explanation=explanation,
        source=source,
        computed_at=score_row["computed_at"],
        nearest_mi=nearest_mi_by_factor(feature_row),
    )


@app.post(
    "/v1/triangulate",
    response_model=TriangulateResponse,
    responses={400: {"model": Error}},
)
def triangulate(body: TriangulateRequest):
    circles = []
    for anchor in body.anchors:
        latlon = _resolve_anchor_latlon(anchor)
        if latlon is None:
            return _error(
                400,
                "invalid_anchor",
                f"Anchor {anchor.label!r} needs a resolvable address or lat/lon.",
            )
        lat, lon = latlon
        # Phase 1 straight-line-circle placeholder, see api/triangulate.py.
        circles.append(anchor_to_circle(lat, lon, anchor.max_travel_minutes, anchor.mode))

    with get_connection() as conn:
        # Bounding-box prefilter: only cells near the circles leave the DB;
        # rank_candidates still does the exact haversine test.
        candidates = get_scored_candidates_in_box(
            conn, combined_bbox(circles, body.combine_mode), SCORING_WEIGHTS_VERSION
        )

    for c in candidates:
        c["address"] = c.get("formatted_address") or f"{c['latitude']:.5f},{c['longitude']:.5f}"

    ranked = rank_candidates(candidates, circles, combine_mode=body.combine_mode, limit=body.limit)

    results = [
        RankedAddress(
            geo_entity_id=r["geo_entity_id"],
            address=r["address"],
            latitude=r["latitude"],
            longitude=r["longitude"],
            composite_score=r["composite_score"],
        )
        for r in ranked
    ]
    return TriangulateResponse(results=results)


CACHE_CONTROL_5_MIN = "public, max-age=300"


@app.get(
    "/v1/suggest",
    response_model=SuggestResponse,
    responses={400: {"model": Error}, 503: {"model": Error}},
)
def suggest(
    response: Response,
    q: str = Query(max_length=200, description="Text typed so far. At least 3 characters."),
    limit: int = Query(default=5, ge=1, le=10),
):
    q = normalize_query(q)
    if len(q) < MIN_QUERY_LENGTH:
        return _error(
            400, "invalid_request", f"q must be at least {MIN_QUERY_LENGTH} characters."
        )
    try:
        suggestions = suggest_addresses(q, limit)
    except SuggestUnavailable:
        return _error(503, "suggest_unavailable", "Address suggestions are temporarily unavailable.")
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return SuggestResponse(suggestions=suggestions)


@app.get(
    "/v1/reverse",
    response_model=ReverseResponse,
    responses={422: {"model": Error}, 503: {"model": Error}},
)
def reverse(
    response: Response,
    lat: float = Query(ge=-90, le=90, description="Latitude."),
    lon: float = Query(ge=-180, le=180, description="Longitude."),
):
    if not in_coverage(lat, lon):
        return _error(422, "out_of_coverage", "Location is outside the covered metro area.")
    try:
        label = reverse_geocode(lat, lon)
    except ReverseUnavailable:
        return _error(503, "reverse_unavailable", "Address lookup is temporarily unavailable.")
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return ReverseResponse(label=label, latitude=lat, longitude=lon)


@app.get(
    "/v1/places",
    response_model=PlacesResponse,
    responses={400: {"model": Error}, 422: {"model": Error}},
)
def get_places(
    response: Response,
    lat: float = Query(ge=-90, le=90, description="Latitude."),
    lon: float = Query(ge=-180, le=180, description="Longitude."),
    factor: str = Query(description="Factor key, e.g. grocery, gasStation, premiumRetail."),
    radius_mi: float = Query(default=1.0, gt=0, le=5, alias="radiusMi"),
    limit: int = Query(default=5, ge=1, le=20),
):
    if factor not in FACTOR_CATEGORIES:
        return _error(
            400,
            "invalid_request",
            f"factor must be one of: {', '.join(FACTOR_CATEGORIES)}.",
        )
    if not in_coverage(lat, lon):
        return _error(422, "out_of_coverage", "Location is outside the covered metro area.")
    with get_connection() as conn:
        places = places_for_factor(conn, lat, lon, factor, radius_mi, limit)
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return PlacesResponse(factor=factor, radius_mi=radius_mi, places=places)


def _resolve_area(lat: float, lon: float):
    """Shared by /v1/area and /v1/area/explanation. Returns an error
    JSONResponse, or (area, aggregate, geo_entity, feature_row)."""
    if not in_coverage(lat, lon):
        return _error(422, "out_of_coverage", "Location is outside the covered metro area.")

    def not_found() -> JSONResponse:
        return _error(404, "area_not_found", "No road-bounded area found for this location.")

    with get_connection() as conn:
        area = pick_area(lat, lon, get_area_candidates(conn, lat, lon))
        if area is None or area["area_sq_m"] / SQ_M_PER_SQ_MI > AREA_MAX_SQ_MI:
            return not_found()
        aggregate = get_area_aggregate(conn, area["id"], SCORING_WEIGHTS_VERSION)
        if aggregate is None:
            return not_found()
        # The grid cell under the click supplies geoEntityId, school district
        # and nearest distances (same lookup as /score?lat&lon).
        geo_entity = get_geo_entity_by_geohash(conn, geohash_encode(lat, lon, precision=6))
        if geo_entity is None:
            min_lat, max_lat, min_lon, max_lon = bbox_around(lat, lon)
            geo_entity = nearest_geo_entity(
                lat, lon, get_geo_entities_in_bbox(conn, min_lat, max_lat, min_lon, max_lon)
            )
        if geo_entity is None:
            return not_found()
        feature_row = get_feature_row(conn, str(geo_entity["id"]))
    return area, aggregate, geo_entity, feature_row


@app.get(
    "/v1/area",
    response_model=AreaScoreResponse,
    responses={400: {"model": Error}, 404: {"model": Error}, 422: {"model": Error}},
)
def get_area(
    response: Response,
    lat: float = Query(ge=-90, le=90, description="Latitude."),
    lon: float = Query(ge=-180, le=180, description="Longitude."),
):
    resolved = _resolve_area(lat, lon)
    if isinstance(resolved, JSONResponse):
        return resolved
    area, aggregate, geo_entity, feature_row = resolved
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return build_area_response(
        area, aggregate, geo_entity, lat, lon, feature_row, SCORING_WEIGHTS_VERSION
    )


@app.get(
    "/v1/area/explanation",
    response_model=AreaExplanationResponse,
    responses={400: {"model": Error}, 404: {"model": Error}, 422: {"model": Error}},
)
def get_area_explanation(
    response: Response,
    lat: float = Query(ge=-90, le=90, description="Latitude."),
    lon: float = Query(ge=-180, le=180, description="Longitude."),
):
    """AI-written explanation for the area under a point; rule-based text when
    the LLM layer is unavailable. Kept separate from /v1/area so that stays fast."""
    resolved = _resolve_area(lat, lon)
    if isinstance(resolved, JSONResponse):
        return resolved
    area, aggregate, _geo_entity, feature_row = resolved
    sub_scores = sub_scores_from_score_row(aggregate)
    nearest_m = nearest_m_by_factor(feature_row)
    with get_connection() as conn:
        text = ai_explanation(
            conn,
            f"area:{area['id']}",
            sub_scores,
            nearest_m,
            float(aggregate["composite_score"]),
            bounded_by_text(list(area.get("bounded_by") or [])),
            aggregate.get("weights_version") or SCORING_WEIGHTS_VERSION,
        )
    source = "ai"
    if text is None:
        text = area_explanation(sub_scores, feature_row)
        source = "rules"
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return AreaExplanationResponse(explanation=text, source=source, area_id=area["id"])


@app.get(
    "/v1/map/cells",
    response_model=MapCellsResponse,
    responses={400: {"model": Error}},
)
def get_map_cells_route(
    response: Response,
    bbox: str = Query(description="Viewport as minLon,minLat,maxLon,maxLat."),
    precision: int = Query(default=6, json_schema_extra={"enum": [5, 6]}),
    factors: str | None = Query(default=None),
    weights: str | None = Query(default=None),
    limit: int = Query(default=8000, ge=1, le=20000),
):
    if precision not in (5, 6):
        return _error(400, "invalid_request", "precision must be 5 or 6.")
    try:
        parsed_bbox = parse_bbox(bbox)
        spec = parse_score_spec(factors, weights)
    except InvalidMapRequest as exc:
        return _error(400, "invalid_request", str(exc))

    with get_connection() as conn:
        # limit + 1 rows reveals whether the viewport held more than `limit`.
        rows = get_map_cells(
            conn, spec.columns_weights, SCORING_WEIGHTS_VERSION, parsed_bbox, precision, limit + 1
        )
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return build_cells_response(rows, spec, precision, limit)


@app.get(
    "/v1/map/top",
    response_model=MapTopResponse,
    responses={400: {"model": Error}},
)
def get_map_top(
    response: Response,
    bbox: str | None = Query(default=None),
    factors: str | None = Query(default=None),
    weights: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    min_separation_km: float | None = Query(
        default=None, ge=0, le=50, alias="minSeparationKm", deprecated=True
    ),
    min_separation_mi: float | None = Query(default=None, ge=0, le=31, alias="minSeparationMi"),
):
    if min_separation_km is not None and min_separation_mi is not None:
        return _error(
            400,
            "invalid_request",
            "Provide minSeparationMi or the deprecated minSeparationKm, not both.",
        )
    if min_separation_mi is not None:
        min_separation_km = mi_to_km(min_separation_mi)
    elif min_separation_km is None:
        min_separation_km = 3.0  # default spacing, same as before
    try:
        parsed_bbox = parse_bbox(bbox) if bbox is not None else None
        spec = parse_score_spec(factors, weights)
    except InvalidMapRequest as exc:
        return _error(400, "invalid_request", str(exc))

    with get_connection() as conn:
        result = find_top(conn, spec, parsed_bbox, limit, min_separation_km)
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return result
