import random

from common.geo import haversine_m
from ingestion.osm_poi import (
    BUCKET_DEG,
    build_bucket_index,
    build_overpass_query,
    candidates_near,
    categorize_poi,
    compute_cell_features,
    group_pois_by_category,
    nearest_and_count,
    nearest_and_count_indexed,
    parse_overpass_response,
)

# A fixed cell near midtown Manhattan, used across several tests.
CELL_LAT, CELL_LON = 40.7549, -73.9840


# --------------------------------------------------------------------------
# categorize_poi
# --------------------------------------------------------------------------


def test_categorize_supermarket_and_grocery_as_grocery():
    assert categorize_poi({"shop": "supermarket"}) == "grocery"
    assert categorize_poi({"shop": "grocery"}) == "grocery"


def test_categorize_convenience_store_is_not_grocery():
    # PROJECT.md: convenience stores are their own negative-signal category,
    # not a grocery synonym — a single POI must never count as both.
    assert categorize_poi({"shop": "convenience"}) == "convenience_store"
    assert categorize_poi({"shop": "kiosk"}) == "convenience_store"


def test_categorize_gym_cafe_gas_station():
    assert categorize_poi({"leisure": "fitness_centre"}) == "gym"
    assert categorize_poi({"amenity": "cafe"}) == "cafe"
    assert categorize_poi({"amenity": "fuel"}) == "gas_station"


def test_categorize_unmatched_tags_returns_none():
    assert categorize_poi({"shop": "bakery"}) is None
    assert categorize_poi({}) is None


def test_categorize_extra_tags_dont_interfere():
    # A POI can carry unrelated tags alongside the one that matters.
    tags = {"shop": "supermarket", "name": "Trader Joe's", "brand": "Trader Joe's"}
    assert categorize_poi(tags) == "grocery"


# --------------------------------------------------------------------------
# parse_overpass_response
# --------------------------------------------------------------------------


def test_parse_overpass_response_node():
    data = {
        "elements": [
            {"type": "node", "id": 1, "lat": 40.75, "lon": -73.98, "tags": {"shop": "supermarket"}},
        ]
    }
    pois = parse_overpass_response(data)
    assert pois == [(40.75, -73.98, {"shop": "supermarket"})]


def test_parse_overpass_response_way_uses_center():
    data = {
        "elements": [
            {
                "type": "way",
                "id": 2,
                "center": {"lat": 40.76, "lon": -73.99},
                "tags": {"amenity": "fuel"},
            },
        ]
    }
    pois = parse_overpass_response(data)
    assert pois == [(40.76, -73.99, {"amenity": "fuel"})]


def test_parse_overpass_response_way_without_center_is_skipped():
    data = {"elements": [{"type": "way", "id": 3, "tags": {"amenity": "fuel"}}]}
    assert parse_overpass_response(data) == []


def test_parse_overpass_response_missing_tags_defaults_empty():
    data = {"elements": [{"type": "node", "id": 4, "lat": 40.0, "lon": -74.0}]}
    pois = parse_overpass_response(data)
    assert pois == [(40.0, -74.0, {})]


def test_parse_overpass_response_empty():
    assert parse_overpass_response({}) == []
    assert parse_overpass_response({"elements": []}) == []


# --------------------------------------------------------------------------
# group_pois_by_category
# --------------------------------------------------------------------------


def test_group_pois_by_category():
    pois = [
        (40.75, -73.98, {"shop": "supermarket"}),
        (40.76, -73.99, {"shop": "convenience"}),
        (40.77, -74.00, {"amenity": "cafe"}),
        (40.78, -74.01, {"shop": "bakery"}),  # unmatched, should be dropped
    ]
    grouped = group_pois_by_category(pois)
    assert grouped["grocery"] == [(40.75, -73.98)]
    assert grouped["convenience_store"] == [(40.76, -73.99)]
    assert grouped["cafe"] == [(40.77, -74.00)]
    assert grouped["gym"] == []
    assert grouped["gas_station"] == []
    # unmatched POI doesn't silently end up in any bucket
    assert sum(len(v) for v in grouped.values()) == 3


# --------------------------------------------------------------------------
# build_overpass_query
# --------------------------------------------------------------------------


def test_build_overpass_query_contains_bbox_and_tag_filters():
    query = build_overpass_query(40.49, 40.92, -74.26, -73.70)
    assert "40.49,-74.26,40.92,-73.7" in query
    assert 'node["shop"="supermarket"]' in query
    assert 'way["shop"="supermarket"]' in query
    assert 'node["amenity"="fuel"]' in query
    assert 'node["shop"="convenience"]' in query
    assert "out center;" in query
    assert query.strip().startswith("[out:json]")


# --------------------------------------------------------------------------
# nearest_and_count (brute-force ground truth)
# --------------------------------------------------------------------------


def test_nearest_and_count_empty():
    assert nearest_and_count(CELL_LAT, CELL_LON, []) == (0, None)


def test_nearest_and_count_basic():
    # One POI ~111m north (0.001 deg lat), one POI far away (~11km north).
    close = (CELL_LAT + 0.001, CELL_LON)
    far = (CELL_LAT + 0.1, CELL_LON)
    coords = [close, far]
    count, nearest = nearest_and_count(CELL_LAT, CELL_LON, coords, radius_m=500.0)
    expected_nearest = haversine_m(CELL_LAT, CELL_LON, *close)
    assert count == 1  # only `close` is within 500m
    assert nearest is not None
    assert abs(nearest - expected_nearest) < 1e-6


def test_nearest_and_count_all_within_radius():
    coords = [(CELL_LAT + 0.0005, CELL_LON), (CELL_LAT - 0.0005, CELL_LON)]
    count, nearest = nearest_and_count(CELL_LAT, CELL_LON, coords, radius_m=500.0)
    assert count == 2
    assert nearest is not None and nearest > 0


def test_nearest_and_count_none_within_radius_but_nearest_still_reported():
    far = (CELL_LAT + 0.1, CELL_LON)
    count, nearest = nearest_and_count(CELL_LAT, CELL_LON, [far], radius_m=500.0)
    assert count == 0
    assert nearest is not None and nearest > 500.0


# --------------------------------------------------------------------------
# bucket index + indexed nearest/count
# --------------------------------------------------------------------------


def test_build_bucket_index_groups_by_bucket():
    coords = [(40.75, -73.98), (40.751, -73.981), (41.5, -72.0)]
    index = build_bucket_index(coords, bucket_deg=BUCKET_DEG)
    # first two points fall in the same (or adjacent) bucket, far one doesn't
    assert sum(len(v) for v in index.values()) == 3
    assert len(index) <= 3


def test_candidates_near_returns_nearby_points_only():
    close = (CELL_LAT + 0.001, CELL_LON)
    far = (CELL_LAT + 5.0, CELL_LON)  # ~550km away, different bucket entirely
    index = build_bucket_index([close, far])
    candidates = candidates_near(index, CELL_LAT, CELL_LON, ring=1)
    assert close in candidates
    assert far not in candidates


def test_nearest_and_count_indexed_matches_brute_force_dense():
    random.seed(42)
    coords = [
        (CELL_LAT + random.uniform(-0.01, 0.01), CELL_LON + random.uniform(-0.01, 0.01))
        for _ in range(200)
    ]
    index = build_bucket_index(coords)
    brute = nearest_and_count(CELL_LAT, CELL_LON, coords)
    indexed = nearest_and_count_indexed(CELL_LAT, CELL_LON, coords, index)
    assert indexed == brute


def test_nearest_and_count_indexed_falls_back_correctly_when_sparse():
    # No POI within the fast-path window's guaranteed radius (500m) — the
    # true nearest is a single point ~2km away. Fast path should still find
    # it via fallback to a full scan, not report None/wrong distance.
    lone = (CELL_LAT + 0.02, CELL_LON)  # ~2.2km away
    coords = [lone]
    index = build_bucket_index(coords)
    brute = nearest_and_count(CELL_LAT, CELL_LON, coords)
    indexed = nearest_and_count_indexed(CELL_LAT, CELL_LON, coords, index)
    assert indexed == brute
    assert indexed[0] == 0  # not within 500m
    assert indexed[1] is not None and indexed[1] > 500.0


def test_nearest_and_count_indexed_empty_coords():
    index = build_bucket_index([])
    assert nearest_and_count_indexed(CELL_LAT, CELL_LON, [], index) == (0, None)


# --------------------------------------------------------------------------
# compute_cell_features
# --------------------------------------------------------------------------


def test_compute_cell_features_all_columns_present():
    pois_by_category = {
        "grocery": [(CELL_LAT + 0.001, CELL_LON)],
        "gym": [],
        "cafe": [(CELL_LAT + 0.0005, CELL_LON), (CELL_LAT - 0.0005, CELL_LON)],
        "gas_station": [],
        "convenience_store": [(CELL_LAT + 0.2, CELL_LON)],  # far away
    }
    features = compute_cell_features(CELL_LAT, CELL_LON, pois_by_category)

    assert features["grocery_count_500m"] == 1
    assert features["grocery_nearest_m"] is not None
    assert features["gym_count_500m"] == 0
    assert features["gym_nearest_m"] is None
    assert features["cafe_count_500m"] == 2
    assert features["gas_station_count_500m"] == 0
    assert features["gas_station_nearest_m"] is None
    assert features["convenience_store_count_500m"] == 0
    assert features["convenience_store_nearest_m"] is not None
    assert features["convenience_store_nearest_m"] > 500.0

    # exactly the 10 feature_store columns this job owns, nothing more/less
    assert set(features) == {
        "grocery_count_500m", "grocery_nearest_m",
        "gym_count_500m", "gym_nearest_m",
        "cafe_count_500m", "cafe_nearest_m",
        "gas_station_count_500m", "gas_station_nearest_m",
        "convenience_store_count_500m", "convenience_store_nearest_m",
    }


def test_compute_cell_features_indexed_matches_unindexed():
    random.seed(7)
    pois_by_category = {
        "grocery": [
            (CELL_LAT + random.uniform(-0.02, 0.02), CELL_LON + random.uniform(-0.02, 0.02))
            for _ in range(50)
        ],
        "gym": [],
        "cafe": [(CELL_LAT + 0.0003, CELL_LON)],
        "gas_station": [(CELL_LAT + 0.05, CELL_LON)],
        "convenience_store": [],
    }
    indexes = {cat: build_bucket_index(coords) for cat, coords in pois_by_category.items()}

    unindexed = compute_cell_features(CELL_LAT, CELL_LON, pois_by_category)
    indexed = compute_cell_features(CELL_LAT, CELL_LON, pois_by_category, indexes=indexes)
    assert unindexed == indexed


def test_compute_cell_features_missing_category_key_treated_as_empty():
    features = compute_cell_features(CELL_LAT, CELL_LON, {"grocery": [(CELL_LAT, CELL_LON)]})
    assert features["grocery_count_500m"] == 1
    assert features["gym_count_500m"] == 0
    assert features["gym_nearest_m"] is None
