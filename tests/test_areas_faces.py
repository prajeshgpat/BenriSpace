"""Faces of the hard-road arrangement: offline, on a cropped real fixture
(Lower Manhattan + Downtown Brooklyn) and on synthetic geometry."""

import json
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from shapely.geometry import Point, box

from common.geo import encode
from ingestion.areas.build import compute_metrics, frame_for, projector_for
from ingestion.areas.faces import (
    FaceParams,
    _interleave,
    _to_m,
    build_faces,
    cells_in_bbox,
    geohash_bounds,
    number_faces,
)
from ingestion.areas.hard_source import parse_hard
from ingestion.areas.osm_source import SAMPLE_BBOX, Projector
from ingestion.areas.types import RoadWay

FIXTURE = Path(__file__).parent / "fixtures" / "areas_hard_sample.json"


@pytest.fixture(scope="module")
def sample():
    data = json.loads(FIXTURE.read_text())
    proj = projector_for(SAMPLE_BBOX)
    roads, coast = parse_hard(data, proj)
    faces = build_faces(roads, coast, frame_for(SAMPLE_BBOX, proj), FaceParams(proj))
    return data, proj, roads, coast, faces


# ------------------------------------------------------------------ geohash


def test_geohash_bounds_match_pygeohash_cells():
    for lat, lon in [(40.7128, -74.006), (41.2, -73.1), (0.0001, 0.0001), (-33.9, 151.2)]:
        gh = encode(lat, lon, 6)
        a, b, lo, hi = geohash_bounds(gh)
        assert a <= lat <= b and lo <= lon <= hi
        assert abs((b - a) - 180 / 2**15) < 1e-9 and abs((hi - lo) - 360 / 2**15) < 1e-9


def test_cells_in_bbox_cover_and_roundtrip():
    cells = cells_in_bbox(40.70, 40.72, -74.02, -74.00)
    assert encode(40.71, -74.01, 6) in cells
    assert encode(40.70, -74.02, 6) in cells and encode(40.72, -74.00, 6) in cells
    assert len(cells) == len(set(cells))
    nlon = 2**15
    assert _interleave(0, 0, 6) == "000000"
    assert geohash_bounds(_interleave(nlon - 1, 2**15 - 1, 6))[1] == pytest.approx(90.0)


# ------------------------------------------------------------------- sample


def test_sample_street_points_covered(sample):
    data, proj, _, _, faces = sample
    pts = [proj.fwd(lon, lat) for lat, lon in data["street_points"]]
    numbered = number_faces(faces)
    m = compute_metrics(numbered, proj, 0.0, pts)
    assert m["street_points_in_face_pct"] >= 95.0
    assert m["face_count"] > 50


def test_sample_no_faces_over_water(sample):
    _, proj, _, _, faces = sample
    geoms = [_to_m(f.geometry, proj) for f in faces]
    # East River, Upper Bay and the water between Brooklyn's piers and Governors Island
    for lat, lon in [(40.7040, -73.9960), (40.6990, -74.0070), (40.6950, -74.0150)]:
        p = Point(*proj.fwd(lon, lat))
        assert not any(g.contains(p) for g in geoms), (lat, lon)
    # land: Manhattan (Lower East Side), Downtown Brooklyn
    for lat, lon in [(40.7200, -73.9850), (40.6930, -73.9850)]:
        p = Point(*proj.fwd(lon, lat))
        assert any(g.contains(p) for g in geoms), (lat, lon)


def test_sample_filters_and_bounded_by(sample):
    _, _, _, _, faces = sample
    assert all(f.area_sq_m >= 5000 * 0.97 for f in faces)  # local-projection tolerance
    assert all(f.geometry.is_valid for f in faces)
    assert all(len(f.bounded_by) <= 4 for f in faces)
    assert sum(1 for f in faces if f.bounded_by) > 0.9 * len(faces)
    names = {n for f in faces for n in f.bounded_by}
    assert "Broadway" in names or "Bowery" in names or "Delancey St" in names


def test_sample_coordinates_rounded(sample):
    faces = sample[4]
    for f in faces[:20]:
        for poly in getattr(f.geometry, "geoms", [f.geometry]):
            for x, y in poly.exterior.coords:
                assert round(x, 5) == pytest.approx(x, abs=1e-9)
                assert round(y, 5) == pytest.approx(y, abs=1e-9)


def test_overlaps_sum_to_face_area(sample):
    _, _, _, _, faces = sample
    for f in faces:
        total = sum(ov for _, ov in f.cells)
        assert total == pytest.approx(f.area_sq_m, rel=1e-6)
        min_lat, max_lat, min_lon, max_lon = f.bbox
        for gh, _ in f.cells:
            a, b, lo, hi = geohash_bounds(gh)
            assert a < max_lat and b > min_lat and lo < max_lon and hi > min_lon


def test_overlaps_restricted_to_known_geohashes(sample):
    _, proj, roads, coast, faces = sample
    known = frozenset(gh for f in faces[:10] for gh, _ in f.cells[:1])
    again = build_faces(
        roads, coast, frame_for(SAMPLE_BBOX, proj), FaceParams(proj, geohashes=known)
    )
    assert all(gh in known for f in again for gh, _ in f.cells)
    assert any(f.cells for f in again)
    for f in again:
        assert sum(ov for _, ov in f.cells) <= f.area_sq_m * (1 + 1e-6)


def test_ids_deterministic_across_runs(sample):
    _, proj, roads, coast, faces = sample
    again = build_faces(roads, coast, frame_for(SAMPLE_BBOX, proj), FaceParams(proj))
    a, b = number_faces(faces), number_faces(again)
    assert [i for i, _ in a] == list(range(1, len(a) + 1))
    assert [(i, f.geometry.wkt, f.bounded_by) for i, f in a] == [
        (i, f.geometry.wkt, f.bounded_by) for i, f in b
    ]


# ---------------------------------------------------------------- synthetic

P = Projector(40.7, -74.0)
FRAME = box(-2000, -2000, 2000, 2000)


def road(rid, name, a, b, nodes):
    return RoadWay(rid, "primary", name, nodes, (a, b))


def mainland_coast():
    # land on the LEFT: travelling west along y=0, left is south (y<0)
    return [(2000.0, 0.0), (1000.0, 0.0), (0.0, 0.0), (-1000.0, 0.0), (-2000.0, 0.0)]


def island_ring(ccw=True):
    ring = [(-500.0, 800.0), (500.0, 800.0), (500.0, 1500.0), (-500.0, 1500.0), (-500.0, 800.0)]
    return ring if ccw else ring[::-1]


def test_left_of_coast_rule_island_and_mainland():
    roads = [road(1, "Main Street", (0, -2000), (0, 0), (1, 2))]
    faces = build_faces(
        roads,
        [mainland_coast(), island_ring(True)],
        FRAME,
        FaceParams(P, enforce_size_limits=False),
    )
    centers = sorted(
        (round(f.geometry.centroid.x, 4), round(f.geometry.centroid.y, 4)) for f in faces
    )
    assert len(faces) == 3
    lat = lambda y: P.inv(0, y)[1]
    ys = sorted(c[1] for c in centers)
    assert (
        ys[0] < lat(-1) and ys[1] < lat(-1) and lat(800) < ys[2] < lat(1500)
    )  # 2 mainland + island
    # nothing in the open sea north of the coast, around the island
    sea = Point(*P.inv(1500, 400))
    assert not any(f.geometry.contains(sea) for f in faces)


def test_clockwise_ring_is_water():
    # Same ring, reversed: land would be on the outside (right of travel is inside).
    faces = build_faces(
        [], [mainland_coast(), island_ring(False)], FRAME, FaceParams(P, enforce_size_limits=False)
    )
    assert len(faces) == 1  # only the mainland; the reversed ring encloses water
    assert faces[0].geometry.centroid.y < P.inv(0, 0)[1]


def test_sliver_and_small_faces_dropped_and_names():
    roads = [
        road(1, "Main Street", (0, -2000), (0, 0), (1, 2)),
        road(2, "Side Road", (10, -2000), (10, 0), (3, 4)),  # 10 m strip: thinner than 15 m
        road(3, "Far Avenue", (1990, -2000), (1990, 0), (5, 6)),  # 10 m x 2 km as well
    ]
    faces = build_faces(roads, [mainland_coast()], FRAME, FaceParams(P, enforce_size_limits=False))
    assert len(faces) == 2
    by_x = sorted(faces, key=lambda f: f.geometry.centroid.x)
    assert by_x[0].bounded_by == ("Main St",)
    assert set(by_x[1].bounded_by) == {"Side Rd", "Far Ave"}
    # thin strips are gone: total land area equals the two big faces only
    assert all(f.area_sq_m > 1_000_000 for f in faces)


def test_small_area_threshold():
    roads = [
        road(1, "A", (0, -2000), (0, 0), (1, 2)),
        road(2, "B", (60, -2000), (60, 0), (3, 4)),  # 60 m wide: passes thickness, area 120k
        road(3, "C", (60, -60), (-0.0, -60), (5, 6)),
    ]
    big = build_faces(roads, [mainland_coast()], FRAME, FaceParams(P, enforce_size_limits=False))
    strict = build_faces(
        roads,
        [mainland_coast()],
        FRAME,
        FaceParams(P, min_area_m2=1_000_000, enforce_size_limits=False),
    )
    assert len(strict) < len(big)


def test_residential_is_not_a_wall():
    roads = [RoadWay(1, "residential", "Elm", (1, 2), ((0, -2000), (0, 0)))]
    faces = build_faces(roads, [mainland_coast()], FRAME, FaceParams(P, enforce_size_limits=False))
    assert len(faces) == 1  # the hard filter ignores residential (edges would be dropped)


def test_overlap_sums_on_synthetic():
    faces = build_faces([], [mainland_coast()], FRAME, FaceParams(P, enforce_size_limits=False))
    assert len(faces) == 1
    f = faces[0]
    assert sum(ov for _, ov in f.cells) == pytest.approx(f.area_sq_m, rel=1e-6)
    assert f.area_sq_m == pytest.approx(4000 * 2000, rel=0.01)
