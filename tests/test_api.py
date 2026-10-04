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
        "gas_convenience_score": 90.0,
        "road_score": 33.0,
        "airport_score": None,
    }
    sub = sub_scores_from_score_row(row)
    assert sub.grocery == 80.0
    assert sub.gym == 40.0
    assert sub.gas_convenience == 90.0
    assert sub.traffic == 33.0
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
        "gas_convenience_score": 90.0,
    }
    resp = build_score_response(geo_entity, score_row)
    assert isinstance(resp, ScoreResponse)
    assert resp.address == "123 Main St, New York, NY"
    assert resp.composite_score == 72.5

    dumped = resp.model_dump(by_alias=True, mode="json")
    assert dumped["geoEntityId"] == str(geo_entity["id"])
    assert dumped["compositeScore"] == 72.5
    assert dumped["weightsVersion"] == "v1-handtuned"
    assert dumped["subScores"]["gasConvenience"] == 90.0


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


# --- Contract conformance (bugs found when the frontend first consumed the API)


def test_sub_scores_model_has_a_field_for_every_scored_category():
    # trail_popularity_score was computed and stored but silently dropped
    # from responses because SubScores had no field for it.
    from api.factors import to_snake
    from api.mapdata import FACTOR_COLUMNS
    from api.schemas import SubScores
    from scoring.engine import CATEGORY_SPECS_V2_1

    assert len(SubScores.model_fields) == 13
    assert set(SubScores.model_fields) == {to_snake(k) for k in FACTOR_COLUMNS}
    assert set(FACTOR_COLUMNS.values()) == {s.score_column for s in CATEGORY_SPECS_V2_1}


def test_v2_rows_are_read_through_legacy_columns():
    from api.lookup import sub_scores_from_score_row

    v2 = sub_scores_from_score_row(
        {
            "trail_popularity_score": 42.0,
            "premium_retail_score": 61.0,
            "road_score": 12.0,
            "gas_station_score": 90.0,  # negative-direction legacy score: not mapped
            "convenience_store_score": 80.0,
        }
    ).model_dump(by_alias=True)
    assert v2["recreation"] == 42.0 and v2["shopping"] == 61.0 and v2["traffic"] == 12.0
    assert v2["gasConvenience"] is None
    assert set(v2) >= {"shopping", "recreation", "gasConvenience", "traffic"}
    assert not {"premiumRetail", "trailPopularity", "gasStation", "road"} & set(v2)

    both = sub_scores_from_score_row(
        {"recreation_score": 70.0, "trail_popularity_score": 42.0, "shopping_score": 0.0,
         "premium_retail_score": 50.0}
    )  # fmt: skip
    assert both.recreation == 70.0  # the new column wins
    assert both.shopping == 0.0  # a real 0 is not treated as missing


def test_error_body_omits_upgrade_url_when_unset():
    from fastapi.testclient import TestClient

    from api.main import app

    resp = TestClient(app).get("/v1/score")
    assert resp.status_code == 400
    assert resp.json() == {
        "code": "invalid_request",
        "message": "Provide address, or both lat and lon.",
    }


def test_validation_errors_use_the_contract_error_shape_not_fastapi_422():
    from fastapi.testclient import TestClient

    from api.main import app

    resp = TestClient(app).get("/v1/score/not-a-uuid/explanation")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "invalid_request"
    assert "geo_entity_id" in body["message"] or "geoEntityId" in body["message"]
    assert "detail" not in body


def test_every_scored_factor_has_a_human_readable_explanation_label():
    # The trail factor shipped without a label and the live explanation read
    # "trail_popularity 79/100" -- a raw field name. Fail on any future gap.
    from api.explain import FACTOR_LABELS
    from api.schemas import SubScores

    assert set(SubScores.model_fields) == set(FACTOR_LABELS)
    assert all("_" not in label for label in FACTOR_LABELS.values())


# --- v2: feet/miles, school info, nearestMi, triangulate prefilter --------


def test_explanation_distances_are_feet_and_miles_only():
    import re

    from api.explain import nearest_m_by_factor

    nearest = nearest_m_by_factor({"grocery_nearest_m": 140, "gym_nearest_m": 1200})
    text = build_explanation(SubScores(grocery=90, gym=10, cafe=50), nearest)
    assert "Nearest feature: grocery access 450 ft, gym access 0.7 mi." in text
    assert not re.search(r"\d\s*(km|m|metres|meters)\b", text)


def test_explanation_without_distances_is_unchanged():
    assert "Nearest" not in build_explanation(SubScores(grocery=90, gym=10))


def test_nearest_mi_by_factor_picks_nearest_premium_brand_and_nulls():
    from api.explain import nearest_mi_by_factor

    out = nearest_mi_by_factor(
        {
            "grocery_nearest_m": 1609.344,
            "whole_foods_nearest_m": 3000,
            "starbucks_nearest_m": 804.672,
            "emergency_facility_nearest_m": 0,
        }
    )
    assert out["grocery"] == pytest.approx(1.0)
    assert out["shopping"] == pytest.approx(0.5)
    assert out["emergencyCorridor"] == 0.0
    assert out["gym"] is None
    assert set(out) == {
        "grocery", "gym", "cafe", "restaurant", "bar", "gasConvenience",
        "transit", "school", "recreation", "shopping", "emergencyCorridor",
    }  # fmt: skip
    # v2.1 columns are feet; the nearest of old and new wins
    ft = nearest_mi_by_factor({"shopping_nearest_ft": 2640, "starbucks_nearest_m": 3218.688,
                               "park_nearest_ft": 528})  # fmt: skip
    assert ft["shopping"] == pytest.approx(0.5) and ft["recreation"] == pytest.approx(0.1)
    assert all(v is None for v in nearest_mi_by_factor(None).values())


def _score_row(**extra):
    return {
        "composite_score": 70, "weights_version": "v1", "computed_at": datetime.now(timezone.utc),
        **extra,
    }  # fmt: skip


def test_school_info_null_for_v1_rows():
    geo = {"id": uuid4(), "latitude": 40.0, "longitude": -73.0, "formatted_address": "x"}
    body = build_score_response(geo, _score_row(), None).model_dump(by_alias=True, mode="json")
    assert body["school"] is None


def test_school_info_populated_for_v2_rows():
    geo = {"id": uuid4(), "latitude": 40.0, "longitude": -73.0, "formatted_address": "x"}
    feature = {"school_district_name": "Garden City UFSD", "school_rating_source": "niche"}
    resp = build_score_response(geo, _score_row(school_proximity_score=72.0), feature)
    body = resp.model_dump(by_alias=True, mode="json")
    assert body["school"] == {
        "proximity": 72.0, "ratingAvailable": False,
        "districtName": "Garden City UFSD", "source": "niche",
    }  # fmt: skip
    rated = build_score_response(
        geo, _score_row(school_proximity_score=72.0, school_score=80), feature
    )
    assert rated.school.rating_available is True


def test_triangulate_bbox_contains_circle_and_modes_combine():
    from api.triangulate_sql import box_is_empty, circle_bbox, combined_bbox

    a = anchor_to_circle(40.7, -73.9, 10, "drive")
    b = anchor_to_circle(40.7, -73.5, 10, "drive")
    box = circle_bbox(a)
    # every point on the circle edge (haversine <= radius) lies inside the box
    for bearing_lat, bearing_lon in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        import math

        d = a.radius_m
        lat = a.latitude + bearing_lat * d / 111_194.9
        lon = a.longitude + bearing_lon * d / (111_194.9 * math.cos(math.radians(a.latitude)))
        assert box[0] <= lat <= box[1] and box[2] <= lon <= box[3]
    union = combined_bbox([a, b], "union")
    assert union[2] <= circle_bbox(a)[2] and union[3] >= circle_bbox(b)[3]
    assert box_is_empty(combined_bbox([a, b], "intersect"))  # ~30 km apart, 11 km radii
    assert combined_bbox([], "intersect") is None


def test_triangulate_prefilter_gives_same_ranking_as_full_scan():
    from api.triangulate_sql import combined_bbox

    circles = [
        anchor_to_circle(40.70, -73.90, 15, "drive"),
        anchor_to_circle(40.72, -73.88, 15, "walk"),
    ]
    cells = [
        {
            "latitude": 40.70 + i * 0.004,
            "longitude": -73.90 + j * 0.004,
            "composite_score": i * 7 + j,
        }
        for i in range(-30, 30)
        for j in range(-30, 30)
    ]
    for mode in ("intersect", "union"):
        box = combined_bbox(circles, mode)
        pre = [
            c for c in cells
            if box[0] <= c["latitude"] <= box[1] and box[2] <= c["longitude"] <= box[3]
        ]  # fmt: skip
        assert rank_candidates(pre, circles, mode, 1000) == rank_candidates(
            cells, circles, mode, 1000
        )


def test_triangulate_sql_and_empty_box_short_circuits():
    from api.triangulate_sql import build_candidates_sql, get_scored_candidates_in_box

    sql, params = build_candidates_sql((1.0, 2.0, 3.0, 4.0))
    assert "ge.latitude between %s and %s" in sql and params == [1.0, 2.0, 3.0, 4.0, None]
    assert build_candidates_sql(None)[1] == [None]

    class Boom:
        def cursor(self):
            raise AssertionError("must not query an empty box")

    assert get_scored_candidates_in_box(Boom(), (2.0, 1.0, 0.0, 1.0)) == []


def test_candidate_sql_prefers_the_configured_weights_version():
    from api.triangulate_sql import build_candidates_sql

    sql, params = build_candidates_sql((1.0, 2.0, 3.0, 4.0), "v2-handtuned")
    assert "(s.weights_version = %s) desc" in sql
    assert params == [1.0, 2.0, 3.0, 4.0, "v2-handtuned"]
