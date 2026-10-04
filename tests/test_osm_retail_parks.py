"""Shopping and parks features: parsing, footprints, curves, per-cell math.
No network or database."""

import math

import pytest

from common.db import FEATURE_STORE_COLUMNS
from ingestion import osm_retail_parks as rp

LAT, LON = 40.7000, -73.9900
FT = 3.280839895


def lat_off(feet):
    return feet / FT / 111_320.0


def shop(dlat_ft, group="apparel"):
    return (LAT + lat_off(dlat_ft), LON, group)


def square_park(center_dlat_ft, half_ft, area=None):
    """A footprint rectangle centred north of the cell (the shrink is already applied)."""
    c = LAT + lat_off(center_dlat_ft)
    h = lat_off(half_ft)
    w = half_ft / FT / (111_320.0 * math.cos(math.radians(LAT)))
    return (c - h, LON - w, c + h, LON + w, area if area is not None else (2 * half_ft) ** 2)


def test_query_covers_shops_parks_and_requests_bounds():
    q = rp.build_overpass_query(40.5, 40.9, -74.3, -73.7)
    assert "out center bb tags;" in q
    assert '["shop"~"^(' in q and "department_store" in q and "doityourself" in q
    assert "supermarket" not in q and "convenience" not in q  # scored by other factors
    assert "park|playground|nature_reserve|garden" in q and "recreation_ground" in q
    assert q.count("(40.5,-74.3,40.9,-73.7)") == 3


def test_is_park_and_retail_group():
    assert rp.is_park({"leisure": "park"}) and rp.is_park({"landuse": "recreation_ground"})
    assert rp.is_park({"leisure": "garden"})
    assert not rp.is_park({"leisure": "park", "access": "private"})
    assert not rp.is_park({"leisure": "pitch"}) and not rp.is_park({"shop": "clothes"})
    assert rp.retail_group({"shop": "mall"}) == "department"
    assert rp.retail_group({"shop": "chemist"}) == "personal_care"
    assert rp.retail_group({"shop": "supermarket"}) is None
    assert rp.retail_group({}) is None
    assert rp.RETAIL_GROUP_COUNT == 6


def test_footprint_rect_shrinks_bbox_and_estimates_area():
    bounds = {"minlat": 40.60, "minlon": -74.00, "maxlat": 40.62, "maxlon": -73.98}
    min_lat, _, max_lat, _, area = rp.footprint_rect((40.61, -73.99), bounds)
    assert (min_lat + max_lat) / 2 == pytest.approx(40.61)
    assert (max_lat - min_lat) == pytest.approx(0.02 * math.sqrt(rp.PARK_FILL_FACTOR))
    full = 0.02 * 111_320 * FT * 0.02 * 111_320 * math.cos(math.radians(40.61)) * FT
    assert area == pytest.approx(full * rp.PARK_FILL_FACTOR, rel=1e-6)
    # a node has no area and no extent
    assert rp.footprint_rect((40.61, -73.99), None) == (40.61, -73.99, 40.61, -73.99, 0.0)
    assert rp.footprint_rect((1.0, 2.0), {"minlat": 1})[4] == 0.0


ELEMENTS = {
    "elements": [
        {
            "type": "node",
            "id": 1,
            "lat": 40.7,
            "lon": -73.99,
            "tags": {"shop": "clothes", "name": "Gap", "brand": "Gap"},
        },
        {
            "type": "way",
            "id": 2,
            "center": {"lat": 40.701, "lon": -73.991},
            "tags": {"shop": "mall", "name": "  City   Mall "},
        },
        {"type": "node", "id": 3, "lat": 40.7, "lon": -73.98, "tags": {"shop": "books"}},  # unnamed
        {
            "type": "node",
            "id": 4,
            "lat": 40.7,
            "lon": -73.97,
            "tags": {"shop": "supermarket", "name": "X"},
        },
        {
            "type": "relation",
            "id": 5,
            "tags": {"leisure": "park", "name": "Big Park"},
            "bounds": {"minlat": 40.70, "minlon": -73.99, "maxlat": 40.71, "maxlon": -73.98},
        },
        {
            "type": "node",
            "id": 6,
            "lat": 40.71,
            "lon": -73.97,
            "tags": {"leisure": "playground", "name": "Tot Lot"},
        },
        {"type": "way", "id": 7, "tags": {"leisure": "park", "name": "No Geometry"}},
        {
            "type": "way",
            "id": 8,
            "center": {"lat": 40.7, "lon": -73.9},
            "bounds": {"minlat": 40.69, "minlon": -73.91, "maxlat": 40.71, "maxlon": -73.89},
            "tags": {"leisure": "park", "access": "private", "name": "Private Garden"},
        },
    ]
}


def test_parse_elements_splits_shops_parks_and_named_places():
    shops, parks, shop_places, park_places = rp.parse_elements(ELEMENTS)
    assert [(s[2]) for s in shops] == ["apparel", "department", "general"]
    assert len(parks) == 2  # Big Park (from bounds) and the Tot Lot; private + no-geometry skipped
    assert parks[1][4] == 0.0 and parks[0][4] > 0
    assert [(p.name, p.category, p.source, p.source_id) for p in shop_places] == [
        ("Gap", "shopping", "osm_retail", "node/1"),
        ("City Mall", "shopping", "osm_retail", "way/2"),
    ]
    assert shop_places[0].brand == "Gap"
    assert [(p.name, p.category, p.source) for p in park_places] == [
        ("Big Park", "park", "osm_parks"),
        ("Tot Lot", "park", "osm_parks"),
    ]
    # the sources never collide with ingestion.osm_poi's 'osm' rows
    assert not any(p.source == "osm" for p in [*shop_places, *park_places])


def test_linear_curve():
    assert rp.linear_curve(0, 100, 500) == 1.0
    assert rp.linear_curve(100, 100, 500) == 1.0
    assert rp.linear_curve(300, 100, 500) == pytest.approx(0.5)
    assert rp.linear_curve(500, 100, 500) == 0.0
    assert rp.linear_curve(9999, 100, 500) == 0.0


def test_shopping_raw_combines_proximity_and_variety():
    assert rp.shopping_raw(None, 3) is None
    best = rp.shopping_raw(100.0, rp.RETAIL_GROUP_COUNT)
    assert best == pytest.approx(1.0)
    far_varied = rp.shopping_raw(40_000.0, rp.RETAIL_GROUP_COUNT)
    close_dull = rp.shopping_raw(100.0, 0)
    assert far_varied == pytest.approx(0.4) and close_dull == pytest.approx(0.6)
    assert rp.shopping_raw(100.0, 99) == pytest.approx(1.0)  # variety is capped


def test_park_size_score_is_log_scaled_and_clamped():
    assert rp.park_size_score(None) == 0.0 and rp.park_size_score(0) == 0.0
    assert rp.park_size_score(1000) == 0.0  # below a pocket park
    assert rp.park_size_score(20 * rp.SQ_FT_PER_ACRE) == 1.0
    assert rp.park_size_score(1e9) == 1.0
    mid = rp.park_size_score(2 * rp.SQ_FT_PER_ACRE)
    assert 0.4 < mid < 0.6  # 2 acres is about half way in log space
    assert rp.park_size_score(1 * rp.SQ_FT_PER_ACRE) < mid


def test_recreation_raw_weights_proximity_over_size():
    assert rp.recreation_raw(None, 5e5) is None
    assert rp.recreation_raw(0.0, 25 * rp.SQ_FT_PER_ACRE) == pytest.approx(1.0)
    pocket_next_door = rp.recreation_raw(0.0, None)
    big_but_far = rp.recreation_raw(5000.0, 25 * rp.SQ_FT_PER_ACRE)
    assert pocket_next_door == pytest.approx(2 / 3)
    assert big_but_far == pytest.approx(1 / 3)
    assert pocket_next_door > big_but_far


def test_distance_to_rect_is_zero_inside_and_edge_distance_outside():
    rect = square_park(1000, 500)  # spans 500..1500 ft north of the cell
    assert rp.distance_to_rect_ft(LAT, LON, rect) == pytest.approx(500, rel=0.01)
    inside = rp.distance_to_rect_ft(LAT + lat_off(1000), LON, rect)
    assert inside == 0.0


def test_grid_index_finds_items_and_dedupes_multi_bucket_footprints():
    idx = rp.GridIndex()
    wide = (LAT - 0.02, LON - 0.02, LAT + 0.02, LON + 0.02, 1.0)  # spans several buckets
    idx.add(wide, *wide[:4])
    idx.add("far", 45.0, -70.0, 45.0, -70.0)
    found = idx.near(LAT, LON, 2)
    assert found == [wide]  # once, not once per bucket
    assert idx.near(45.0, -70.0, 1) == ["far"]
    assert idx.count == 2


def test_huge_footprints_go_to_the_linear_list_and_are_always_candidates():
    idx = rp.GridIndex()
    huge = (39.0, -75.0, 42.0, -72.0, 1e9)
    idx.add(huge, *huge[:4])
    assert idx.big == [huge] and not idx.buckets
    assert idx.near(0.0, 0.0, 1) == [huge]


def test_shop_features_count_nearest_variety_and_kth_distance():
    shops = [
        shop(300, "apparel"), shop(900, "home"), shop(1500, "department"),
        shop(2000, "apparel"), shop(9000, "electronics"),  # beyond a mile (5,280 ft)
    ]  # fmt: skip
    f = rp.shop_features(LAT, LON, rp.build_shop_index(shops))
    assert f["shopping_count_1mi"] == 4
    assert f["shopping_nearest_ft"] == pytest.approx(300, rel=0.01)
    assert f["shopping_variety_count_1mi"] == 3
    expected = rp.shopping_raw(1500, 3)  # 3rd nearest is the 1,500 ft shop
    assert f["shopping_raw"] == pytest.approx(expected, rel=0.01)


def test_shop_features_with_one_shop_far_away_and_with_none():
    far = rp.shop_features(LAT, LON, rp.build_shop_index([shop(60_000, "home")]))
    assert far["shopping_count_1mi"] == 0 and far["shopping_variety_count_1mi"] == 0
    assert far["shopping_nearest_ft"] == pytest.approx(60_000, rel=0.01)
    assert far["shopping_raw"] == pytest.approx(0.0)
    none = rp.shop_features(LAT, LON, rp.GridIndex())
    assert none["shopping_nearest_ft"] is None and none["shopping_raw"] is None
    assert none["shopping_count_1mi"] == 0


def test_shop_features_find_a_third_shop_beyond_the_first_ring():
    shops = [shop(200), shop(400), shop(25_000)]  # ~4.7 mi away, outside ring 2
    f = rp.shop_features(LAT, LON, rp.build_shop_index(shops))
    assert f["shopping_count_1mi"] == 2
    expected = rp.shopping_raw(25_000, 1)
    assert f["shopping_raw"] == pytest.approx(expected, rel=0.01)


def test_park_features_nearest_count_largest_and_raw():
    parks = [
        square_park(1500, 500, area=4e5),   # edge 1,000 ft away
        square_park(2900, 100, area=4e4),   # edge 2,800 ft away (within half a mile)
        square_park(4000, 400, area=9e5),   # edge 3,600 ft away (beyond half a mile, within a mile)
        square_park(9000, 400, area=9e6),   # beyond a mile
    ]  # fmt: skip
    f = rp.park_features(LAT, LON, rp.build_park_index(parks))
    assert f["park_nearest_ft"] == pytest.approx(1000, rel=0.02)
    assert f["park_count_1mi"] == 3
    assert f["park_largest_sq_ft_half_mi"] == 4e5  # the 9e5 park is past half a mile
    assert f["recreation_raw"] == pytest.approx(rp.recreation_raw(f["park_nearest_ft"], 4e5))


def test_park_features_none_nearby_and_none_at_all():
    far = rp.park_features(LAT, LON, rp.build_park_index([square_park(40_000, 500)]))
    assert far["park_count_1mi"] == 0 and far["park_largest_sq_ft_half_mi"] is None
    assert far["park_nearest_ft"] > 30_000 and far["recreation_raw"] == pytest.approx(0.0)
    none = rp.park_features(LAT, LON, rp.GridIndex())
    assert none["park_nearest_ft"] is None and none["recreation_raw"] is None


def test_compute_cell_features_only_emits_known_imperial_columns():
    f = rp.compute_cell_features(
        LAT, LON, rp.build_shop_index([shop(300)]), rp.build_park_index([square_park(500, 100)])
    )
    assert set(f) <= FEATURE_STORE_COLUMNS
    assert set(f) == {
        "shopping_count_1mi", "shopping_nearest_ft", "shopping_variety_count_1mi", "shopping_raw",
        "park_count_1mi", "park_nearest_ft", "park_largest_sq_ft_half_mi", "recreation_raw",
    }  # fmt: skip
    assert not any(c.endswith(("_m", "_500m", "_800m")) for c in f)  # imperial by owner rule


def test_migration_0009_is_additive_idempotent_and_mirrored_in_schema_sql():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "contracts"
    migration = (root / "migrations" / "0009_v2_1.sql").read_text()
    schema = (root / "schema.sql").read_text()
    code = "\n".join(line for line in migration.splitlines() if not line.lstrip().startswith("--"))
    statements = [s for s in code.split(";") if s.strip()]
    assert len(statements) == 3 and all(s.strip().startswith("alter table") for s in statements)
    assert not re.search(r"\b(drop|delete|truncate|rename)\b", code, re.IGNORECASE)
    columns = re.findall(r"add column if not exists (\w+) ", code)
    assert len(columns) == 11 and len(set(columns)) == 11
    for column in columns:
        assert re.search(rf"^\s+{column} ", schema, re.MULTILINE), column
    feature_columns = [c for c in columns if not c.endswith("_score")]
    assert set(feature_columns) <= FEATURE_STORE_COLUMNS
    assert {"shopping_score", "recreation_score", "gas_convenience_score"} == {
        c for c in columns if c.endswith("_score")
    }
    for column in feature_columns:  # imperial units only
        assert not column.endswith(("_m", "_km", "_500m", "_800m", "_1600m")), column
