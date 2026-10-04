import pytest

from scoring.engine import (
    CATEGORY_SPECS,
    CATEGORY_SPECS_V2,
    DEFAULT_WEIGHTS,
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
    with_rating_row = {
        "school_count_1600m": 3,
        "school_nearest_m": 200,
        "school_avg_rating_1600m": 9.0,
    }
    without_rating_row = {
        "school_count_1600m": 3,
        "school_nearest_m": 200,
        "school_avg_rating_1600m": None,
    }
    assert compute_raw_goodness(with_rating_row, spec("school_score")) == compute_raw_goodness(
        without_rating_row, spec("school_score")
    )


def test_compute_rating_raw():
    assert compute_rating_raw({"school_avg_rating_1600m": 8.5}, spec("school_score")) == 8.5
    assert compute_rating_raw({"school_avg_rating_1600m": None}, spec("school_score")) is None
    assert compute_rating_raw({}, spec("school_score")) is None
    # Category with no rating_column at all (e.g. grocery) always returns None.
    assert compute_rating_raw({"grocery_count_500m": 5}, spec("grocery_score")) is None


def test_school_missing_rating_is_null_and_never_penalized():
    # Identical proximity/density, different rating availability. The
    # unrated cell gets NO school score (not 0, not proximity-only), and the
    # rated cells order by rating.
    rows = [
        {
            "geo_entity_id": "no_rating",
            "school_count_1600m": 3,
            "school_nearest_m": 200,
            "school_avg_rating_1600m": None,
        },
        {
            "geo_entity_id": "low_rating",
            "school_count_1600m": 3,
            "school_nearest_m": 200,
            "school_avg_rating_1600m": 1.0,
        },
        {
            "geo_entity_id": "high_rating",
            "school_count_1600m": 3,
            "school_nearest_m": 200,
            "school_avg_rating_1600m": 9.0,
        },
    ]
    for r in rows:  # a second factor so the unrated cell still gets a row
        r.update(grocery_count_500m=2, grocery_nearest_m=100)
    scored = score_metro_cohort(rows)
    assert "school_score" not in scored["no_rating"]
    assert scored["low_rating"]["school_score"] < scored["high_rating"]["school_score"]
    # proximity is still reported for every cell with school data
    assert all("school_proximity_score" in scored[k] for k in scored)


def test_school_blend_is_20_80():
    rows = [
        {
            "geo_entity_id": "a",
            "school_count_1600m": 0,
            "school_nearest_m": 5000,
            "school_avg_rating_1600m": 10.0,
        },
        {
            "geo_entity_id": "b",
            "school_count_1600m": 10,
            "school_nearest_m": 0,
            "school_avg_rating_1600m": 0.0,
        },
    ]
    scored = score_metro_cohort(rows)
    # a: proximity 0, rating 100 -> 0.2*0 + 0.8*100; b: proximity 100, rating 0 -> 20
    assert scored["a"]["school_score"] == pytest.approx(80.0)
    assert scored["b"]["school_score"] == pytest.approx(20.0)
    assert scored["b"]["school_proximity_score"] == pytest.approx(100.0)
    assert spec("school_score").rating_weight == 0.8
    assert spec("school_score").missing_rating == "null"


def test_school_unrated_cell_excluded_from_composite():
    rows = [
        {
            "geo_entity_id": "a",
            "school_count_1600m": 2,
            "school_nearest_m": 100,
            "school_avg_rating_1600m": None,
            "grocery_count_500m": 1,
            "grocery_nearest_m": 100,
        },
        {"geo_entity_id": "b", "grocery_count_500m": 5, "grocery_nearest_m": 50},
    ]
    scored = score_metro_cohort(rows)
    assert "school_score" not in scored["a"]
    assert scored["a"]["composite_score"] == pytest.approx(scored["a"]["grocery_score"])


def test_trail_blend_unchanged_and_falls_back_to_proximity_only():
    t = spec("trail_popularity_score")
    assert t.rating_weight == pytest.approx(1 / 3)
    assert t.missing_rating == "blend_only"
    rows = [
        {
            "geo_entity_id": "a",
            "running_trail_count_800m": 0,
            "running_trail_nearest_m": 5000,
            "strava_segment_popularity_raw": 0.0,
        },
        {
            "geo_entity_id": "b",
            "running_trail_count_800m": 10,
            "running_trail_nearest_m": 0,
            "strava_segment_popularity_raw": 100.0,
        },
        {
            "geo_entity_id": "c",
            "running_trail_count_800m": 10,
            "running_trail_nearest_m": 0,
            "strava_segment_popularity_raw": None,
        },
    ]
    scored = score_metro_cohort(rows)
    assert scored["b"]["trail_popularity_score"] == pytest.approx(100.0)
    assert scored["c"]["trail_popularity_score"] == pytest.approx(100.0)  # proximity-only
    assert "school_proximity_score" not in scored["a"]


def test_premium_retail_direction_higher_is_better():
    rows = [
        {"geo_entity_id": "lo", "premium_retail_raw": 1.0},
        {"geo_entity_id": "hi", "premium_retail_raw": 9.0},
    ]
    scored = score_metro_cohort(rows)
    assert scored["hi"]["premium_retail_score"] > scored["lo"]["premium_retail_score"]


def test_restaurant_and_bar_prefer_closer_and_more():
    rows = [
        {
            "geo_entity_id": "far",
            "restaurant_count_500m": 1,
            "restaurant_nearest_m": 400,
            "bar_count_500m": 0,
            "bar_nearest_m": None,
        },
        {
            "geo_entity_id": "near",
            "restaurant_count_500m": 20,
            "restaurant_nearest_m": 30,
            "bar_count_500m": 5,
            "bar_nearest_m": 40,
        },
    ]
    scored = score_metro_cohort(rows)
    assert scored["near"]["restaurant_score"] > scored["far"]["restaurant_score"]
    assert scored["near"]["bar_score"] > scored["far"]["bar_score"]


def test_emergency_corridor_prefers_facility_signal_and_falls_back_to_proxy():
    e = spec("emergency_corridor_score")
    both = {"emergency_corridor_facility_raw": 4.0, "emergency_corridor_proxy_raw": 99.0}
    assert compute_raw_goodness(both, e) == -4.0
    assert (
        compute_raw_goodness(
            {"emergency_corridor_facility_raw": None, "emergency_corridor_proxy_raw": 7.0}, e
        )
        == -7.0
    )
    assert compute_raw_goodness({"emergency_corridor_proxy_raw": 7.0}, e) == -7.0
    assert compute_raw_goodness({}, e) is None
    # damping applies to the facility signal too
    assert compute_raw_goodness({**both, "street_orientation": "side_street"}, e) == -2.0


def test_default_weights_v2_and_factor_count():
    assert len(CATEGORY_SPECS_V2) == 14
    assert set(DEFAULT_WEIGHTS) == {s.score_column for s in CATEGORY_SPECS_V2}
    assert DEFAULT_WEIGHTS["restaurant_score"] == 1.0
    assert DEFAULT_WEIGHTS["bar_score"] == 0.5
    assert DEFAULT_WEIGHTS["premium_retail_score"] == 0.75
    assert DEFAULT_WEIGHTS["emergency_corridor_score"] == 0.75


def test_underlying_flag_marks_only_premium_retail_and_trail_popularity():
    from scoring.engine import UNDERLYING_SCORE_COLUMNS

    assert UNDERLYING_SCORE_COLUMNS == {"premium_retail_score", "trail_popularity_score"}
    assert {s.score_column for s in CATEGORY_SPECS if s.underlying} == set(UNDERLYING_SCORE_COLUMNS)
    # underlying metrics still carry a default weight and count in the composite
    assert all(c in DEFAULT_WEIGHTS for c in UNDERLYING_SCORE_COLUMNS)
    assert DEFAULT_WEIGHTS["premium_retail_score"] == 0.75
    assert DEFAULT_WEIGHTS["trail_popularity_score"] == 1.25


def test_composite_with_all_14_factors():
    scores = {c: 100.0 for c in DEFAULT_WEIGHTS}
    assert compute_composite(scores) == pytest.approx(100.0)
    scores["bar_score"] = 0.0
    total = sum(DEFAULT_WEIGHTS.values())
    assert compute_composite(scores) == pytest.approx(100.0 * (total - 0.5) / total)


def test_trail_popularity_works_without_strava_data():
    # No Strava data anywhere (unconfigured, or no segments nearby -- None,
    # never 0). Category still ranks sensibly off OSM trail count/distance
    # alone: a cell with a trail beats one without.
    rows = [
        {
            "geo_entity_id": "no_trail",
            "running_trail_count_800m": 0,
            "running_trail_nearest_m": None,
            "strava_segment_popularity_raw": None,
        },
        {
            "geo_entity_id": "has_trail",
            "running_trail_count_800m": 4,
            "running_trail_nearest_m": 150,
            "strava_segment_popularity_raw": None,
        },
    ]
    scored = score_metro_cohort(rows)
    assert (
        scored["has_trail"]["trail_popularity_score"] > scored["no_trail"]["trail_popularity_score"]
    )


def test_trail_popularity_ranks_by_strava_popularity_when_available():
    # Identical OSM trail presence, different Strava popularity -- the
    # more-used segment should score higher once there's enough Strava
    # data in the cohort to actually normalize against (a single lone
    # data point normalizes to a neutral midpoint, not "best" or "worst" --
    # that's a separate, deliberate degenerate-cohort behavior, not what
    # this test is checking).
    rows = [
        {
            "geo_entity_id": "low_popularity",
            "running_trail_count_800m": 4,
            "running_trail_nearest_m": 150,
            "strava_segment_popularity_raw": 50.0,
        },
        {
            "geo_entity_id": "high_popularity",
            "running_trail_count_800m": 4,
            "running_trail_nearest_m": 150,
            "strava_segment_popularity_raw": 500.0,
        },
    ]
    scored = score_metro_cohort(rows)
    assert (
        scored["high_popularity"]["trail_popularity_score"]
        > scored["low_popularity"]["trail_popularity_score"]
    )


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
            "grocery_count_500m": 5,
            "grocery_nearest_m": 100,
            "gas_station_count_500m": 0,
            "gas_station_nearest_m": None,
        },
        {
            "geo_entity_id": "b",
            "grocery_count_500m": 0,
            "grocery_nearest_m": None,
            "gas_station_count_500m": 4,
            "gas_station_nearest_m": 30,
        },
    ]
    scored = score_metro_cohort(rows)
    assert set(scored) == {"a", "b"}
    assert scored["a"]["composite_score"] > scored["b"]["composite_score"]
    assert "grocery_score" in scored["a"]
    assert "gas_station_score" in scored["a"]
    # Category with no data anywhere in the cohort shouldn't appear.
    assert "cafe_score" not in scored["a"]


def test_all_score_columns_cover_every_emitted_column():
    from scoring.engine import all_score_columns

    cols = all_score_columns()
    assert "composite_score" in cols and "school_proximity_score" in cols
    assert len(cols) == len(set(cols))


# ---------------------------------------------------------------------------
# v2.1 (weights_version 'v2.1-handtuned')
# ---------------------------------------------------------------------------

from scoring.engine import (
    ADJACENCY_FULL_M,
    ADJACENCY_ZERO_M,
    CATEGORY_SPECS_V2_1,
    V2_1_WEIGHTS,
    WEIGHTS_VERSION_V2_1,
    adjacency_share,
    all_score_columns,
    gas_convenience_adjacency_penalty,
    gas_convenience_goodness,
    noise_corridor_goodness,
    shopping_goodness,
)

FT = 0.3048


def test_v2_1_has_thirteen_factors_and_the_agreed_weights():
    assert len(CATEGORY_SPECS_V2_1) == 13
    assert set(V2_1_WEIGHTS) == {s.score_column for s in CATEGORY_SPECS_V2_1}
    assert V2_1_WEIGHTS == {
        "grocery_score": 14, "transit_score": 14, "emergency_corridor_score": 12,
        "restaurant_score": 10, "school_score": 10, "gym_score": 9, "cafe_score": 8,
        "gas_convenience_score": 6, "bar_score": 5, "airport_score": 5,
        "recreation_score": 5, "shopping_score": 4, "road_score": 4,
    }  # fmt: skip
    assert not any(s.underlying for s in CATEGORY_SPECS_V2_1)
    assert sum(V2_1_WEIGHTS.values()) == 106


def test_v2_1_score_columns_and_union_whitelist():
    cols = all_score_columns(WEIGHTS_VERSION_V2_1)
    assert "gas_convenience_score" in cols and "shopping_score" in cols
    assert "recreation_score" in cols and "premium_retail_score" not in cols
    assert cols[-1] == "composite_score"
    union = {s.score_column for s in CATEGORY_SPECS}
    assert {"shopping_score", "recreation_score", "gas_convenience_score"} <= union
    assert "premium_retail_score" in union  # v2 rows keep working
    assert len(CATEGORY_SPECS) == len(union)


def test_adjacency_share_curve():
    assert adjacency_share(None) == 0.0
    assert adjacency_share(0) == 1.0
    assert adjacency_share(300 * FT - 0.01) == 1.0
    assert adjacency_share(ADJACENCY_FULL_M) == pytest.approx(1.0)
    assert adjacency_share(550 * FT) == pytest.approx(0.5, abs=0.001)
    assert adjacency_share(ADJACENCY_ZERO_M) == 0.0
    assert adjacency_share(5000) == 0.0


def test_adjacency_penalty_combines_both_kinds_capped():
    assert gas_convenience_adjacency_penalty(None, None) == 0.0
    one = gas_convenience_adjacency_penalty(10, None)
    both = gas_convenience_adjacency_penalty(10, 20)
    assert one == pytest.approx(3.0)
    assert both == pytest.approx(4.5)  # capped at 1.5x
    assert gas_convenience_adjacency_penalty(10, 5000) == pytest.approx(one)


def test_noise_corridor_adds_adjacency_penalty_to_the_base_signal():
    base = {"emergency_corridor_facility_raw": 2.0}
    assert noise_corridor_goodness(base) == -2.0
    near = {**base, "gas_station_nearest_m": 20.0}
    assert noise_corridor_goodness(near) == pytest.approx(-5.0)
    far = {**base, "gas_station_nearest_m": 150.0, "convenience_store_nearest_m": 1000.0}
    assert -5.0 < noise_corridor_goodness(far) < -2.0
    # proxy fallback, side-street damping applies to the road signal only
    assert noise_corridor_goodness({"emergency_corridor_proxy_raw": 4.0}) == -4.0
    damped = {**near, "street_orientation": "side_street"}
    assert noise_corridor_goodness(damped) == pytest.approx(-(1.0 + 3.0))
    # no corridor signal at all -> no score, even with a gas station next door
    assert noise_corridor_goodness({"gas_station_nearest_m": 5.0}) is None


def test_gas_convenience_is_one_positive_factor_over_the_union():
    assert gas_convenience_goodness({}) is None
    none_nearby = gas_convenience_goodness(
        {"gas_station_count_500m": 0, "convenience_store_count_500m": 0}
    )
    close_gas = gas_convenience_goodness(
        {
            "gas_station_count_500m": 1,
            "gas_station_nearest_m": 100,
            "convenience_store_count_500m": 0,
        }
    )
    close_both = gas_convenience_goodness(
        {
            "gas_station_count_500m": 1, "gas_station_nearest_m": 100,
            "convenience_store_count_500m": 3, "convenience_store_nearest_m": 60,
        }
    )  # fmt: skip
    assert none_nearby < close_gas < close_both
    only_convenience = gas_convenience_goodness(
        {"convenience_store_count_500m": 2, "convenience_store_nearest_m": 100}
    )
    assert only_convenience > none_nearby


def test_shopping_goodness_combines_stored_signal_and_anchor_bonus():
    assert shopping_goodness({}) is None
    assert shopping_goodness({"shopping_raw": 0.5}) == pytest.approx(0.5)
    assert shopping_goodness({"shopping_raw": 0.5, "premium_retail_raw": 2.5}) == pytest.approx(0.7)
    assert shopping_goodness({"premium_retail_raw": 1.0}) == pytest.approx(0.08)


def _v21_rows():
    return [
        {
            "geo_entity_id": "urban",
            "shopping_raw": 0.9, "premium_retail_raw": 2.0,
            "gas_station_count_500m": 1, "gas_station_nearest_m": 150,
            "convenience_store_count_500m": 4, "convenience_store_nearest_m": 40,
            "recreation_raw": 0.8,
            "running_trail_count_800m": 3, "running_trail_nearest_m": 100,
            "emergency_corridor_facility_raw": 3.0,
        },
        {
            "geo_entity_id": "rural",
            "shopping_raw": 0.1,
            "gas_station_count_500m": 0, "gas_station_nearest_m": 2500,
            "convenience_store_count_500m": 0, "convenience_store_nearest_m": 3000,
            "recreation_raw": 0.2,
            "running_trail_count_800m": 0, "running_trail_nearest_m": None,
            "emergency_corridor_facility_raw": 0.5,
        },
    ]  # fmt: skip


def test_score_metro_cohort_v2_1_emits_the_new_columns_and_normalized_composite():
    scored = score_metro_cohort(_v21_rows(), WEIGHTS_VERSION_V2_1)
    urban, rural = scored["urban"], scored["rural"]
    for col in ("shopping_score", "gas_convenience_score", "recreation_score"):
        assert urban[col] == pytest.approx(100.0) and rural[col] == pytest.approx(0.0)
    assert "premium_retail_score" not in urban and "gas_station_score" not in urban
    # more corridor + adjacent stations = worse noise score
    assert urban["emergency_corridor_score"] < rural["emergency_corridor_score"]
    # composite is normalized by the weight of factors that have a score
    weights = V2_1_WEIGHTS
    expected = sum(urban[c] * weights[c] for c in urban if c in weights) / sum(
        weights[c] for c in urban if c in weights
    )
    assert urban["composite_score"] == pytest.approx(expected)


def test_recreation_blends_parks_75_and_trails_25_and_falls_back():
    rows = [
        {"geo_entity_id": "a", "recreation_raw": 1.0, "running_trail_count_800m": 0},
        {"geo_entity_id": "b", "recreation_raw": 0.0, "running_trail_count_800m": 5,
         "running_trail_nearest_m": 10},
        {"geo_entity_id": "c", "recreation_raw": None, "running_trail_count_800m": 5,
         "running_trail_nearest_m": 10},
        {"geo_entity_id": "d", "recreation_raw": 0.5, "running_trail_count_800m": None},
    ]  # fmt: skip
    scored = score_metro_cohort(rows, WEIGHTS_VERSION_V2_1)
    assert scored["a"]["recreation_score"] == pytest.approx(75.0)
    assert scored["b"]["recreation_score"] == pytest.approx(25.0)
    assert scored["c"]["recreation_score"] == pytest.approx(100.0)  # trails only
    assert scored["d"]["recreation_score"] == pytest.approx(50.0)  # parks only


def test_score_metro_cohort_defaults_to_v2_columns():
    rows = [{"geo_entity_id": "x", "premium_retail_raw": 1.0, "grocery_nearest_m": 10}]
    scored = score_metro_cohort(rows)
    assert "premium_retail_score" in scored["x"] and "shopping_score" not in scored["x"]
