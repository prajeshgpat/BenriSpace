"""Pydantic response/request models for contracts/openapi.yaml.

Field names are snake_case in Python but serialize as the contract's exact
camelCase (geoEntityId, compositeScore, weightsVersion, ...) via
`alias_generator=to_camel` on `CamelModel`. `populate_by_name=True` lets
call sites in this codebase construct models with snake_case keyword args;
FastAPI's default `response_model_by_alias=True` handles serialization back
to camelCase on the wire, so nothing extra is needed in route handlers.

Only the schemas actually used by the three implemented endpoints (score,
explanation, triangulate) are defined here -- the `security`/`401`/`429`/
rate-limit-header parts of openapi.yaml are Phase 4 and intentionally not
modeled yet (see api/main.py's module docstring).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Error(CamelModel):
    code: str
    message: str
    upgrade_url: str | None = None


class SubScores(CamelModel):
    """Normalized 0-100 sub-scores, direction already applied (higher is
    always better) -- matches openapi.yaml's SubScores description and the
    `scores` table columns via scoring.engine.CATEGORY_SPECS."""

    grocery: float | None = None
    gym: float | None = None
    cafe: float | None = None
    restaurant: float | None = None
    bar: float | None = None
    shopping: float | None = None
    gas_convenience: float | None = None
    transit: float | None = None
    school: float | None = None
    traffic: float | None = None
    emergency_corridor: float | None = None
    airport: float | None = None
    recreation: float | None = None


class SchoolInfo(CamelModel):
    """School detail beside the (rating-gated) `school` sub-score: proximity
    is shown even when no rating exists, so the UI can say 'proximity 72,
    rating unavailable'."""

    proximity: float | None = None
    rating_available: bool = False
    district_name: str | None = None
    source: str | None = None


class ScoreResponse(CamelModel):
    geo_entity_id: UUID
    address: str
    latitude: float
    longitude: float
    composite_score: float
    sub_scores: SubScores
    weights_version: str
    computed_at: datetime
    school: SchoolInfo | None = None
    # Human name such as 'Park Slope, Brooklyn'; null when not labelled.
    neighborhood: str | None = None
    # 'point' when scored on demand at the exact location (?precision=point),
    # 'grid' when it is the stored score of the containing grid cell (default).
    precision: Literal["point", "grid"] = "grid"
    # How people here usually get around, from population density: 'walk' at
    # 10,000+ people / sq mi, else 'drive'. Null when density is unknown.
    travel_mode: Literal["walk", "drive"] | None = None


class ExplanationResponse(CamelModel):
    geo_entity_id: UUID
    explanation: str
    computed_at: datetime
    # Nearest feature per factor in miles (FactorKey -> miles | null).
    nearest_mi: dict[str, float | None] | None = None
    # 'ai' when written by the LLM layer, 'rules' for the rule-based text.
    source: Literal["ai", "rules"] | None = None
    priorities: list[str] = []


class AreaExplanationResponse(CamelModel):
    explanation: str
    source: Literal["ai", "rules"]
    area_id: int | None = None
    priorities: list[str] = []
    neighborhood: str | None = None


class AnchorPoint(CamelModel):
    label: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    max_travel_minutes: int | None = None
    mode: Literal["drive", "transit", "walk"] = "drive"


class TriangulateRequest(CamelModel):
    anchors: list[AnchorPoint] = Field(min_length=1, max_length=4)
    combine_mode: Literal["intersect", "union"] = "intersect"
    limit: int = 50


class RankedAddress(CamelModel):
    geo_entity_id: UUID
    address: str
    latitude: float
    longitude: float
    composite_score: float


class IsochroneShape(CamelModel):
    """A reachable area as GeoJSON (MultiPolygon, lon/lat). method is "network" when it comes
    from the precomputed road-network cell graph, "estimate" for the straight-line fallback."""

    label: str | None = None
    mode: Literal["drive", "transit", "walk"]
    minutes: int
    method: Literal["network", "estimate"]
    cell_count: int
    area_sq_mi: float
    geometry: dict | None = None


class IsochroneResponse(CamelModel):
    latitude: float
    longitude: float
    isochrone: IsochroneShape


class TriangulateResponse(CamelModel):
    results: list[RankedAddress]
    isochrones: list[IsochroneShape] = []
    combined: IsochroneShape | None = None


class Suggestion(CamelModel):
    label: str
    latitude: float
    longitude: float


class SuggestResponse(CamelModel):
    suggestions: list[Suggestion]


class ReverseResponse(CamelModel):
    label: str | None
    latitude: float
    longitude: float


class MapCellsResponse(CamelModel):
    precision: int
    factors: list[str]
    weights: dict[str, float]
    weights_version: str
    count: int
    truncated: bool
    geohashes: list[str]
    scores: list[float]


class MapTopResult(CamelModel):
    geohash: str
    latitude: float
    longitude: float
    score: float
    metro_area: str
    sub_scores: SubScores
    neighborhood: str | None = None


class MapTopResponse(CamelModel):
    factors: list[str]
    weights: dict[str, float]
    weights_version: str
    results: list[MapTopResult]


class AreaInfo(CamelModel):
    # GeoJSON Polygon or MultiPolygon in [lon, lat].
    geometry: dict
    area_sq_mi: float
    bounded_by: list[str]
    cell_count: int


class AreaScoreResponse(ScoreResponse):
    area_id: int
    area: AreaInfo
    explanation: str


class PlaceOut(CamelModel):
    name: str
    brand: str | None = None
    category: str
    distance_mi: float
    distance_label: str | None
    direction: str
    latitude: float
    longitude: float


class PlacesResponse(CamelModel):
    factor: str
    radius_mi: float
    places: list[PlaceOut]


class ImprovePlace(CamelModel):
    name: str
    brand: str | None = None
    distance_mi: float
    distance_label: str | None
    direction: str
    latitude: float
    longitude: float


class BetterArea(CamelModel):
    latitude: float
    longitude: float
    direction: str
    distance_mi: float
    distance_label: str | None
    factor_score: int
    factor_gain: int
    composite_score: int
    composite_gain: int
    neighborhood: str | None = None


class ImproveSuggestion(CamelModel):
    factor: str
    label: str
    score: int
    places: list[ImprovePlace]
    better_area: BetterArea | None = None
    tip: str


class BestNearby(CamelModel):
    latitude: float
    longitude: float
    direction: str
    distance_label: str | None
    composite_score: int
    composite_gain: int
    neighborhood: str | None = None


class ImproveResponse(CamelModel):
    composite: float
    radius_mi: float
    suggestions: list[ImproveSuggestion]
    best_nearby: BestNearby | None = None
    # Factor keys used (the request's `factors`, or the 13 factors).
    priorities: list[str] = []


class SimilarDifference(CamelModel):
    factor: str
    label: str
    delta: int


class SimilarArea(CamelModel):
    latitude: float
    longitude: float
    direction: str
    distance_label: str | None
    similarity: int
    composite_score: int
    area_label: str | None = None
    neighborhood: str | None = None
    differences: list[SimilarDifference]
    summary: str


class SimilarResponse(CamelModel):
    min_separation_mi: float
    results: list[SimilarArea]
    priorities: list[str] = []


class DataSource(CamelModel):
    id: str
    name: str
    feeds: str
    license: str
    url: str
    last_updated: datetime | None = None
    rows_affected: int | None = None


class SourcesResponse(CamelModel):
    sources: list[DataSource]
