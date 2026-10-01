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

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.explain import build_explanation
from api.geocoding import geocode_address
from api.lookup import (
    bbox_around,
    build_score_response,
    nearest_geo_entity,
    sub_scores_from_score_row,
)
from api.schemas import (
    AnchorPoint,
    Error,
    ExplanationResponse,
    RankedAddress,
    ScoreResponse,
    TriangulateRequest,
    TriangulateResponse,
)
from api.triangulate import anchor_to_circle, rank_candidates
from common.config import CORS_ALLOWED_ORIGINS
from common.db import (
    get_connection,
    get_geo_entities_in_bbox,
    get_geo_entity_by_geohash,
    get_latest_score,
    iter_latest_scored_geo_entities,
)
from common.geo import encode as geohash_encode

app = FastAPI(title="BenriSpace API", version="0.3.1")

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

        score_row = get_latest_score(conn, str(geo_entity["id"]))
        if score_row is None:
            return _error(404, "not_found", "No score on file for this geo entity yet.")

    return build_score_response(geo_entity, score_row)


@app.get(
    "/v1/score/{geo_entity_id}/explanation",
    response_model=ExplanationResponse,
    responses={404: {"model": Error}},
)
def get_score_explanation(geo_entity_id: UUID):
    with get_connection() as conn:
        score_row = get_latest_score(conn, str(geo_entity_id))
    if score_row is None:
        return _error(404, "not_found", "No score on file for this geo entity.")

    sub_scores = sub_scores_from_score_row(score_row)
    explanation = build_explanation(sub_scores)  # Phase 1 template placeholder, see api/explain.py
    return ExplanationResponse(
        geo_entity_id=geo_entity_id,
        explanation=explanation,
        computed_at=score_row["computed_at"],
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
        candidates = [dict(row) for row in iter_latest_scored_geo_entities(conn)]

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
