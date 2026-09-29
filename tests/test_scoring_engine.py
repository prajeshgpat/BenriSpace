from scoring.engine import (
    CATEGORY_SPECS,
    compute_composite,
    compute_rating_raw,
    compute_raw_goodness,
    min_max_normalize,
    score_metro_cohort,
)


def spec(score_column):
    return next(s for s in CATEGORY_SPECS if s.score_column == score_column)


def test_positive_category_prefers_closer_and_more():
    close_dense = compute_raw_goodness(
        {"grocery_count_500m": 5, "grocery_nearest_m": 50}, spec("grocery_score")
    )
    far_sparse = compute_raw_goodness(
        {"grocery_count_500m": 1, "grocery_nearest_m": 800}, spec("grocery_score")
    )
    assert close_dense > far_sparse


def test_negative_category_inverts_so_absence_is_good():
    no_gas_station = compute_raw_goodness(
        {"gas_station_count_500m": 0, "gas_station_nearest_m": None}, spec("gas_station_score")
    )
    lots_of_gas_stations = compute_raw_goodness(
        {"gas_station_count_500m": 6, "gas_station_nearest_m": 40}, spec("gas_station_score")
    )
    assert no_gas_station > lots_of_gas_stations


def test_missing_data_returns_none_not_a_fabricated_value():
    assert compute_raw_goodness({}, spec("grocery_score")) is None
    assert compute_raw_goodness({"congestion_proxy_raw": None}, spec("road_score")) is None


def test_emergency_corridor_dampened_by_side_street():
    facing = compute_raw_goodness(
        {"emergency_corridor_proxy_raw": 10, "street_orientation": "facing_corridor"},
        spec("emergency_corridor_score"),
    )
    side = compute_raw_goodness(
        {"emergency_corridor_proxy_raw": 10, "street_orientation": "side_street"},
        spec("emergency_corridor_score"),
    )
    # Both negative (inverted), but the side-street penalty should be
    # smaller in magnitude, so its inverted (negated) raw value is higher.
    assert side > facing


def test_compute_raw_goodness_ignores_rating_column():
    # Proximity+density signal only -- rating is normalized separately
    # (see compute_rating_raw / score_metro_cohort), never blended into
    # the same raw value pre-normalization (they're on incomparable
    # scales: meters vs. a count vs. an external rating).
    with_rating_row = {"school_count_1600m": 3, "school_nearest_m": 200, "school_avg_rating_1600m": 9.0}
    without_rating_row = {"school_count_1600m": 3, "school_nearest_m": 200, "school_avg_rating_1600m": None}
    assert compute_raw_goodness(with_rating_row, spec("school_score")) == compute_raw_goodness(
        without_rating_row, spec("school_score")
    )


def test_compute_rating_raw():
    assert compute_rating_raw({"school_avg_rating_1600m": 8.5}, spec("school_score")) == 8.5
    assert compute_rating_raw({"school_avg_rating_1600m": None}, spec("school_score")) is None
    assert compute_rating_raw({}, spec("school_score")) is None
    # Category with no rating_column at all (e.g. grocery) always returns None.
    assert compute_rating_raw({"grocery_count_500m": 5}, spec("grocery_score")) is None


def test_missing_rating_does_not_penalize_relative_to_rated_rows():
    # Three cells with IDENTICAL proximity/density but different rating
    # availability. If a missing rating were ever treated as "worst
    # possible," the no-rating cell would rank below the low-rating cell --
    # that's the bug this test guards against.
    rows = [
        {"geo_entity_id": "no_rating", "school_count_1600m": 3, "school_nearest_m": 200, "school_avg_rating_1600m": None},
        {"geo_entity_id": "low_rating", "school_count_1600m": 3, "school_nearest_m": 200, "school_avg_rating_1600m": 1.0},
        {"geo_entity_id": "high_rating", "school_count_1600m": 3, "school_nearest_m": 200, "school_avg_rating_1600m": 9.0},
    ]
    scored = score_metro_cohort(rows)
    assert scored["low_rating"]["school_score"] < scored["no_rating"]["school_score"] < scored["high_rating"]["school_score"]


def test_trail_popularity_works_without_strava_data():
    # No Strava data anywhere (unconfigured, or no segments nearby -- None,
    # never 0). Category still ranks sensibly off OSM trail count/distance
    # alone: a cell with a trail beats one without.
    rows = [
        {"geo_entity_id": "no_trail", "running_trail_count_800m": 0, "running_trail_nearest_m": None, "strava_segment_popularity_raw": None},
        {"geo_entity_id": "has_trail", "running_trail_count_800m": 4, "running_trail_nearest_m": 150, "strava_segment_popularity_raw": None},
    ]
    scored = score_metro_cohort(rows)
    assert scored["has_trail"]["trail_popularity_score"] > scored["no_trail"]["trail_popularity_score"]


def test_trail_popularity_ranks_by_strava_popularity_when_available():
    # Identical OSM trail presence, different Strava popularity -- the
    # more-used segment should score higher once there's enough Strava
    # data in the cohort to actually normalize against (a single lone
    # data point normalizes to a neutral midpoint, not "best" or "worst" --
    # that's a separate, deliberate degenerate-cohort behavior, not what
    # this test is checking).
    rows = [
        {"geo_entity_id": "low_popularity", "running_trail_count_800m": 4, "running_trail_nearest_m": 150, "strava_segment_popularity_raw": 50.0},
        {"geo_entity_id": "high_popularity", "running_trail_count_800m": 4, "running_trail_nearest_m": 150, "strava_segment_popularity_raw": 500.0},
    ]
    scored = score_metro_cohort(rows)
    assert scored["high_popularity"]["trail_popularity_score"] > scored["low_popularity"]["trail_popularity_score"]


def test_min_max_normalize_range_and_degenerate_case():
    normed = min_max_normalize({"a": 0, "b": 50, "c": 100})
    assert normed["a"] == 0.0
    assert normed["c"] == 100.0
    assert 0 < normed["b"] < 100

    degenerate = min_max_normalize({"a": 7, "b": 7})
    assert degenerate == {"a": 50.0, "b": 50.0}

    assert min_max_normalize({}) == {}


def test_compute_composite_weighted_average():
    composite = compute_composite({"grocery_score": 100.0, "gym_score": 0.0})
    # weights: grocery 1.5, gym 1.0 -> (1.5*100 + 1.0*0) / 2.5 = 60
    assert composite == 60.0


def test_compute_composite_empty_input():
    assert compute_composite({}) == 0.0


def test_score_metro_cohort_end_to_end():
    rows = [
        {
            "geo_entity_id": "a",
            "grocery_count_500m": 5, "grocery_nearest_m": 100,
            "gas_station_count_500m": 0, "gas_station_nearest_m": None,
        },
        {
            "geo_entity_id": "b",
            "grocery_count_500m": 0, "grocery_nearest_m": None,
            "gas_station_count_500m": 4, "gas_station_nearest_m": 30,
        },
    ]
    scored = score_metro_cohort(rows)
    assert set(scored) == {"a", "b"}
    assert scored["a"]["composite_score"] > scored["b"]["composite_score"]
    assert "grocery_score" in scored["a"]
    assert "gas_station_score" in scored["a"]
    # Category with no data anywhere in the cohort shouldn't appear.
    assert "cafe_score" not in scored["a"]
