"""Road-hierarchy subdivision: density caps, polygonizing with roads, merging to the
cap without crossing hard roads, and the no-roads fallback (synthetic grids)."""

import numpy as np
import pytest

pytest.importorskip("shapely")

from shapely.geometry import LineString, box
from shapely.ops import unary_union

from ingestion.areas import limits
from ingestion.areas.hierarchy import (
    Leaf,
    Lower,
    build_subdivider,
    merge_leaves,
    polygonize_within,
    union_group,
)

SQ = limits.SQ_M_PER_SQ_MI


@pytest.mark.parametrize(
    ("density", "cap"),
    [(None, 1.0), (0, 1.0), (1999, 1.0), (2000, 0.6), (4999, 0.6), (5000, 0.35),
     (9999, 0.35), (10_000, 0.2), (19_999, 0.2), (20_000, 0.1), (80_000, 0.1)],
)  # fmt: skip
def test_density_cap_table(density, cap):
    assert limits.cap_for_density(density) == cap


def test_extent_cap_scales_with_cap():
    assert limits.extent_cap_mi(1.0) > limits.extent_cap_mi(0.1) > 0


def test_polygonize_within_splits_and_closes_small_gaps():
    face = box(0, 0, 1000, 1000)
    # vertical road stops 4 m short of both edges (simplified hard boundary mismatch)
    pieces = polygonize_within(face, [LineString([(500, 4), (500, 996)])])
    assert len(pieces) == 2
    assert sum(p.area for p in pieces) == pytest.approx(face.area)


def test_polygonize_within_no_roads_returns_face():
    face = box(0, 0, 100, 100)
    assert polygonize_within(face, []) == [face]
    # a lone cul-de-sac far from everything does not split
    assert len(polygonize_within(face, [LineString([(50, 50), (50, 80)])])) == 1


def _grid_leaves(n=10, size=100.0, parent=lambda i, j: 0):
    return [
        Leaf(
            box(i * size, j * size, (i + 1) * size, (j + 1) * size), size * size, 0.0, parent(i, j)
        )
        for i in range(n)
        for j in range(n)
    ]


def test_merge_leaves_reaches_cap_without_exceeding():
    leaves = _grid_leaves()  # 1 km x 1 km of 100 m blocks = 0.386 sq mi
    cap = 0.1
    groups = merge_leaves(leaves, lambda d: cap, lambda c: 10_000.0)
    areas = [sum(leaves[i].area for i in g) for g in groups]
    assert sorted(i for g in groups for i in g) == list(range(100))
    assert max(areas) <= cap * SQ
    assert len(groups) <= 6  # close to the cap: not left as 100 blocks
    assert np.mean(areas) >= 0.5 * cap * SQ * 0.8
    for g in groups:
        assert union_group(leaves, g).geom_type == "Polygon"


def test_merge_leaves_prefers_same_parent():
    leaves = _grid_leaves(4, parent=lambda i, j: 1 if i < 2 else 2)
    groups = merge_leaves(leaves, lambda d: 8 * 100 * 100 / SQ, lambda c: 10_000.0)
    mixed = [g for g in groups if len({leaves[i].parent for i in g}) > 1]
    assert len(mixed) <= 1  # greedy: same-parent merges win, a straggler may straddle


def test_merge_requires_shared_edge():
    a = Leaf(box(0, 0, 100, 100), 1e4, 0.0)
    b = Leaf(box(100, 100, 200, 200), 1e4, 0.0)  # touches at a corner only
    assert len(merge_leaves([a, b], lambda d: 1.0, lambda c: 1e5)) == 2


def _grid_lines(x0, y0, x1, y1, step, tertiary_every=None):
    out = []
    for k, x in enumerate(np.arange(x0 + step, x1, step)):
        out.append(
            Lower(
                LineString([(x, y0 - 5), (x, y1 + 5)]),
                f"S{k}",
                bool(tertiary_every and k % tertiary_every == 0),
            )
        )
    for k, y in enumerate(np.arange(y0 + step, y1, step)):
        out.append(
            Lower(
                LineString([(x0 - 5, y), (x1 + 5, y)]),
                f"E{k}",
                bool(tertiary_every and k % tertiary_every == 0),
            )
        )
    return out


def _sub(lower, density):
    return build_subdivider(lambda polys: np.full(len(polys), float(density)), lower)


def test_dense_face_split_to_small_pieces_that_tile_the_face():
    face = box(0, 0, 1500, 1500)  # 0.87 sq mi
    sub = _sub(_grid_lines(0, 0, 1500, 1500, 100, tertiary_every=5), 25_000)
    pieces = sub.process(face)
    cap = 0.1 * SQ
    assert all(p.area <= cap for p in pieces)
    assert len(pieces) >= 9
    assert unary_union(pieces).symmetric_difference(face).area < 1e-3 * face.area
    assert np.mean([p.area for p in pieces]) > 0.5 * cap
    assert sub.stats.get("tile_cut_fallback", 0) == 0


def test_sparse_face_under_cap_is_untouched():
    face = box(0, 0, 1000, 1000)
    sub = _sub(_grid_lines(0, 0, 1000, 1000, 100), 100)
    assert sub.process(face) == [face]


def test_pieces_never_cross_the_hard_face_boundary():
    f1, f2 = box(0, 0, 1000, 1500), box(1000, 0, 2000, 1500)
    sub = _sub(_grid_lines(0, 0, 2000, 1500, 100, tertiary_every=5), 15_000)
    for f in (f1, f2):
        for p in sub.process(f):
            assert f.buffer(0.01).contains(p)


def test_no_internal_roads_keeps_whole_when_small_else_tile_cuts():
    small = box(0, 0, 1200, 1200)  # 0.56 sq mi, dense: keep whole
    sub = _sub([], 30_000)
    assert sub.process(small) == [small]
    assert sub.stats["kept_whole_no_roads"] == 1
    big = box(0, 0, 2500, 2500)  # 2.4 sq mi
    sub2 = _sub([Lower(LineString([(5000, 0), (5000, 10)]), None, False)], 30_000)
    pieces = sub2.process(big)
    assert len(pieces) > 1
    assert all(p.area <= limits.HIER_MAX_AREA_SQ_MI * SQ for p in pieces)
    assert sub2.stats["tile_cut_fallback"] == 1
    assert sub2.tile_cut_pts
