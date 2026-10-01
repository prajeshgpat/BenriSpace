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
    gas_station: float | None = None
    convenience_store: float | None = None
    transit: float | None = None
    school: float | None = None
    road: float | None = None
    emergency_corridor: float | None = None
    airport: float | None = None
    trail_popularity: float | None = None


class ScoreResponse(CamelModel):
    geo_entity_id: UUID
    address: str
    latitude: float
    longitude: float
    composite_score: float
    sub_scores: SubScores
    weights_version: str
    computed_at: datetime


class ExplanationResponse(CamelModel):
    geo_entity_id: UUID
    explanation: str
    computed_at: datetime


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


class TriangulateResponse(CamelModel):
    results: list[RankedAddress]
