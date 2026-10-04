from ingestion.roads import (
    _parse_lanes,
    bucket_key,
    compute_congestion_proxy_raw,
    compute_emergency_corridor_proxy_raw,
    derive_street_orientation,
    index_segments,
    is_major_corridor,
    nearby_segments_with_distance,
    nearest_segment,
    road_class_weight,
    segment_congestion_contribution,
)
from scoring.engine import CATEGORY_SPECS, compute_raw_goodness


def spec(score_column):
    return next(s for s in CATEGORY_SPECS if s.score_column == score_column)


# --------------------------------------------------------------------------
# Highway classification
# --------------------------------------------------------------------------


def test_road_class_weight_orders_hierarchy_correctly():
    assert road_class_weight("motorway") > road_class_weight("trunk")
    assert road_class_weight("trunk") > road_class_weight("primary")
    assert road_class_weight("primary") > road_class_weight("secondary")
    assert road_class_weight("secondary") > road_class_weight("tertiary")
    assert road_class_weight("tertiary") > road_class_weight("residential")
    assert road_class_weight("residential") > road_class_weight("service")


def test_road_class_weight_unknown_defaults_to_residential_equivalent():
    assert road_class_weight("some_unexpected_tag") == road_class_weight("residential")
    assert road_class_weight(None) == road_class_weight("residential")


def test_is_major_corridor_threshold():
    assert is_major_corridor("primary") is True
    assert is_major_corridor("secondary") is True
    assert is_major_corridor("tertiary") is False
    assert is_major_corridor("residential") is False
    assert is_major_corridor("motorway") is True


def test_derive_street_orientation():
    assert derive_street_orientation("primary") == "facing_corridor"
    assert derive_street_orientation("secondary") == "facing_corridor"
    assert derive_street_orientation("motorway") == "facing_corridor"
    assert derive_street_orientation("residential") == "side_street"
    assert derive_street_orientation("tertiary") == "side_street"
    assert derive_street_orientation("service") == "side_street"
    assert derive_street_orientation(None) == "unknown"


def test_parse_lanes():
    assert _parse_lanes("2") == 2
    assert _parse_lanes("1;2") == 1
    assert _parse_lanes(None) is None
    assert _parse_lanes("not a number") is None


# --------------------------------------------------------------------------
# Congestion proxy
# --------------------------------------------------------------------------


def test_congestion_contribution_prefers_closer_and_more_major():
    close = segment_congestion_contribution("primary", distance_m=50)
    far = segment_congestion_contribution("primary", distance_m=500)
    assert close > far

    major = segment_congestion_contribution("primary", distance_m=100)
    minor = segment_congestion_contribution("residential", distance_m=100)
    assert major > minor


def test_congestion_contribution_narrow_bottleneck_bonus():
    # A single-lane stretch of an otherwise-through road (weight >= 2) gets
    # a bonus; a single-lane residential street (weight 1, already low)
    # does not.
    normal_secondary = segment_congestion_contribution("secondary", distance_m=100, lanes=2)
    narrow_secondary = segment_congestion_contribution("secondary", distance_m=100, lanes=1)
    assert narrow_secondary > normal_secondary

    normal_residential = segment_congestion_contribution("residential", distance_m=100, lanes=2)
    narrow_residential = segment_congestion_contribution("residential", distance_m=100, lanes=1)
    assert narrow_residential == normal_residential


def test_compute_congestion_proxy_raw_sums_and_respects_radius():
    nearby = [
        {"highway": "primary", "distance_m": 100, "lanes": None},
        {"highway": "residential", "distance_m": 200, "lanes": None},
        {"highway": "primary", "distance_m": 5000, "lanes": None},  # outside radius
    ]
    result = compute_congestion_proxy_raw(nearby, radius_m=600)
    expected = segment_congestion_contribution("primary", 100) + segment_congestion_contribution(
        "residential", 200
    )
    assert result == round(expected, 3)


def test_congestion_proxy_higher_for_dense_major_roads_than_quiet_residential():
    dense_major_area = [
        {"highway": "primary", "distance_m": 80, "lanes": None},
        {"highway": "secondary", "distance_m": 150, "lanes": None},
        {"highway": "primary", "distance_m": 300, "lanes": None},
    ]
    quiet_residential_area = [
        {"highway": "residential", "distance_m": 80, "lanes": None},
    ]
    assert compute_congestion_proxy_raw(dense_major_area) > compute_congestion_proxy_raw(
        quiet_residential_area
    )


# --------------------------------------------------------------------------
# Emergency corridor proxy
# --------------------------------------------------------------------------


def test_emergency_corridor_proxy_ignores_minor_roads():
    nearby = [{"highway": "residential", "distance_m": 20, "lanes": None}]
    assert compute_emergency_corridor_proxy_raw(nearby) == 0.0


def test_emergency_corridor_proxy_counts_major_roads_within_radius():
    nearby = [
        {"highway": "primary", "distance_m": 100, "lanes": None},
        {"highway": "residential", "distance_m": 10, "lanes": None},  # ignored, not major
        {"highway": "secondary", "distance_m": 5000, "lanes": None},  # outside radius
    ]
    result = compute_emergency_corridor_proxy_raw(nearby, radius_m=500)
    assert result > 0.0
    only_primary = compute_emergency_corridor_proxy_raw(
        [{"highway": "primary", "distance_m": 100, "lanes": None}], radius_m=500
    )
    assert result == only_primary


def test_emergency_corridor_proxy_closer_major_road_is_worse():
    close = compute_emergency_corridor_proxy_raw(
        [{"highway": "primary", "distance_m": 50, "lanes": None}]
    )
    far = compute_emergency_corridor_proxy_raw(
        [{"highway": "primary", "distance_m": 400, "lanes": None}]
    )
    assert close > far


# --------------------------------------------------------------------------
# Spatial bucketing / nearest lookup
# --------------------------------------------------------------------------


def test_bucket_key_groups_nearby_points_together():
    assert bucket_key(40.7050, -73.9050) == bucket_key(40.7051, -73.9051)


def test_nearby_segments_with_distance_finds_segment_in_neighboring_bucket():
    # Place a segment just across a bucket boundary from the query point.
    # bucket_size_deg default is 0.02; put query point near a boundary and
    # the segment just on the other side.
    segments = [{"highway": "primary", "lanes": None, "lat": 40.700 + 0.019, "lon": -73.900}]
    index = index_segments(segments)
    # Query point is close in real distance but its own bucket differs.
    results = nearby_segments_with_distance(40.700, -73.900, index, max_radius_m=5000)
    assert len(results) == 1
    assert "distance_m" in results[0]


def test_nearby_segments_with_distance_respects_radius():
    segments = [{"highway": "primary", "lanes": None, "lat": 40.700, "lon": -73.900}]
    index = index_segments(segments)
    far_query_lat = 40.700 + 0.5  # far away
    results = nearby_segments_with_distance(far_query_lat, -73.900, index, max_radius_m=100)
    assert results == []


def test_nearest_segment_picks_minimum_distance():
    segments = [
        {"highway": "primary", "distance_m": 300},
        {"highway": "residential", "distance_m": 50},
    ]
    nearest = nearest_segment(segments)
    assert nearest["highway"] == "residential"
    assert nearest_segment([]) is None


# --------------------------------------------------------------------------
# Sanity check against the actual consumer (scoring/engine.py) — mirrors
# tests/test_scoring_engine.py's test_emergency_corridor_dampened_by_side_street
# so our raw-value scale/direction choices make sense downstream.
# --------------------------------------------------------------------------


def test_our_raw_values_behave_correctly_in_scoring_engine():
    # A cell right next to a primary road, classified as facing it.
    facing_row = {
        "congestion_proxy_raw": compute_congestion_proxy_raw(
            [{"highway": "primary", "distance_m": 30, "lanes": None}]
        ),
        "emergency_corridor_proxy_raw": compute_emergency_corridor_proxy_raw(
            [{"highway": "primary", "distance_m": 30, "lanes": None}]
        ),
        "street_orientation": derive_street_orientation("primary"),
    }
    # A cell on a quiet residential side street, same distance to the same
    # primary road (so same raw emergency proxy before damping), but the
    # *nearest* segment is the residential street it's actually on.
    side_street_row = {
        "congestion_proxy_raw": compute_congestion_proxy_raw(
            [{"highway": "primary", "distance_m": 30, "lanes": None}]
        ),
        "emergency_corridor_proxy_raw": compute_emergency_corridor_proxy_raw(
            [{"highway": "primary", "distance_m": 30, "lanes": None}]
        ),
        "street_orientation": derive_street_orientation("residential"),
    }
    assert facing_row["street_orientation"] == "facing_corridor"
    assert side_street_row["street_orientation"] == "side_street"

    facing_goodness = compute_raw_goodness(facing_row, spec("emergency_corridor_score"))
    side_goodness = compute_raw_goodness(side_street_row, spec("emergency_corridor_score"))
    # Side street's penalty is dampened (halved), so its "goodness" (negated
    # penalty) should be higher/less-negative than the facing-corridor cell.
    assert side_goodness > facing_goodness

    # And the road (congestion) category — unaffected by street_orientation
    # — should be identical for both since congestion_proxy_raw was equal.
    road_facing = compute_raw_goodness(facing_row, spec("road_score"))
    road_side = compute_raw_goodness(side_street_row, spec("road_score"))
    assert road_facing == road_side


def test_empty_area_yields_zero_proxies_and_unknown_orientation():
    assert compute_congestion_proxy_raw([]) == 0.0
    assert compute_emergency_corridor_proxy_raw([]) == 0.0
    assert derive_street_orientation(None) == "unknown"
