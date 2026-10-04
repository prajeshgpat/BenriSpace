"""Size limits for road-bounded areas: splitting, sliver merging, API parity."""

import pytest

pytest.importorskip("shapely")

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from api import areas as api_areas
from ingestion.areas import limits
from ingestion.areas.faces import FaceParams, build_faces
from ingestion.areas.limits_apply import (
    compactness,
    enforce_limits,
    measure,
    merge_slivers,
    split_oversized,
    within_caps,
)
from ingestion.areas.osm_source import Projector
from ingestion.areas.types import RoadWay

PROJ = Projector(40.7, -74.0)
MI = limits.M_PER_MI


def test_caps_are_the_agreed_values_and_api_mirrors_them():
    assert limits.MAX_AREA_SQ_MI == 0.8
    assert limits.TARGET_TILE_MI == 0.75
    assert limits.MAX_EXTENT_MI == 1.4
    assert limits.MIN_SLIVER_SQ_MI == 0.02
    assert api_areas.AREA_MAX_SQ_MI == limits.MAX_AREA_SQ_MI
    assert api_areas.AREA_MAX_EXTENT_MI == limits.MAX_EXTENT_MI
    assert api_areas.SQ_M_PER_SQ_MI == limits.SQ_M_PER_SQ_MI
    assert api_areas.M_PER_MI == limits.M_PER_MI


def _check_pieces(original, pieces):
    assert len(pieces) > 1
    for p in pieces:
        assert within_caps(p, PROJ), measure(p, PROJ)
    union = unary_union(pieces)
    assert union.area == pytest.approx(original.area, rel=1e-3)
    assert union.symmetric_difference(original).area < original.area * 1e-3


def test_split_big_square():
    big = box(0, 0, 4.2 * MI, 3.1 * MI)  # ~13 sq mi
    pieces = split_oversized(big, PROJ)
    _check_pieces(big, pieces)
    assert len(pieces) <= 30


def test_split_concave_face_keeps_union():
    big = Polygon(
        [(0, 0), (4 * MI, 0), (4 * MI, 1 * MI), (1 * MI, 1 * MI), (1 * MI, 3.5 * MI), (0, 3.5 * MI)]
    )
    pieces = split_oversized(big, PROJ)
    _check_pieces(big, pieces)
    assert all(p.geom_type == "Polygon" for p in pieces)


def test_thin_long_face_is_split_by_extent_not_area():
    thin = box(0, 0, 6 * MI, 0.1 * MI)  # 0.6 sq mi but 6 mi long
    assert measure(thin, PROJ)[0] < limits.MAX_AREA_M2
    pieces = split_oversized(thin, PROJ)
    _check_pieces(thin, pieces)
    assert all(measure(p, PROJ)[1] <= limits.MAX_EXTENT_M for p in pieces)


def test_compliant_face_is_untouched():
    ok = box(0, 0, 0.85 * MI, 0.85 * MI)
    assert split_oversized(ok, PROJ) == [ok]


def test_sliver_merges_into_neighbour_with_longest_shared_boundary():
    a = box(0, 0, 1000, 1000)
    b = box(1000, 0, 1020, 600)  # sliver, 12,000 m2
    c = box(1000, 600, 2000, 1000)
    out = merge_slivers([a, b, c], PROJ)
    assert len(out) == 2
    merged = next(p for p in out if p.area > 1_000_000)
    assert merged.equals(unary_union([a, b])) or merged.equals(unary_union([b, c]))
    # b shares 600 m with a but only 20 m with c
    assert merged.equals(unary_union([a, b]))


def test_sliver_not_merged_when_caps_would_break():
    near_cap = box(0, 0, 0.89 * MI, 0.89 * MI)  # 0.79 sq mi
    sliver = box(0.89 * MI, 0, 0.89 * MI + 25, 0.89 * MI)  # 0.019 sq mi
    out = merge_slivers([near_cap, sliver], PROJ)
    assert len(out) == 2


def test_isolated_sliver_is_kept():
    s = box(0, 0, 100, 100)
    assert len(merge_slivers([s, box(5000, 5000, 6000, 6000)], PROJ)) == 2


def test_enforce_limits_end_to_end_no_crumbs_below_threshold_when_mergeable():
    big = box(0, 0, 2.05 * MI, 1.0 * MI)  # tiles leave a thin crumb at the end
    pieces = enforce_limits([big], PROJ)
    assert all(within_caps(p, PROJ) for p in pieces)
    assert unary_union(pieces).area == pytest.approx(big.area, rel=1e-3)
    assert all(measure(p, PROJ)[0] >= limits.MIN_SLIVER_M2 for p in pieces)


def test_compactness():
    assert compactness(1.0, 4.0) == pytest.approx(0.785398, abs=1e-5)
    assert compactness(1.0, 0.0) == 0.0


def test_build_faces_splits_a_big_frame_and_fills_shape_fields():
    frame = box(-4 * MI, -4 * MI, 4 * MI, 4 * MI)  # one 64 sq mi face, no roads
    road = RoadWay(1, "primary", "Long Rd", (1, 2), ((-4 * MI, 0.0), (4 * MI, 0.0)))
    faces = build_faces([road], [], frame, FaceParams(PROJ))
    assert len(faces) > 20
    for f in faces:
        assert f.area_sq_m <= limits.MAX_AREA_M2
        assert f.extent_m <= limits.MAX_EXTENT_M
        assert 0 < f.compactness <= 1
        assert sum(ov for _, ov in f.cells) == pytest.approx(f.area_sq_m, rel=0.02)
    assert any("Long Rd" in f.bounded_by for f in faces)
