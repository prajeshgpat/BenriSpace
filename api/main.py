"""BenriSpace API -- FastAPI app implementing contracts/openapi.yaml's
three data endpoints: GET /score, GET /score/{geoEntityId}/explanation,
POST /triangulate.

**Phase 4 (auth + rate limiting) is intentionally NOT implemented here.**
Per docs/ROADMAP.md, that's a later addition on top of this app: a
Depends(...)-style auth dependency plus middleware checking `usage_counters`
(docs/ROADMAP.md Phase 4). Route handlers below are kept as plain functions with
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

import contextlib
import logging
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from api import area_cache, area_scores, point_score, scorefile, slim_areas, sources
from api.ai_explain import ai_explanation
from api.areas import (
    area_explanation,
    bounded_by_text,
    build_area_response,
    pick_area,
    point_in_polygon,
    usable_areas,
)
from api.chat import ChatHttpError, ChatRequest, ChatResponse, handle_chat, stream_chat
from api.explain import build_explanation, nearest_m_by_factor, nearest_mi_by_factor
from api.feedback import FeedbackRequest, record_feedback
from api.geocoding import geocode_address
from api.improve import build_improve, search_box
from api.lookup import (
    bbox_around,
    build_score_response,
    get_feature_row,
    nearest_geo_entity,
    sub_scores_from_score_row,
    with_neighborhood,
)
from api.mapdata import (
    InvalidMapRequest,
    build_cells_response,
    find_top,
    parse_bbox,
    parse_score_spec,
)
from api.metro_stats import get_stats
from api.optimize import (
    OptimizeInputError,
    OptimizeOutOfCoverage,
    OptimizeRequest,
    OptimizeResponse,
    optimize,
)
from api.places import FACTOR_CATEGORIES, places_for_factor
from api.priorities import parse_priorities
from api.reverse import ReverseUnavailable
from api.reverse import reverse as reverse_geocode
from api.schemas import (
    AnchorPoint,
    AreaExplanationResponse,
    AreaScoreResponse,
    Error,
    ExplanationResponse,
    ImproveResponse,
    IsochroneResponse,
    IsochroneShape,
    MapCellsResponse,
    MapTopResponse,
    PlacesResponse,
    RankedAddress,
    ReverseResponse,
    ScoreResponse,
    SimilarResponse,
    SourcesResponse,
    SuggestResponse,
    TriangulateRequest,
    TriangulateResponse,
)
from api.similar import build_similar, fetch_neighbours, fetch_target, overfetch_limit
from api.suggest import MIN_QUERY_LENGTH, SuggestUnavailable, in_coverage, normalize_query
from api.suggest import suggest as suggest_addresses
from api.triangulate import anchor_cells, cells_box, rank_in_cells, shape_for
from api.triangulate_sql import get_scored_candidates_in_box
from common.config import CORS_ALLOWED_ORIGINS, SCORING_WEIGHTS_VERSION

# Requests reuse one pooled connection per process (common.db.api_connection); the name
# stays `get_connection` so tests can keep patching it.
from common.db import api_connection as get_connection
from common.db import (
    get_area_aggregate,
    get_area_candidates,
    get_geo_entities_in_bbox,
    get_geo_entity_by_geohash,
    get_geo_entity_by_id,
    get_latest_score,
    get_map_cells,
    get_scored_cells_in_bbox,
)
from common.geo import encode as geohash_encode
from common.units import mi_to_km
from scoring.point import sample_points

log = logging.getLogger(__name__)

PRECISION_DOC = (
    "grid (default): the stored score of the grid cell containing the location. "
    "point: scored on demand at the exact location (an area: the mean of sample points "
    "inside it) from live place queries; falls back to grid on any error. "
    "The response's `precision` says which was served."
)

FACTORS_DOC = (
    "Comma-separated factor keys the user cares about (same keys as /map/top). "
    "Omitted means all 13 factors. Legacy keys (premiumRetail, gasStation, road, ...) are accepted as aliases."
)
WEIGHTS_DOC = "Optional importance overrides as factor:number,... (same as /map/top)."

app = FastAPI(title="BenriSpace API", version="0.5.0")

# The frontend is a separate origin (benrispace.com / localhost:3000) from
# the API (api.benrispace.com / localhost:8000), so browsers need CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=[
        "Retry-After",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
    ],
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
    precision: Literal["grid", "point"] = Query(default="grid", description=PRECISION_DOC),
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

    # A density version stores whole-area scores; its cells already carry them.
    if precision == "point" and not area_scores.is_density(SCORING_WEIGHTS_VERSION):
        try:
            with get_connection() as conn:
                result = point_score.score_points(conn, [(lat, lon)], SCORING_WEIGHTS_VERSION)[0]
            return point_score.point_score_response(result, SCORING_WEIGHTS_VERSION)
        except Exception:  # any failure serves the grid score instead
            log.warning("point scoring failed; serving grid", exc_info=True)

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

        geo_entity = with_neighborhood(conn, geo_entity)
        score_row = get_latest_score(conn, str(geo_entity["id"]), SCORING_WEIGHTS_VERSION)
        if score_row is None:
            return _error(404, "not_found", "No score on file for this geo entity yet.")
        feature_row = get_feature_row(conn, str(geo_entity["id"]))

    return build_score_response(geo_entity, score_row, feature_row)


@app.get(
    "/v1/score/{geo_entity_id}/explanation",
    response_model=ExplanationResponse,
    responses={404: {"model": Error}},
)
def get_score_explanation(
    geo_entity_id: UUID,
    factors: str | None = Query(default=None, description=FACTORS_DOC),
    weights: str | None = Query(default=None, description=WEIGHTS_DOC),
):
    try:
        priorities = parse_priorities(factors, weights)
    except InvalidMapRequest as exc:
        return _error(400, "invalid_request", str(exc))
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
        entity = None
        try:
            entity = get_geo_entity_by_id(conn, str(geo_entity_id))
        except Exception:  # noqa: BLE001 - only used for the named-places evidence
            with contextlib.suppress(Exception):
                conn.rollback()
        explanation = ai_explanation(
            conn,
            str(geo_entity_id),
            sub_scores,
            nearest_m,
            float(score_row["composite_score"]),
            "this location",
            score_row.get("weights_version") or SCORING_WEIGHTS_VERSION,
            priorities=priorities,
            lat=entity["latitude"] if entity else None,
            lon=entity["longitude"] if entity else None,
        )
    source = "ai"
    if explanation is None:
        explanation = build_explanation(
            sub_scores, nearest_m, priorities.factors if priorities.explicit else None
        )
        source = "rules"
    return ExplanationResponse(
        geo_entity_id=geo_entity_id,
        explanation=explanation,
        source=source,
        computed_at=score_row["computed_at"],
        nearest_mi=nearest_mi_by_factor(feature_row),
        priorities=priorities.factors,
    )


@app.post(
    "/v1/triangulate",
    response_model=TriangulateResponse,
    responses={400: {"model": Error}},
)
def triangulate(body: TriangulateRequest):
    from api import isochrone

    points = []
    for anchor in body.anchors:
        latlon = _resolve_anchor_latlon(anchor)
        if latlon is None:
            return _error(
                400,
                "invalid_anchor",
                f"Anchor {anchor.label!r} needs a resolvable address or lat/lon.",
            )
        points.append((anchor, *latlon))

    with get_connection() as conn:
        per_anchor = []
        for anchor, lat, lon in points:
            cells, mins, method = anchor_cells(
                conn, lat, lon, anchor.mode, anchor.max_travel_minutes
            )
            per_anchor.append((anchor, lat, lon, cells, mins, method))
        combined = isochrone.combine([p[3] for p in per_anchor], body.combine_mode)
        box = cells_box(combined)
        candidates = (
            get_scored_candidates_in_box(conn, box, SCORING_WEIGHTS_VERSION) if box else []
        )

    for c in candidates:
        c["address"] = c.get("formatted_address") or f"{c['latitude']:.5f},{c['longitude']:.5f}"
    ranked = rank_in_cells(candidates, combined, body.limit)

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
    shapes = [
        IsochroneShape(**shape_for(cells, a.label, a.mode, mins, method, lat))
        for a, lat, lon, cells, mins, method in per_anchor
    ]
    mid_lat = sum(p[1] for p in points) / len(points)
    combined_shape = IsochroneShape(
        **shape_for(
            combined,
            None,
            body.anchors[0].mode,
            min(s.minutes for s in shapes),
            "network" if all(s.method == "network" for s in shapes) else "estimate",
            mid_lat,
        )
    )
    return TriangulateResponse(results=results, isochrones=shapes, combined=combined_shape)


@app.get(
    "/v1/isochrone",
    response_model=IsochroneResponse,
    responses={400: {"model": Error}, 404: {"model": Error}},
)
def get_isochrone(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    mode: Literal["walk", "drive", "transit"] = "drive",
    minutes: int | None = Query(default=None, ge=1, le=120),
    response: Response = None,
):
    """Area reachable from a point within `minutes`, from the precomputed cell graph."""
    with get_connection() as conn:
        cells, mins, method = anchor_cells(conn, lat, lon, mode, minutes)
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return IsochroneResponse(
        latitude=lat,
        longitude=lon,
        isochrone=IsochroneShape(**shape_for(cells, None, mode, mins, method, lat)),
    )


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
        return _error(400, "invalid_request", f"q must be at least {MIN_QUERY_LENGTH} characters.")
    try:
        suggestions = suggest_addresses(q, limit)
    except SuggestUnavailable:
        return _error(
            503, "suggest_unavailable", "Address suggestions are temporarily unavailable."
        )
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
    factor: str = Query(description="Factor key, e.g. grocery, shopping, recreation, gasConvenience."),
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


def _resolve_area(lat: float, lon: float, with_aggregate: bool = True, open_conn=None):
    """Shared by /v1/area and /v1/area/explanation. Returns an error
    JSONResponse, or (area, aggregate, geo_entity, feature_row). With
    with_aggregate=False the stored grid aggregate is not fetched (aggregate is None).
    Pass `open_conn` to reuse an open connection."""
    if not in_coverage(lat, lon):
        return _error(422, "out_of_coverage", "Location is outside the covered metro area.")

    def not_found() -> JSONResponse:
        return _error(404, "area_not_found", "No road-bounded area found for this location.")

    with (
        contextlib.nullcontext(open_conn) if open_conn is not None else get_connection()
    ) as conn:
        use_slim = slim_areas.enabled()  # AREAS_TABLE=areas_slim: no stored cell scores
        if use_slim:
            area = slim_areas.find_area(conn, lat, lon)
        else:
            area = pick_area(lat, lon, usable_areas(get_area_candidates(conn, lat, lon)))
        if area is None:
            return not_found()
        aggregate = None
        if with_aggregate and area_scores.is_density(SCORING_WEIGHTS_VERSION):
            aggregate = area_scores.fetch(conn, area["id"], SCORING_WEIGHTS_VERSION)
            if aggregate is None:
                return not_found()
        elif with_aggregate and use_slim:
            samples = sample_points(area["geometry"], point_in_polygon) or [(lat, lon)]
            results = point_score.score_points(conn, samples, SCORING_WEIGHTS_VERSION)
            aggregate = point_score.area_aggregate_from_points(results, SCORING_WEIGHTS_VERSION)
            if aggregate.get("composite_score") is None:
                return not_found()
        elif with_aggregate:
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
        geo_entity = with_neighborhood(conn, geo_entity)
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
    precision: Literal["grid", "point"] = Query(default="grid", description=PRECISION_DOC),
):
    density = area_scores.is_density(SCORING_WEIGHTS_VERSION)  # stored, not sampled
    if (precision == "point" or slim_areas.enabled()) and not density:
        try:
            point_response = _area_at_point_precision(lat, lon)
            if isinstance(point_response, JSONResponse):
                return point_response
            response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
            return point_response
        except Exception:  # any failure serves the grid aggregate instead
            log.warning("point area scoring failed; serving grid", exc_info=True)
    resolved = _resolve_area(lat, lon)
    if isinstance(resolved, JSONResponse):
        return resolved
    area, aggregate, geo_entity, feature_row = resolved
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return build_area_response(
        area, aggregate, geo_entity, lat, lon, feature_row, SCORING_WEIGHTS_VERSION
    )


def _area_at_point_precision(lat: float, lon: float):
    """The area's score as the equal-weight mean of up to 5 sample points inside
    the polygon (scoring.point.sample_points), each scored on demand. Returns the
    AreaScoreResponse, or an error JSONResponse for an unknown area."""
    if slim_areas.enabled():
        return _slim_area_at_point_precision(lat, lon)
    with get_connection() as conn:
        resolved = _resolve_area(lat, lon, with_aggregate=False, open_conn=conn)
        if isinstance(resolved, JSONResponse):
            return resolved
        area, _, geo_entity, feature_row = resolved
        samples = sample_points(area["geometry"], point_in_polygon) or [(lat, lon)]
        results = point_score.score_points(conn, samples, SCORING_WEIGHTS_VERSION)
    aggregate = point_score.area_aggregate_from_points(results, SCORING_WEIGHTS_VERSION)
    built = build_area_response(
        area, aggregate, geo_entity, lat, lon, feature_row, SCORING_WEIGHTS_VERSION
    )
    return built.model_copy(update={"precision": "point"})


def _slim_area_at_point_precision(lat: float, lon: float):
    """areas_slim path with caches (api/area_cache.py) and the fewest round trips:
    area lookup (AREAS_DATABASE_URL, or the main DB), then ONE statement pipeline that
    scores every sample point AND fetches the click cell (geo_entity + feature row)."""
    if not in_coverage(lat, lon):
        return _error(422, "out_of_coverage", "Location is outside the covered metro area.")
    not_found = _error(404, "area_not_found", "No road-bounded area found for this location.")
    geohash = geohash_encode(lat, lon, precision=6)

    area = area_cache.POINT_AREA.get(area_cache.point_key(lat, lon))
    aggregate = cell = None
    with contextlib.ExitStack() as stack:
        conn = None

        def main_conn():
            nonlocal conn
            if conn is None:
                conn = stack.enter_context(get_connection())
            return conn

        if area is None:
            if slim_areas.has_own_database():
                area = slim_areas.find_area(None, lat, lon)
            else:
                area = slim_areas.find_area(main_conn(), lat, lon)
            if area is None:
                return not_found
            area_cache.POINT_AREA.put(area_cache.point_key(lat, lon), area)
        skey = area_cache.scores_key(area["id"], SCORING_WEIGHTS_VERSION)
        aggregate = area_cache.AREA_SCORES.get(skey)
        cell = area_cache.CELLS.get(geohash)
        if aggregate is None:
            samples = sample_points(area["geometry"], point_in_polygon) or [(lat, lon)]
            results, cells = point_score.score_points_cells(
                main_conn(), samples, SCORING_WEIGHTS_VERSION, extra_geohashes=(geohash,)
            )
            aggregate = area_cache.AREA_SCORES.put(
                skey, point_score.area_aggregate_from_points(results, SCORING_WEIGHTS_VERSION)
            )
            if cell is None and geohash in cells:
                cell = area_cache.CELLS.put(geohash, cells[geohash])
        if aggregate.get("composite_score") is None:
            return not_found
        if cell is None:  # scores were cached but the click cell was not
            cell = point_score.fetch_cell(main_conn(), lat, lon, geohash)
            if cell is None:
                return not_found
            area_cache.CELLS.put(geohash, cell)
    built = build_area_response(area, aggregate, cell, lat, lon, cell, SCORING_WEIGHTS_VERSION)
    return built.model_copy(update={"precision": "point"})


@app.get(
    "/v1/area/explanation",
    response_model=AreaExplanationResponse,
    responses={400: {"model": Error}, 404: {"model": Error}, 422: {"model": Error}},
)
def get_area_explanation(
    response: Response,
    lat: float = Query(ge=-90, le=90, description="Latitude."),
    lon: float = Query(ge=-180, le=180, description="Longitude."),
    factors: str | None = Query(default=None, description=FACTORS_DOC),
    weights: str | None = Query(default=None, description=WEIGHTS_DOC),
):
    """AI-written explanation for the area under a point; rule-based text when
    the LLM layer is unavailable. Kept separate from /v1/area so that stays fast."""
    try:
        priorities = parse_priorities(factors, weights)
    except InvalidMapRequest as exc:
        return _error(400, "invalid_request", str(exc))
    resolved = _resolve_area(lat, lon)
    if isinstance(resolved, JSONResponse):
        return resolved
    area, aggregate, geo_entity, feature_row = resolved
    neighborhood = area.get("neighborhood") or (geo_entity or {}).get("neighborhood")
    sub_scores = sub_scores_from_score_row(aggregate)
    nearest_m = nearest_m_by_factor(feature_row)
    with get_connection() as conn:
        text = ai_explanation(
            conn,
            f"area:{area['id']}",
            sub_scores,
            nearest_m,
            float(aggregate["composite_score"]),
            neighborhood or bounded_by_text(list(area.get("bounded_by") or [])),
            aggregate.get("weights_version") or SCORING_WEIGHTS_VERSION,
            priorities=priorities,
            lat=lat,
            lon=lon,
        )
    source = "ai"
    if text is None:
        text = area_explanation(
            sub_scores, feature_row, priorities.factors if priorities.explicit else None
        )
        source = "rules"
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return AreaExplanationResponse(
        explanation=text,
        source=source,
        area_id=area["id"],
        priorities=priorities.factors,
        neighborhood=neighborhood,
    )


@app.get(
    "/v1/improve",
    response_model=ImproveResponse,
    responses={400: {"model": Error}, 404: {"model": Error}, 422: {"model": Error}},
)
def get_improve(
    response: Response,
    lat: float = Query(ge=-90, le=90, description="Latitude."),
    lon: float = Query(ge=-180, le=180, description="Longitude."),
    radius_mi: float = Query(default=1.0, gt=0, le=3, alias="radiusMi"),
    max_suggestions: int = Query(default=3, ge=1, le=5, alias="maxSuggestions"),
    factors: str | None = Query(default=None, description=FACTORS_DOC),
    weights: str | None = Query(default=None, description=WEIGHTS_DOC),
):
    """Deterministic suggestions for the weakest selected place-based factors."""
    try:
        priorities = parse_priorities(factors, weights)
    except InvalidMapRequest as exc:
        return _error(400, "invalid_request", str(exc))
    resolved = _resolve_area(lat, lon)
    base_row = None
    if isinstance(resolved, JSONResponse):
        if resolved.status_code != 404:
            return resolved
        # No road-bounded area here: fall back to the grid cell's own score row.
        with get_connection() as conn:
            geo_entity = get_geo_entity_by_geohash(conn, geohash_encode(lat, lon, precision=6))
            if geo_entity is None:
                min_lat, max_lat, min_lon, max_lon = bbox_around(lat, lon)
                geo_entity = nearest_geo_entity(
                    lat, lon, get_geo_entities_in_bbox(conn, min_lat, max_lat, min_lon, max_lon)
                )
            if geo_entity is not None:
                base_row = get_latest_score(conn, str(geo_entity["id"]), SCORING_WEIGHTS_VERSION)
        if base_row is None:
            return resolved
    else:
        base_row = resolved[1]
    sub_scores = sub_scores_from_score_row(base_row).model_dump(by_alias=True)
    composite = float(base_row["composite_score"])
    box = search_box(lat, lon, radius_mi)
    with get_connection() as conn:
        cells = get_scored_cells_in_bbox(conn, *box, SCORING_WEIGHTS_VERSION)
        result = build_improve(
            conn, lat, lon, radius_mi, max_suggestions, sub_scores, composite, cells,
            geohash_encode(lat, lon, precision=6), priorities,
        )  # fmt: skip
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return result


@app.get(
    "/v1/similar",
    response_model=SimilarResponse,
    responses={400: {"model": Error}, 404: {"model": Error}, 422: {"model": Error}},
)
def get_similar(
    response: Response,
    lat: float = Query(ge=-90, le=90, description="Latitude."),
    lon: float = Query(ge=-180, le=180, description="Longitude."),
    k: int = Query(default=5, ge=1, le=10),
    min_separation_mi: float = Query(default=1.0, ge=0, le=10, alias="minSeparationMi"),
    factors: str | None = Query(default=None, description=FACTORS_DOC),
    weights: str | None = Query(default=None, description=WEIGHTS_DOC),
):
    """Areas with a similar factor profile, spread out geographically."""
    try:
        priorities = parse_priorities(factors, weights)
    except InvalidMapRequest as exc:
        return _error(400, "invalid_request", str(exc))
    if not in_coverage(lat, lon):
        return _error(422, "out_of_coverage", "Location is outside the covered metro area.")
    with get_connection() as conn:
        geo_entity = get_geo_entity_by_geohash(conn, geohash_encode(lat, lon, precision=6))
        if geo_entity is None:
            min_lat, max_lat, min_lon, max_lon = bbox_around(lat, lon)
            geo_entity = nearest_geo_entity(
                lat, lon, get_geo_entities_in_bbox(conn, min_lat, max_lat, min_lon, max_lon)
            )
        target = (
            fetch_target(conn, str(geo_entity["id"]), SCORING_WEIGHTS_VERSION)
            if geo_entity
            else None
        )
        if target is None:
            return _error(404, "not_found", "No similarity data for this location yet.")
        candidates = fetch_neighbours(
            conn,
            str(geo_entity["id"]),
            SCORING_WEIGHTS_VERSION,
            geo_entity["metro_area"],
            overfetch_limit(k, wide=priorities.explicit),
        )
        stats = (
            get_stats(conn, SCORING_WEIGHTS_VERSION, geo_entity["metro_area"])
            if priorities.explicit
            else None
        )
        result = build_similar(
            conn, lat, lon, target, candidates, k, min_separation_mi, priorities, stats
        )
    response.headers["Cache-Control"] = CACHE_CONTROL_5_MIN
    return result


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


@app.post(
    "/v1/optimize",
    response_model=OptimizeResponse,
    responses={400: {"model": Error}, 422: {"model": Error}},
)
def post_optimize(body: OptimizeRequest):
    try:
        with get_connection() as conn:
            return optimize(conn, body)
    except OptimizeInputError as exc:
        return _error(400, "invalid_request", str(exc))
    except OptimizeOutOfCoverage as exc:
        return _error(422, "out_of_coverage", str(exc))


@app.post(
    "/v1/chat",
    response_model=ChatResponse,
    response_model_exclude_none=True,
    responses={400: {"model": Error}, 429: {"model": Error}, 503: {"model": Error}},
)
def post_chat(body: ChatRequest, request: Request):
    """Ask Benri: a tool-using assistant grounded in our own data."""
    try:
        return handle_chat(
            body,
            request.headers.get("x-forwarded-for"),
            request.client.host if request.client else None,
        )
    except ChatHttpError as exc:
        return _error(exc.status, exc.code, exc.message)


@app.post(
    "/v1/chat/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-sent events."}},
)
def post_chat_stream(body: ChatRequest, request: Request):
    """POST /v1/chat as server-sent events: `status` frames, then one `reply` or `error`."""
    return StreamingResponse(
        stream_chat(
            body,
            request.headers.get("x-forwarded-for"),
            request.client.host if request.client else None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get(
    "/v1/map/scores",
    responses={304: {"description": "Not modified"}, 404: {"model": Error}},
    response_class=Response,
)
def get_map_scores(request: Request, version: str | None = Query(default=None)):
    """Every cell's 13 sub-scores as a compact binary file (format: docs/api.md)."""
    if version is not None and version != SCORING_WEIGHTS_VERSION:
        return _error(404, "not_found", f"Unknown weights version {version!r}.")
    with get_connection() as conn:
        stamp = scorefile.current_stamp(conn, SCORING_WEIGHTS_VERSION)
        etag = scorefile.make_etag(SCORING_WEIGHTS_VERSION, stamp)
        headers = {
            "Cache-Control": "public, max-age=86400",
            "ETag": etag,
            "Vary": "Accept-Encoding",
        }
        if stamp is not None and request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        built = scorefile.build(conn, SCORING_WEIGHTS_VERSION, stamp)
    if built is None:
        return _error(404, "not_found", "No scores for this weights version yet.")
    if "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        body = built.gzipped
    else:
        body = built.body
    return Response(content=body, media_type="application/octet-stream", headers=headers)


@app.get("/v1/sources", response_model=SourcesResponse)
def get_sources(response: Response):
    """Data sources behind the scores, with licences and freshness."""
    with get_connection() as conn:
        runs = sources.freshness(conn)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return {"sources": sources.build_sources(runs)}


@app.post(
    "/v1/feedback",
    status_code=204,
    responses={429: {"model": Error}},
)
def post_feedback(body: FeedbackRequest, request: Request):
    """Thumbs / reports on summaries, chat answers and places."""
    stored = record_feedback(
        body,
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
    )
    if not stored:
        return _error(429, "rate_limited", "Too much feedback today. Thank you.")
    return Response(status_code=204)
