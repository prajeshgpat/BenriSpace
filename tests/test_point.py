"""scoring/point.py: feature building for an exact point (pure parts and SQL shape)."""

import math

import pytest

from api.areas import point_in_polygon
from common.geo import haversine_m
from ingestion import airports, osm_poi, osm_retail_parks, schools
from scoring import point
from scoring.point import (
    CTR,
    DEFAULT_ANCHOR,
    NO_ANCHOR,
    PT,
    Live,
    anchored_count,
    anchored_nearest,
    build_live_sql,
    build_point_features,
    kth_nearest,
    live_params,
    read_live,
    sample_points,
    school_nearest_in_block,
)

# --- parity with the ingestion functions this module copies ----------------------


def test_constants_match_ingestion():
    assert point.PREMIUM_RETAIL_WEIGHTS == osm_poi.PREMIUM_RETAIL_WEIGHTS
    assert point.PREMIUM_RETAIL_SCALE_M == osm_poi.PREMIUM_RETAIL_SCALE_M
    assert point.SHOP_KTH_NEAREST == osm_retail_parks.SHOP_KTH_NEAREST
    assert point.SHOP_PROX_FULL_FT == osm_retail_parks.SHOP_PROX_FULL_FT
    assert point.SHOP_PROX_ZERO_FT == osm_retail_parks.SHOP_PROX_ZERO_FT
    assert point.SHOP_PROX_WEIGHT == osm_retail_parks.SHOP_PROX_WEIGHT
    assert point.SHOP_VARIETY_WEIGHT == osm_retail_parks.SHOP_VARIETY_WEIGHT
    assert point.RETAIL_GROUP_COUNT == osm_retail_parks.RETAIL_GROUP_COUNT
    assert point.PARK_PROX_FULL_FT == osm_retail_parks.PARK_PROX_FULL_FT
    assert point.PARK_PROX_ZERO_FT == osm_retail_parks.PARK_PROX_ZERO_FT
    assert point.PARK_SIZE_MIN_SQ_FT == osm_retail_parks.PARK_SIZE_MIN_SQ_FT
    assert point.PARK_SIZE_MAX_SQ_FT == osm_retail_parks.PARK_SIZE_MAX_SQ_FT
    assert point.PARK_PROX_WEIGHT == osm_retail_parks.PARK_PROX_WEIGHT
    assert point.PARK_SIZE_WEIGHT == osm_retail_parks.PARK_SIZE_WEIGHT
    assert point.FT_PER_M == osm_retail_parks.FT_PER_M
    assert point.AIRPORT_SPEED_KMH == airports.HaversineFallbackRouter.ASSUMED_AVG_SPEED_KMH
    assert point.AIRPORTS == tuple((a.code, a.lat, a.lon) for a in airports.TIER1_AIRPORTS)
    assert point.SCHOOL_LAT_BUCKET_DEG == schools.LAT_BUCKET_DEG
    assert point.SCHOOL_LON_BUCKET_DEG == schools.LON_BUCKET_DEG


def test_formulas_match_ingestion():
    for wf in (None, 0.0, 120.0, 4000.0):
        for sb in (None, 300.0, 9000.0):
            for tg in (None, 50.0):
                assert point.premium_retail_raw(wf, sb, tg) == osm_poi.premium_retail_raw(
                    wf, sb, tg
                )
    for kth in (None, 0, 2640, 3000, 10_000, 31_680, 40_000):
        for variety in (0, 1, 3, 6):
            assert point.shopping_raw(kth, variety) == osm_retail_parks.shopping_raw(kth, variety)
    for nearest in (None, 0, 500, 1015, 2500, 4062, 9000):
        for area in (None, 0, 4000, 50_000, 500_000, 2_000_000):
            assert point.recreation_raw(nearest, area) == osm_retail_parks.recreation_raw(
                nearest, area
            )


def test_airport_time_matches_the_ingestion_fallback():
    for lat, lon in ((40.672, -73.978), (41.4, -73.3), (42.0, -74.5)):
        _, minutes = airports.nearest_airport(lat, lon, airports.HaversineFallbackRouter())
        assert point.airport_drive_time_min(lat, lon) == pytest.approx(minutes)


def test_school_block_rule_matches_ingestion():
    school_pts = [(40.70, -73.99), (40.71, -73.97), (40.80, -73.90), (40.60, -74.10)]
    recs = [schools.SchoolRecord(lat=la, lon=lo, **_school_kwargs()) for la, lo in school_pts]
    index = schools.build_spatial_index(recs)
    for lat, lon in ((40.705, -73.985), (40.79, -73.91), (40.5, -73.5), (40.72, -73.60)):
        expected = schools.compute_cell_aggregate(lat, lon, index)["school_nearest_m"]
        ranked = sorted(school_pts, key=lambda p: haversine_m(lat, lon, *p))[:6]
        live = Live(
            0,
            tuple(haversine_m(lat, lon, *p) for p in ranked),
            tuple(ranked),
        )
        got = school_nearest_in_block(live, lat, lon)
        if expected is None:
            assert got is None
        else:
            assert got == pytest.approx(expected, abs=0.1)


def _school_kwargs():
    import dataclasses

    fields = {f.name: f for f in dataclasses.fields(schools.SchoolRecord)}
    extra = {}
    for name, f in fields.items():
        if name in ("lat", "lon"):
            continue
        extra[name] = "x" if f.type in (str, "str") else None
    return extra


# --- anchoring helpers --------------------------------------------------------------


def test_anchored_nearest_shifts_and_clips():
    assert anchored_nearest(100.0, 150.0, 120.0, offset=500) == 130.0
    assert anchored_nearest(100.0, 1000.0, 0.0, offset=50) == 150.0  # clipped to offset
    assert anchored_nearest(100.0, 0.0, 1000.0, offset=50) == 50.0
    assert anchored_nearest(10.0, 0.0, 400.0, offset=300) == 0.0  # never negative
    assert anchored_nearest(None, 77.0, 1.0, offset=10) == 77.0
    assert anchored_nearest(100.0, None, 5.0, offset=10) == 100.0
    assert anchored_nearest(100.0, 150.0, 120.0, offset=500, weight=0.5) == 115.0


def test_anchored_count():
    assert anchored_count(4, 6, 5) == 5.0
    assert anchored_count(1, 0, 3) == 0.0
    assert anchored_count(None, 3, 9) == 3.0


def test_kth_nearest():
    assert kth_nearest(Live(0, ())) is None
    assert kth_nearest(Live(0, (10.0, 20.0))) == 20.0
    assert kth_nearest(Live(0, (10.0, 20.0, 30.0, 40.0))) == 30.0


# --- feature building ---------------------------------------------------------------

CELL = {
    "latitude": 40.70,
    "longitude": -73.99,
    "grocery_count_500m": 3,
    "grocery_nearest_m": 120.0,
    "gym_count_500m": 0,
    "gym_nearest_m": 900.0,
    "cafe_count_500m": 5,
    "cafe_nearest_m": 60.0,
    "restaurant_count_500m": 20,
    "restaurant_nearest_m": 25.0,
    "bar_count_500m": 2,
    "bar_nearest_m": 200.0,
    "gas_station_count_500m": 1,
    "gas_station_nearest_m": 300.0,
    "convenience_store_count_500m": 2,
    "convenience_store_nearest_m": 90.0,
    "transit_stop_count_800m": 8,
    "transit_nearest_m": 140.0,
    "school_count_1600m": 3,
    "school_nearest_m": 500.0,
    "shopping_raw": 0.8,
    "shopping_variety_count_1mi": 3,
    "shopping_nearest_ft": 400.0,
    "park_nearest_ft": 1500.0,
    "park_largest_sq_ft_half_mi": 200_000.0,
    "congestion_proxy_raw": 12.0,
    "emergency_corridor_facility_raw": 9.0,
    "street_orientation": "side_street",
    "school_avg_rating_1600m": 70.0,
    "running_trail_count_800m": 1,
    "running_trail_nearest_m": 600.0,
}


def live_like_cell(offset_m=None):
    """A live map whose measurements equal the cell's stored numbers (+ optional offset
    for the point), as if places held every element."""
    m = {}
    for cat, (cc, nc) in {**point.LIVE_PLAIN, **point.LIVE_ANCHORED}.items():
        for kind in (PT, CTR):
            d = CELL[nc] + (offset_m if (offset_m and kind == PT) else 0.0)
            m[(0, kind, cat)] = Live(CELL[cc], (d,), ((40.70, -73.99),))
    ft = 0.3048
    for kind in (PT, CTR):
        extra = offset_m if (offset_m and kind == PT) else 0.0
        m[(0, kind, "park")] = Live(1, (CELL["park_nearest_ft"] * ft + extra,))
        m[(0, kind, "shopping")] = Live(5, (CELL["shopping_nearest_ft"] * ft, 300.0, 700.0 + extra))
    for brand in ("whole_foods", "starbucks", "target"):
        m[(0, PT, brand)] = Live(0, (1000.0,))
    return m


def test_point_at_centroid_reproduces_stored_for_anchored_categories():
    live = live_like_cell()
    # a different live picture than stored, identical at point and centroid -> no shift
    live[(0, PT, "grocery")] = Live(1, (999.0,))
    live[(0, CTR, "grocery")] = Live(1, (999.0,))
    row = build_point_features(CELL, 40.70, -73.99, live, 0, DEFAULT_ANCHOR).row
    assert row["grocery_count_500m"] == 3.0
    assert row["grocery_nearest_m"] == 120.0
    assert row["transit_nearest_m"] == 140.0
    assert row["park_nearest_ft"] == pytest.approx(1500.0)


def test_point_away_from_centroid_shifts_by_live_delta():
    lat = 40.70 + 0.002  # ~222 m north
    live = live_like_cell(offset_m=50.0)
    row = build_point_features(CELL, lat, -73.99, live, 0, DEFAULT_ANCHOR).row
    assert row["grocery_nearest_m"] == pytest.approx(170.0)
    assert row["transit_nearest_m"] == pytest.approx(190.0)
    # parks shift by PARK_SHIFT_WEIGHT of the live change
    assert row["park_nearest_ft"] == pytest.approx(
        1500.0 + 50.0 * 3.280839895 * point.PARK_SHIFT_WEIGHT
    )


def test_no_anchor_uses_live_values_directly():
    live = live_like_cell()
    live[(0, PT, "grocery")] = Live(7, (33.0,))
    row = build_point_features(CELL, 40.70, -73.99, live, 0, NO_ANCHOR).row
    assert row["grocery_count_500m"] == 7
    assert row["grocery_nearest_m"] == 33.0
    assert row["park_nearest_ft"] == pytest.approx(1500.0)  # live park value


def test_cell_only_fields_come_from_the_cell_and_airport_is_computed():
    row = build_point_features(CELL, 40.70, -73.99, live_like_cell(), 0).row
    for column in (
        "congestion_proxy_raw",
        "emergency_corridor_facility_raw",
        "street_orientation",
        "school_avg_rating_1600m",
        "running_trail_nearest_m",
    ):
        assert row[column] == CELL[column]
    assert row["airport_drive_time_min"] == pytest.approx(
        point.airport_drive_time_min(40.70, -73.99)
    )


def test_shopping_inverts_stored_proximity_when_not_saturated():
    cell = {**CELL, "shopping_raw": 0.6 * 0.5 + 0.4 * 0.5, "shopping_variety_count_1mi": 3}
    live = live_like_cell()
    live[(0, PT, "shopping")] = live[(0, CTR, "shopping")] = Live(3, (1.0, 2.0, 3.0))
    row = build_point_features(cell, 40.70, -73.99, live, 0).row
    assert row["shopping_raw"] == pytest.approx(cell["shopping_raw"])


def test_shopping_saturated_uses_live_kth_and_missing_cell_data_stays_none():
    cell = {**CELL, "shopping_raw": 1.0, "shopping_variety_count_1mi": 6}
    row = build_point_features(cell, 40.70, -73.99, live_like_cell(), 0).row
    assert row["shopping_raw"] == pytest.approx(1.0)  # 3rd nearest ~700 m is inside 0.5 mi
    cell = {**CELL, "shopping_raw": None}
    assert (
        build_point_features(cell, 40.70, -73.99, live_like_cell(), 0).row["shopping_raw"] is None
    )


def test_cell_without_park_data_has_no_recreation_signal():
    cell = {**CELL, "park_nearest_ft": None}
    row = build_point_features(cell, 40.70, -73.99, live_like_cell(), 0).row
    assert row["recreation_raw"] is None


def test_school_nearest_is_none_beyond_the_block():
    live = live_like_cell()
    live[(0, PT, "school")] = Live(0, (42_000.0,), ((41.5, -75.0),))
    row = build_point_features(CELL, 40.70, -73.99, live, 0).row
    assert row["school_nearest_m"] is None


# --- SQL shape -------------------------------------------------------------------------


def test_live_sql_is_one_statement_with_gist_and_knn():
    sql = build_live_sql(3)
    assert sql.count(";") == 0
    assert "places pl" in sql and "pl.geom &&" in sql
    assert "st_distancesphere" in sql and "pl.geom <-> q.pt" in sql
    assert f"limit {point.KNN_K}" in sql
    assert "geo_entities ge on ge.geohash = p.geohash" in sql  # centroid looked up in SQL
    n_placeholders = sql.count("%s")
    assert n_placeholders == 3 * 4 + len(point.LIVE_RADIUS_M) * 3
    assert len(live_params([("dr5reg", 40.7, -74.0)] * 3)) == n_placeholders


def test_live_params_order_and_anchor_flags():
    params = live_params([("dr5reg", 40.7, -74.0), ("dr5reh", 40.8, -74.1)], DEFAULT_ANCHOR)
    assert params[:8] == [0, "dr5reg", -74.0, 40.7, 1, "dr5reh", -74.1, 40.8]
    tail = params[8:]
    triples = {tail[i]: (tail[i + 1], tail[i + 2]) for i in range(0, len(tail), 3)}
    assert triples["grocery"] == (500.0, True)
    assert triples["school"] == (1600.0, False)
    assert triples["whole_foods"][1] is False
    assert {c for c, (_, a) in triples.items() if a} == set(DEFAULT_ANCHOR)


def test_read_live_parses_rows():
    class Cur:
        def fetchall(self):
            return [
                {"i": 0, "kind": "pt", "category": "grocery", "n": 2, "ds": [10.0, 30.0],
                 "lats": [40.1, 40.2], "lons": [-74.0, -74.1]},
                {"i": 1, "kind": "ctr", "category": "park", "n": 0, "ds": None,
                 "lats": None, "lons": None},
            ]  # fmt: skip

    out = read_live(Cur())
    assert out[(0, "pt", "grocery")].count == 2
    assert out[(0, "pt", "grocery")].nearest_m == 10.0
    assert out[(0, "pt", "grocery")].coords[1] == (40.2, -74.1)
    assert out[(1, "ctr", "park")].nearest_m is None


# --- polygon sampling --------------------------------------------------------------------

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}


def test_sample_points_inside_deterministic_and_spread():
    pts = sample_points(SQUARE, point_in_polygon)
    assert len(pts) == 5
    assert pts == sample_points(SQUARE, point_in_polygon)
    assert all(point_in_polygon(lon, lat, SQUARE) for lat, lon in pts)
    assert pts[0] == (5.0, 5.0)  # nearest the bbox centre first
    assert len(set(pts)) == 5
    assert max(lat for lat, _ in pts) - min(lat for lat, _ in pts) > 4  # spread out


def test_sample_points_concave_and_small():
    ell = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [10, 0], [10, 2], [2, 2], [2, 10], [0, 10], [0, 0]]],
    }
    pts = sample_points(ell, point_in_polygon)
    assert 1 <= len(pts) <= 5
    assert all(point_in_polygon(lon, lat, ell) for lat, lon in pts)
    assert len(sample_points(SQUARE, point_in_polygon, n_extra=0)) == 1


def test_sample_points_degenerate_inputs():
    assert sample_points({"type": "Polygon", "coordinates": []}, point_in_polygon) == []
    sliver = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 0.01], [0, 0.01], [0, 0]]]}
    got = sample_points(sliver, point_in_polygon)
    assert all(math.isfinite(v) for p in got for v in p)
