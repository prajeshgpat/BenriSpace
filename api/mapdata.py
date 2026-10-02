"""Query parsing and result shaping for GET /v1/map/cells and /v1/map/top.

Pure functions over strings and dicts (the SQL itself lives in common/db.py).
"""

import math
import re
from dataclasses import dataclass

from api.lookup import sub_scores_from_score_row
from api.schemas import MapCellsResponse, MapTopResponse, MapTopResult
from common.config import SCORING_WEIGHTS_VERSION
from common.db import MapBbox, get_map_top_candidates
from common.geo import haversine_m
from scoring.engine import DEFAULT_WEIGHTS, UNDERLYING_SCORE_COLUMNS

# Wire factor key -> `scores` column. The only place that maps them; ordering
# is the contract's FactorKey order. tests/test_mapdata.py fails if a scored
# category is added to scoring.engine.CATEGORY_SPECS without a row here.
FACTOR_COLUMNS: dict[str, str] = {
    "grocery": "grocery_score",
    "gym": "gym_score",
    "cafe": "cafe_score",
    "restaurant": "restaurant_score",
    "bar": "bar_score",
    "premiumRetail": "premium_retail_score",
    "gasStation": "gas_station_score",
    "convenienceStore": "convenience_store_score",
    "transit": "transit_score",
    "school": "school_score",
    "road": "road_score",
    "emergencyCorridor": "emergency_corridor_score",
    "airport": "airport_score",
    "trailPopularity": "trail_popularity_score",
}

# API keys of underlying metrics: they count toward the composite (an omitted
# `factors` means all 14) but the website offers no toggle for them.
UNDERLYING_FACTOR_KEYS: tuple[str, ...] = tuple(
    key
    for key, column in FACTOR_COLUMNS.items()
    if column in UNDERLYING_SCORE_COLUMNS
)

MAX_WEIGHT = 1_000_000.0
SCORE_DECIMALS = 1
COORD_DECIMALS = 5

TOP_POOL_STEPS = (600, 6000, 60000)


class InvalidMapRequest(ValueError):
    """Bad factors/weights/bbox; the route turns it into a 400 invalid_request."""


@dataclass(frozen=True)
class ScoreSpec:
    factors: list[str]
    weights: dict[str, float]

    @property
    def columns_weights(self) -> list[tuple[str, float]]:
        return [(FACTOR_COLUMNS[f], self.weights[f]) for f in self.factors]


_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def parse_bbox(raw: str) -> MapBbox:
    """`minLon,minLat,maxLon,maxLat` -> tuple; raises InvalidMapRequest."""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise InvalidMapRequest("bbox must be minLon,minLat,maxLon,maxLat")
    values = []
    for part in parts:
        if not _NUMBER.fullmatch(part):
            raise InvalidMapRequest(f"bbox has a non-numeric value: {part!r}")
        values.append(float(part))
    min_lon, min_lat, max_lon, max_lat = values
    if not all(math.isfinite(v) for v in values):
        raise InvalidMapRequest("bbox values must be finite numbers")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise InvalidMapRequest("bbox latitudes must be between -90 and 90")
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise InvalidMapRequest("bbox longitudes must be between -180 and 180")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise InvalidMapRequest(
            "bbox is empty or inverted: need minLon < maxLon and minLat < maxLat"
        )
    return min_lon, min_lat, max_lon, max_lat


def parse_factors(raw: str | None) -> list[str]:
    """Comma-separated FactorKeys; None = all. Returned in contract order."""
    if raw is None:
        return list(FACTOR_COLUMNS)
    requested = set()
    for part in raw.split(","):
        key = part.strip()
        if not key:
            raise InvalidMapRequest(
                "factors must be a non-empty comma-separated list with no blank entries"
            )
        if key not in FACTOR_COLUMNS:
            raise InvalidMapRequest(
                f"unknown factor {key!r}; valid factors: {', '.join(FACTOR_COLUMNS)}"
            )
        requested.add(key)
    return [f for f in FACTOR_COLUMNS if f in requested]


def parse_weights(raw: str | None, factors: list[str]) -> dict[str, float]:
    """Effective weight per included factor: defaults, then overrides from
    `factor:number,...` (overrides for factors not included are ignored, but
    must still be well formed)."""
    weights = {f: DEFAULT_WEIGHTS[FACTOR_COLUMNS[f]] for f in factors}
    if raw is None:
        return weights
    seen: set[str] = set()
    for part in raw.split(","):
        key, sep, value = part.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value:
            raise InvalidMapRequest(f"weights entries must look like factor:number, got {part!r}")
        if key not in FACTOR_COLUMNS:
            raise InvalidMapRequest(
                f"unknown factor {key!r} in weights; valid factors: {', '.join(FACTOR_COLUMNS)}"
            )
        if key in seen:
            raise InvalidMapRequest(f"weight for {key!r} given more than once")
        seen.add(key)
        if not _NUMBER.fullmatch(value):
            raise InvalidMapRequest(f"weight for {key!r} is not a number: {value!r}")
        number = float(value)
        if not math.isfinite(number) or number <= 0 or number > MAX_WEIGHT:
            raise InvalidMapRequest(
                f"weight for {key!r} must be greater than 0 and at most {MAX_WEIGHT:g}"
            )
        if key in weights:
            weights[key] = number
    return weights


def parse_score_spec(factors: str | None, weights: str | None) -> ScoreSpec:
    used = parse_factors(factors)
    return ScoreSpec(used, parse_weights(weights, used))


def composite_from_row(row: dict, spec: ScoreSpec) -> float | None:
    """Reference implementation of the SQL composite for a `scores` row dict:
    same arithmetic as scoring.engine.compute_composite, over the selected
    factors' non-null sub-scores; None when all are null."""
    total = 0.0
    weighted = 0.0
    for f in spec.factors:
        value = row.get(FACTOR_COLUMNS[f])
        if value is None:
            continue
        weighted += spec.weights[f] * float(value)
        total += spec.weights[f]
    return weighted / total if total else None


def build_cells_response(
    rows: list[dict], spec: ScoreSpec, precision: int, limit: int
) -> MapCellsResponse:
    """`rows` is get_map_cells' output fetched with limit + 1."""
    truncated = len(rows) > limit
    rows = rows[:limit]
    return MapCellsResponse(
        precision=precision,
        factors=spec.factors,
        weights=spec.weights,
        weights_version=SCORING_WEIGHTS_VERSION,
        count=len(rows),
        truncated=truncated,
        geohashes=[r["geohash"] for r in rows],
        scores=[round(float(r["score"]), SCORE_DECIMALS) for r in rows],
    )


def select_separated(candidates: list[dict], limit: int, min_separation_km: float) -> list[dict]:
    """Greedy: candidates are best-first; keep each one that is at least
    min_separation_km from everything kept so far."""
    min_m = min_separation_km * 1000.0
    kept: list[dict] = []
    for c in candidates:
        if all(
            haversine_m(c["latitude"], c["longitude"], k["latitude"], k["longitude"]) >= min_m
            for k in kept
        ):
            kept.append(c)
            if len(kept) == limit:
                break
    return kept


def build_top_response(
    candidates: list[dict], spec: ScoreSpec, limit: int, min_separation_km: float
) -> MapTopResponse:
    chosen = select_separated(candidates, limit, min_separation_km)
    return MapTopResponse(
        factors=spec.factors,
        weights=spec.weights,
        weights_version=SCORING_WEIGHTS_VERSION,
        results=[
            MapTopResult(
                geohash=c["geohash"],
                latitude=round(c["latitude"], COORD_DECIMALS),
                longitude=round(c["longitude"], COORD_DECIMALS),
                score=round(float(c["score"]), SCORE_DECIMALS),
                metro_area=c["metro_area"],
                sub_scores=sub_scores_from_score_row(c),
            )
            for c in chosen
        ],
    )


def find_top(
    conn, spec: ScoreSpec, bbox: MapBbox | None, limit: int, min_separation_km: float
) -> MapTopResponse:
    """Widens the SQL candidate pool until `limit` separated areas are found
    or the pool covers every scored cell in the area (dense clusters of
    near-identical top cells would otherwise starve the result)."""
    candidates: list[dict] = []
    for pool in TOP_POOL_STEPS:
        candidates = get_map_top_candidates(
            conn, spec.columns_weights, SCORING_WEIGHTS_VERSION, bbox, pool
        )
        enough = len(select_separated(candidates, limit, min_separation_km)) == limit
        if enough or len(candidates) < pool:
            break
    return build_top_response(candidates, spec, limit, min_separation_km)
