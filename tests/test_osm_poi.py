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
    # docs/ROADMAP.md: convenience stores are their own negative-signal category,
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

    # exactly the feature_store columns this job owns, nothing more/less
    assert set(features) == {
        "restaurant_count_500m",
        "restaurant_nearest_m",
        "bar_count_500m",
        "bar_nearest_m",
        "whole_foods_nearest_m",
        "starbucks_nearest_m",
        "target_nearest_m",
        "premium_retail_raw",
        "grocery_count_500m",
        "grocery_nearest_m",
        "gym_count_500m",
        "gym_nearest_m",
        "cafe_count_500m",
        "cafe_nearest_m",
        "gas_station_count_500m",
        "gas_station_nearest_m",
        "convenience_store_count_500m",
        "convenience_store_nearest_m",
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


# --------------------------------------------------------------------------
# v2: restaurants, bars, brands, premium_retail_raw, split path
# --------------------------------------------------------------------------

import httpx
import pytest

from common import overpass
from ingestion.osm_poi import (
    categorize_poi_all,
    extract_places,
    fetch_pois_for_bbox,
    premium_retail_raw,
)


def test_restaurant_vs_fast_food():
    assert categorize_poi({"amenity": "restaurant"}) == "restaurant"
    assert categorize_poi({"amenity": "fast_food"}) is None
    assert categorize_poi_all({"amenity": "fast_food", "name": "Shake Shack"}) == []


@pytest.mark.parametrize("value", ["bar", "pub", "biergarten"])
def test_bar_pub_biergarten(value):
    assert categorize_poi({"amenity": value}) == "bar"


def test_brand_by_wikidata_is_non_exclusive():
    wf = {"shop": "supermarket", "brand:wikidata": "Q1809448", "name": "Whole Foods Market"}
    assert categorize_poi_all(wf) == ["grocery", "whole_foods"]
    sb = {"amenity": "cafe", "brand:wikidata": "Q37158"}
    assert categorize_poi_all(sb) == ["cafe", "starbucks"]
    # Target tagged as department_store: no base category, brand only.
    assert categorize_poi_all({"shop": "department_store", "brand:wikidata": "Q1046951"}) == [
        "target"
    ]


def test_brand_name_fallback_case_insensitive_and_restricted():
    assert categorize_poi_all({"shop": "supermarket", "name": "WHOLE FOODS"}) == [
        "grocery",
        "whole_foods",
    ]
    assert categorize_poi_all({"amenity": "cafe", "brand": "starbucks"}) == ["cafe", "starbucks"]
    assert categorize_poi_all({"shop": "department_store", "name": "Target"}) == ["target"]
    # Not shop/cafe -> no name fallback
    assert categorize_poi_all({"amenity": "restaurant", "name": "Starbucks"}) == ["restaurant"]
    # Different brand's wikidata wins over a coincidental name
    assert categorize_poi_all(
        {"shop": "supermarket", "name": "Target", "brand:wikidata": "Q1"}
    ) == ["grocery"]
    # Exact match only
    assert categorize_poi_all({"shop": "mall", "name": "Target Center Mall"}) == []


def test_group_double_counts_brand_and_base():
    pois = [
        (40.0, -73.0, {"shop": "supermarket", "brand:wikidata": "Q1809448"}),
        (40.1, -73.1, {"amenity": "cafe", "name": "Starbucks"}),
        (40.2, -73.2, {"amenity": "fast_food"}),
    ]
    g = group_pois_by_category(pois)
    assert g["grocery"] == [(40.0, -73.0)] and g["whole_foods"] == [(40.0, -73.0)]
    assert g["cafe"] == g["starbucks"] == [(40.1, -73.1)]
    assert g["restaurant"] == [] and g["target"] == []


def test_premium_retail_raw():
    assert premium_retail_raw(None, None, None) is None
    assert premium_retail_raw(0.0, 0.0, 0.0) == pytest.approx(2.5)
    assert premium_retail_raw(None, 800.0, None) == pytest.approx(0.5)
    assert premium_retail_raw(800.0, None, 800.0) == pytest.approx(0.5 + 0.25)
    assert premium_retail_raw(None, None, 1600.0) == pytest.approx(0.5 / 3)


def test_compute_cell_features_v2_columns():
    pois = {c: [] for c in ("grocery", "gym", "cafe", "gas_station", "convenience_store")}
    pois["restaurant"] = [(CELL_LAT, CELL_LON)] * 2
    pois["bar"] = []
    pois["starbucks"] = [(CELL_LAT, CELL_LON)]
    f = compute_cell_features(CELL_LAT, CELL_LON, pois)
    assert f["restaurant_count_500m"] == 2 and f["restaurant_nearest_m"] == 0.0
    assert f["bar_count_500m"] == 0 and f["bar_nearest_m"] is None
    assert f["starbucks_nearest_m"] == 0.0
    assert f["whole_foods_nearest_m"] is None and f["target_nearest_m"] is None
    assert f["premium_retail_raw"] == pytest.approx(1.0)


def test_query_includes_v2_statements():
    q = build_overpass_query(40.0, 41.0, -74.0, -73.0)
    assert '"amenity"="restaurant"' in q and '"amenity"="biergarten"' in q
    assert "fast_food" not in q
    for qid in ("Q1809448", "Q37158", "Q1046951"):
        assert qid in q


def _el(i):
    return {"type": "node", "id": i, "lat": 40.0, "lon": -73.0, "tags": {"amenity": "bar"}}


def test_split_path_on_timeout_dedupes(monkeypatch):
    monkeypatch.setattr(overpass.time, "sleep", lambda s: None)
    monkeypatch.setattr("ingestion.osm_poi.post_overpass_query", None, raising=False)
    calls = []

    def fake_post(query, timeout):
        calls.append(query)
        if len(calls) == 1:
            raise httpx.ReadTimeout("too big")
        return {"elements": [_el(1), _el(len(calls))]}  # id 1 straddles quadrants

    monkeypatch.setattr("ingestion.osm_poi.post_overpass_query", fake_post)
    pois = fetch_pois_for_bbox(40.0, 41.0, -74.0, -73.0)
    assert len(calls) == 5
    assert len(pois) == 5  # id 1 once + 4 distinct


def test_split_gives_up_at_max_depth(monkeypatch):
    monkeypatch.setattr(overpass.time, "sleep", lambda s: None)
    n = []

    def always_fail(*bbox):
        n.append(bbox)
        raise httpx.ReadTimeout("x")

    with pytest.raises(httpx.ReadTimeout):
        overpass.fetch_with_quadrant_split(always_fail, 0, 1, 0, 1, max_depth=1)
    assert len(n) == 2  # root + first sub-tile, which re-raises


def test_merge_overpass_elements_keeps_idless():
    m = overpass.merge_overpass_elements(
        [{"elements": [_el(1), {"type": "node"}]}, {"elements": [_el(1)]}]
    )
    assert len(m["elements"]) == 2


def test_extract_places():
    data = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 40.1,
                "lon": -73.1,
                "tags": {"amenity": "cafe", "name": "  Joe's   Cafe "},
            },
            {
                "type": "way",
                "id": 2,
                "center": {"lat": 40.2, "lon": -73.2},
                "tags": {
                    "shop": "supermarket",
                    "name": "Whole Foods Market",
                    "brand": "Whole Foods",
                    "brand:wikidata": "Q1809448",
                },
            },
            {"type": "node", "id": 3, "lat": 40.3, "lon": -73.3, "tags": {"amenity": "bar"}},
            {
                "type": "node",
                "id": 4,
                "lat": 40.3,
                "lon": -73.3,
                "tags": {"amenity": "bar", "name": "   "},
            },
            {"type": "way", "id": 5, "tags": {"amenity": "bar", "name": "No Center"}},
        ]
    }
    places = extract_places(data)
    assert [(p.source_id, p.category) for p in places] == [
        ("node/1", "cafe"),
        ("way/2", "grocery"),
        ("way/2", "whole_foods"),
    ]
    assert places[0].name == "Joe's Cafe" and places[0].source == "osm"
    assert places[0].brand is None
    assert (places[1].latitude, places[1].longitude) == (40.2, -73.2)
    assert places[1].brand == "Whole Foods"
