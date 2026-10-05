"""Equivalence of the scipy cKDTree paths against the original pure-Python scans."""

import math
import random

import pytest

pytest.importorskip("scipy")
pytest.importorskip("numpy")

from common.geo import haversine_m
from ingestion import gtfs_transit, osm_poi, osm_retail_parks
from ingestion.spatial import PointIndex

RNG = random.Random(7)


def _points(n, lat=(40.5, 41.4), lon=(-74.2, -73.0)):
    return [(RNG.uniform(*lat), RNG.uniform(*lon)) for _ in range(n)]


def test_nearest_and_count_matches_brute_force():
    pts = _points(3000, (40.6, 40.9), (-74.1, -73.7))
    cells = _points(400, (40.55, 40.95), (-74.15, -73.65))
    index = PointIndex([p[0] for p in pts], [p[1] for p in pts])
    counts, nearest = index.nearest_and_count([c[0] for c in cells], [c[1] for c in cells], 500.0)
    for i, (lat, lon) in enumerate(cells):
        want_count, want_nearest = osm_poi.nearest_and_count(lat, lon, pts, 500.0)
        assert counts[i] == want_count
        assert abs(nearest[i] - want_nearest) < 1e-6


def test_sparse_points_still_find_true_nearest():
    pts = _points(5, (40.5, 41.4), (-74.2, -73.0))
    cells = _points(100, (40.5, 41.4), (-74.2, -73.0))
    index = PointIndex([p[0] for p in pts], [p[1] for p in pts])
    _, nearest = index.nearest_and_count([c[0] for c in cells], [c[1] for c in cells], 500.0)
    for i, (lat, lon) in enumerate(cells):
        want = min(haversine_m(lat, lon, *p) for p in pts)
        assert abs(nearest[i] - want) < 1e-6


def test_empty_points():
    index = PointIndex([], [])
    counts, nearest = index.nearest_and_count([40.7], [-74.0], 500.0)
    assert counts[0] == 0 and math.isnan(nearest[0])


def test_poi_features_many_matches_per_cell():
    cats = {
        c: _points(RNG.choice([0, 3, 400]), (40.6, 40.9), (-74.1, -73.7))
        for c in osm_poi.ALL_CATEGORIES
    }
    cells = [
        {"latitude": lat, "longitude": lon}
        for lat, lon in _points(150, (40.58, 40.92), (-74.12, -73.68))
    ]
    got = osm_poi.compute_features_many(cells, cats)
    for cell, row in zip(cells, got, strict=True):
        want = osm_poi.compute_cell_features(cell["latitude"], cell["longitude"], cats)
        assert row.keys() == want.keys()
        for key, value in want.items():
            if value is None or isinstance(value, int):
                assert row[key] == value, key
            else:
                assert abs(row[key] - value) < 1e-6, key


def test_shop_features_many_matches_per_cell():
    groups = ["a", "b", "c", "d", "e"]
    shops = [
        (lat, lon, RNG.choice(groups)) for lat, lon in _points(1500, (40.6, 40.9), (-74.1, -73.7))
    ]
    index = osm_retail_parks.build_shop_index(shops)
    cells = [
        {"latitude": lat, "longitude": lon}
        for lat, lon in _points(150, (40.58, 40.92), (-74.12, -73.68))
    ]
    got = osm_retail_parks.shop_features_many(cells, shops)
    for cell, row in zip(cells, got, strict=True):
        want = osm_retail_parks.shop_features(cell["latitude"], cell["longitude"], index)
        assert row["shopping_count_1mi"] == want["shopping_count_1mi"]
        assert row["shopping_variety_count_1mi"] == want["shopping_variety_count_1mi"]
        for key in ("shopping_nearest_ft", "shopping_raw"):
            if want[key] is None:
                assert row[key] is None
            else:
                assert abs(row[key] - want[key]) < 1e-6


def test_shop_features_many_no_shops():
    row = osm_retail_parks.shop_features_many([{"latitude": 40.7, "longitude": -74.0}], [])[0]
    assert row["shopping_count_1mi"] == 0 and row["shopping_nearest_ft"] is None


def test_gtfs_aggregate_many_matches_per_cell():
    stops = {
        "mta": _points(800, (40.6, 40.9), (-74.1, -73.7)),
        "path": _points(20, (40.7, 40.8), (-74.1, -74.0)),
        "empty": [],
    }
    cells = [
        {"latitude": lat, "longitude": lon}
        for lat, lon in _points(200, (40.58, 40.92), (-74.12, -73.68))
    ]
    got = gtfs_transit.aggregate_cells_many(cells, stops)
    for cell, row in zip(cells, got, strict=True):
        want = gtfs_transit.aggregate_cell(cell["latitude"], cell["longitude"], stops)
        assert row == want
