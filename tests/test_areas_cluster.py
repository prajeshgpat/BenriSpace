import pytest

pytest.importorskip("shapely")

from ingestion.areas.blocks import build_blocks
from ingestion.areas.cluster import _absorb, cluster_blocks
from ingestion.areas.types import ClusterParams
from tests.test_areas_blocks import grid, way

STEP = [i * 100 for i in range(11)]


def test_secondary_road_is_never_crossed_and_sizes_ok():
    bs = build_blocks(grid(STEP, STEP, special={("h", 5): "secondary"}))
    clusters = cluster_blocks(bs)
    assert sum(len(c.block_ids) for c in clusters) == 100
    for c in clusters:
        sides = {bs.blocks[b].geom.centroid.y > 500 for b in c.block_ids}
        assert len(sides) == 1, "cluster spans the secondary road"
        assert 5 <= len(c.block_ids) <= 10
        assert c.area < 2_589_988


def test_tertiary_can_be_crossed_with_penalty():
    bs = build_blocks(grid(STEP, STEP, special={("h", 5): "tertiary"}))
    clusters = cluster_blocks(bs)
    assert all(5 <= len(c.block_ids) <= 10 for c in clusters)


def test_deterministic():
    def run():
        bs = build_blocks(grid(STEP, STEP, special={("h", 5): "secondary", ("v", 3): "tertiary"}))
        return [c.block_ids for c in cluster_blocks(bs)]

    assert run() == run()


def test_small_district_is_one_neighborhood():
    bs = build_blocks(grid([0, 100, 200, 300], [0, 100, 200, 300]))
    clusters = cluster_blocks(bs)
    assert len(clusters) == 1 and len(clusters[0].block_ids) == 9


def test_rural_face_stands_alone():
    big = [
        way(1, "tertiary", [(0, 0), (2000, 0), (2000, 2000), (0, 2000), (0, 0)], "Ring"),
    ]
    small = grid([3000, 3100, 3200], [0, 100, 200], start_id=10)
    bs = build_blocks(big + small)
    clusters = cluster_blocks(bs)
    rural = [c for c in clusters if c.kind == "rural"]
    assert len(rural) == 1 and len(rural[0].block_ids) == 1
    assert rural[0].area > 2_589_988
    assert [len(c.block_ids) for c in clusters if c.kind != "rural"] == [4]


def test_small_cluster_absorbed():
    class G:  # minimal geometry stand-in: _absorb only needs .area
        area = 10_000.0

    geom = {i: G() for i in range(6)}
    adj = {i: {} for i in range(6)}
    for i in range(5):
        adj[i][i + 1] = adj[i + 1][i] = (100.0, 1.0)
    hard = {i: set() for i in range(6)}
    out = _absorb([[0, 1, 2, 3, 4], [5]], geom, adj, hard, 3, 14, 1e9)
    assert out == [[0, 1, 2, 3, 4, 5]]
    # but never across a hard road
    hard[4].add(5)
    hard[5].add(4)
    out = _absorb([[0, 1, 2, 3, 4], [5]], geom, adj, hard, 3, 14, 1e9)
    assert sorted(map(len, out)) == [1, 5]


def test_strip_leftover_is_absorbed():
    xs = [0, 100]
    ys = [i * 100 for i in range(12)]  # 11 blocks in a row
    bs = build_blocks(grid(xs, ys))
    clusters = cluster_blocks(bs, ClusterParams())
    sizes = sorted(len(c.block_ids) for c in clusters)
    assert sum(sizes) == 11 and min(sizes) >= 3 and max(sizes) <= 14
