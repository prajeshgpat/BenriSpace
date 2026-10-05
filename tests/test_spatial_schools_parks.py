"""cKDTree paths for schools and parks against the original bucket scans."""

import random

import pytest

pytest.importorskip("scipy")
pytest.importorskip("numpy")

from ingestion import osm_retail_parks, schools

RNG = random.Random(11)


def _points(n, lat, lon):
    return [(RNG.uniform(*lat), RNG.uniform(*lon)) for _ in range(n)]


def test_schools_many_matches_the_bucket_scan_where_a_school_is_near():
    pts = _points(800, (40.6, 40.9), (-74.1, -73.7))
    recs = [schools.SchoolRecord(la, lo, f"s{i}", "nces_edge") for i, (la, lo) in enumerate(pts)]
    cells = [
        {"latitude": la, "longitude": lo}
        for la, lo in _points(300, (40.62, 40.88), (-74.08, -73.72))
    ]
    index = schools.build_spatial_index(recs)
    got = schools.compute_cell_aggregates_many(cells, recs)
    for cell, row in zip(cells, got, strict=True):
        want = schools.compute_cell_aggregate(cell["latitude"], cell["longitude"], index)
        assert row["school_count_1600m"] == want["school_count_1600m"]
        assert row["school_nearest_m"] == want["school_nearest_m"]


def test_schools_many_reports_the_true_nearest_beyond_the_bucket_block():
    far = [schools.SchoolRecord(40.9, -73.9, "far", "nces_edge")]
    row = schools.compute_cell_aggregates_many([{"latitude": 40.6, "longitude": -73.9}], far)[0]
    assert row["school_count_1600m"] == 0 and row["school_nearest_m"] > 30_000


def _rects(n, big=0):
    out = []
    for _ in range(n):
        la, lo = RNG.uniform(40.6, 40.9), RNG.uniform(-74.1, -73.7)
        h = RNG.uniform(0.0005, 0.01)
        out.append((la, lo, la + h, lo + h * 1.3, RNG.uniform(1e4, 5e6)))
    for _ in range(big):
        la, lo = RNG.uniform(40.6, 40.8), RNG.uniform(-74.0, -73.8)
        out.append((la, lo, la + 0.15, lo + 0.2, 9e8))
    return out


@pytest.mark.parametrize("n,big", [(400, 0), (300, 3), (3, 0)])
def test_park_features_many_matches_the_bucket_scan(n, big):
    parks = _rects(n, big)
    cells = [
        {"latitude": la, "longitude": lo}
        for la, lo in _points(250, (40.55, 40.95), (-74.15, -73.65))
    ]
    index = osm_retail_parks.build_park_index(parks)
    got = osm_retail_parks.park_features_many(cells, parks)
    for cell, row in zip(cells, got, strict=True):
        want = osm_retail_parks.park_features(cell["latitude"], cell["longitude"], index)
        assert row["park_count_1mi"] == want["park_count_1mi"]
        assert row["park_nearest_ft"] == pytest.approx(want["park_nearest_ft"], abs=1e-3)
        assert row["park_largest_sq_ft_half_mi"] == want["park_largest_sq_ft_half_mi"]
        assert row["recreation_raw"] == pytest.approx(want["recreation_raw"], abs=1e-9)
