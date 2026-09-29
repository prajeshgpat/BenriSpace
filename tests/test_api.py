"""Tests for api/. No live Postgres in this sandbox (see task notes), so:

- api.main's app object is tested only for import/construction (no DB
  touched at import time) and route registration.
- The interesting logic -- geohash lookup/fallback, template explanation
  generation, and the Phase 1 isochrone-circle placeholder math -- is
  pure/DB-free and tested directly, same style as
  tests/test_scoring_engine.py.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from api.explain import build_explanation
from api.lookup import (
    bbox_around,
    build_score_response,
    nearest_geo_entity,
    sub_scores_from_score_row,
)
from api.schemas import ScoreResponse, SubScores
from api.triangulate import anchor_to_circle, point_in_circle, rank_candidates

# --- App construction (DB-free) -------------------------------------------


def test_app_imports_and_constructs_without_a_db():
    from api.main import app

    assert app.title == "BenriSpace API"


def test_app_registers_the_three_contract_routes():
    from api.main import app

    paths = {route.path for route in app.routes}
    assert "/v1/score" in paths
    assert "/v1/score/{geo_entity_id}/explanation" in paths
    assert "/v1/triangulate" in paths


def test_openapi_schema_generation_does_not_touch_a_db():
    # Building the OpenAPI schema exercises every route's type
    # annotations/response models -- a good DB-free smoke test that the
    # Pydantic schemas are well-formed.
    from api.main import app

    schema = app.openapi()
    assert "/v1/score" in schema["paths"]


# --- api.lookup (GET /score pure logic) ------------------------------------


def test_bbox_around_is_symmetric_and_bounded():
    min_lat, max_lat, min_lon, max_lon = bbox_around(40.7, -73.9, margin_deg=0.02)
    assert min_lat == pytest.approx(40.68)
    assert max_lat == pytest.approx(40.72)
    assert min_lon == pytest.approx(-73.92)
    assert max_lon == pytest.approx(-73.88)


def test_nearest_geo_entity_picks_the_closest_candidate():
    candidates = [
        {"id": "far", "latitude": 41.0, "longitude": -74.5},
        {"id": "near", "latitude": 40.71, "longitude": -73.99},
        {"id": "farther", "latitude": 39.0, "longitude": -76.0},
    ]
    nearest = nearest_geo_entity(40.70, -74.00, candidates)
    assert nearest["id"] == "near"


def test_nearest_geo_entity_empty_candidates_returns_none():
    assert nearest_geo_entity(40.7, -73.9, []) is None


def test_sub_scores_from_score_row_maps_columns_to_fields():
    row = {
        "grocery_score": 80.0,
        "gym_score": 40.0,
        "gas_station_score": 90.0,
        "airport_score": None,
    }
    sub = sub_scores_from_score_row(row)
    assert sub.grocery == 80.0
    assert sub.gym == 40.0
    assert sub.gas_station == 90.0
    assert sub.airport is None
    # Categories absent from the row should also come through as None,
    # not raise.
    assert sub.school is None


def test_build_score_response_shape_and_camelcase_serialization():
    geo_entity = {
        "id": uuid4(),
        "latitude": 40.7128,
        "longitude": -74.0060,
        "formatted_address": "123 Main St, New York, NY",
    }
    score_row = {
        "composite_score": 72.5,
        "weights_version": "v1-handtuned",
        "computed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "grocery_score": 80.0,
        "gas_station_score": 90.0,
    }
    resp = build_score_response(geo_entity, score_row)
    assert isinstance(resp, ScoreResponse)
    assert resp.address == "123 Main St, New York, NY"
    assert resp.composite_score == 72.5

    dumped = resp.model_dump(by_alias=True, mode="json")
    assert dumped["geoEntityId"] == str(geo_entity["id"])
    assert dumped["compositeScore"] == 72.5
    assert dumped["weightsVersion"] == "v1-handtuned"
    assert dumped["subScores"]["gasStation"] == 90.0


def test_build_score_response_falls_back_to_latlon_when_no_formatted_address():
    geo_entity = {"id": uuid4(), "latitude": 40.5, "longitude": -73.5, "formatted_address": None}
    score_row = {
        "composite_score": 50.0,
        "weights_version": "v1-handtuned",
        "computed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    resp = build_score_response(geo_entity, score_row)
    assert resp.address == "40.50000,-73.50000"


# --- api.explain (Phase 1 template placeholder) ----------------------------


def test_build_explanation_calls_out_best_and_worst():
    sub = SubScores(grocery=90, gym=10, cafe=50)
    text = build_explanation(sub)
    assert "grocery access" in text
    assert "90/100" in text
    assert "gym access" in text
    assert "10/100" in text


def test_build_explanation_mentions_other_factors():
    sub = SubScores(grocery=90, gym=10, cafe=50, transit=70)
    text = build_explanation(sub)
    assert "Other factors" in text
    assert "cafe access" in text
    assert "transit access" in text


def test_build_explanation_handles_all_none():
    text = build_explanation(SubScores())
    assert "No sub-score breakdown" in text


def test_build_explanation_single_value_no_duplicate_best_worst_sentence():
    sub = SubScores(grocery=42)
    text = build_explanation(sub)
    assert text.count("grocery access") == 1
    assert "weakest" not in text


# --- api.triangulate (Phase 1 straight-line-circle placeholder) -----------


def test_anchor_to_circle_uses_mode_speed_and_minutes():
    circle = anchor_to_circle(40.0, -73.0, max_travel_minutes=30, mode="walk")
    # 4.8 km/h -> 80 m/min -> 30 min -> 2400 m
    assert circle.radius_m == 2400.0


def test_anchor_to_circle_defaults_when_minutes_and_mode_omitted():
    circle = anchor_to_circle(40.0, -73.0, max_travel_minutes=None, mode=None)
    # default mode "drive" (40 km/h) x default 20 minutes
    assert circle.radius_m == (40.0 * 1000 / 60) * 20


def test_point_in_circle_true_for_center_false_far_away():
    circle = anchor_to_circle(40.7128, -74.0060, max_travel_minutes=10, mode="walk")
    assert point_in_circle(40.7128, -74.0060, circle) is True
    assert point_in_circle(41.5, -75.0, circle) is False


def test_rank_candidates_intersect_requires_all_circles():
    # Point A is within both circles, point B is within only circle 1.
    circle1 = anchor_to_circle(40.0, -73.0, 60, "drive")  # big radius
    circle2 = anchor_to_circle(40.0001, -73.0001, 5, "walk")  # tiny radius, same spot

    candidates = [
        {"geo_entity_id": "a", "latitude": 40.0001, "longitude": -73.0001, "composite_score": 60},
        {"geo_entity_id": "b", "latitude": 40.05, "longitude": -73.05, "composite_score": 90},
    ]
    ranked = rank_candidates(candidates, [circle1, circle2], combine_mode="intersect", limit=50)
    assert [c["geo_entity_id"] for c in ranked] == ["a"]


def test_rank_candidates_union_allows_any_circle_and_sorts_by_score():
    circle1 = anchor_to_circle(40.0, -73.0, 60, "drive")
    circle2 = anchor_to_circle(50.0, -80.0, 60, "drive")  # far away, no candidates near it

    candidates = [
        {"geo_entity_id": "low", "latitude": 40.001, "longitude": -73.001, "composite_score": 30},
        {"geo_entity_id": "high", "latitude": 40.002, "longitude": -73.002, "composite_score": 90},
    ]
    ranked = rank_candidates(candidates, [circle1, circle2], combine_mode="union", limit=50)
    assert [c["geo_entity_id"] for c in ranked] == ["high", "low"]


def test_rank_candidates_respects_limit():
    circle = anchor_to_circle(40.0, -73.0, 120, "drive")
    candidates = [
        {"geo_entity_id": str(i), "latitude": 40.0001, "longitude": -73.0001, "composite_score": i}
        for i in range(10)
    ]
    ranked = rank_candidates(candidates, [circle], combine_mode="intersect", limit=3)
    assert len(ranked) == 3
    assert [c["composite_score"] for c in ranked] == [9, 8, 7]
