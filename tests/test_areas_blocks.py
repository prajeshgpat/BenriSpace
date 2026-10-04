import pytest

pytest.importorskip("shapely")

from ingestion.areas.blocks import build_blocks
from ingestion.areas.osm_source import parse_layers
from ingestion.areas.types import RoadWay

BBOX = (40.0, -74.0, 40.01, -73.99)


def way(wid, highway, pts, name=None, bridge=False):
    """pts are (x, y) in meters; node id is derived from the coordinate so
    ways that meet at a point share a node (a real junction)."""
    nodes = tuple(int(x) * 100_000 + int(y) for x, y in pts)
    return RoadWay(wid, highway, name, nodes, tuple(pts), bridge)


def grid(xs, ys, highway="residential", start_id=1, special=None):
    """Full street grid; `special` maps ('h'|'v', index) -> highway."""
    special = special or {}
    ways, wid = [], start_id
    for j, y in enumerate(ys):
        ways.append(way(wid, special.get(("h", j), highway), [(x, y) for x in xs], f"H{j}"))
        wid += 1
    for i, x in enumerate(xs):
        ways.append(way(wid, special.get(("v", i), highway), [(x, y) for y in ys], f"V{i}"))
        wid += 1
    return ways


def test_3x3_grid_gives_4_blocks():
    bs = build_blocks(grid([0, 100, 200], [0, 100, 200]))
    assert [b.kind for b in bs.blocks] == ["block"] * 4
    assert all(abs(b.area - 10_000) < 1 for b in bs.blocks)
    # 4 blocks in a 2x2 -> 4 shared edges
    assert len(bs.edges) == 4


def test_cul_de_sac_adds_no_face():
    roads = grid([0, 100, 200], [0, 100, 200])
    roads.append(way(99, "residential", [(100, 100), (100, 150), (130, 150)], "Dead End"))
    # a dead end poking into the upper-right block from the center
    roads.append(way(98, "residential", [(150, 100), (150, 160)], "Cul de Sac"))
    bs = build_blocks(roads)
    assert len(bs.blocks) == 4


def test_tunnel_is_ignored():
    def el(i, nodes, tags, pts):
        return {
            "type": "way",
            "id": i,
            "nodes": nodes,
            "tags": tags,
            "geometry": [{"lat": 40.0 + y * 1e-5, "lon": -74.0 + x * 1.3e-5} for x, y in pts],
        }

    def ways(vertical_tags):
        return [
            el(1, [1, 2, 3], {"highway": "residential"}, [(0, 0), (100, 0), (200, 0)]),
            el(2, [4, 5, 6], {"highway": "residential"}, [(0, 100), (100, 100), (200, 100)]),
            el(3, [1, 4], {"highway": "residential"}, [(0, 0), (0, 100)]),
            el(4, [2, 5], vertical_tags, [(100, 0), (100, 100)]),
            el(5, [3, 6], {"highway": "residential"}, [(200, 0), (200, 100)]),
        ]

    with_street = parse_layers({"elements": ways({"highway": "residential"})}, BBOX)
    with_tunnel = parse_layers(
        {"elements": ways({"highway": "residential", "tunnel": "yes"})}, BBOX
    )
    assert len(with_street.roads) == 5 and len(with_tunnel.roads) == 4
    assert len(build_blocks(with_street.roads).blocks) == 2
    assert len(build_blocks(with_tunnel.roads).blocks) == 1


def test_footway_and_service_not_in_network():
    el = {
        "type": "way",
        "id": 1,
        "nodes": [1, 2],
        "tags": {"highway": "service"},
        "geometry": [{"lat": 40.0, "lon": -74.0}, {"lat": 40.001, "lon": -74.0}],
    }
    assert (
        parse_layers({"elements": [el, dict(el, id=2, tags={"highway": "footway"})]}, BBOX).roads
        == []
    )


def test_median_strip_is_dropped():
    # y=100 and y=110 are the two carriageways of one avenue
    bs = build_blocks(grid([0, 100, 200], [0, 100, 110, 210]))
    assert bs.stats["right_of_way"] == 2
    assert len(bs.blocks) == 4
    assert all(b.area > 9_000 for b in bs.blocks)


def test_water_faces_dropped_and_parks_classified():
    from shapely.geometry import box

    roads = grid([0, 100, 200], [0, 100, 200])
    bs = build_blocks(roads, water=box(-10, -10, 105, 105), parks=box(95, 95, 205, 205))
    assert bs.stats["water"] == 1
    assert sorted(b.kind for b in bs.blocks) == ["block", "block", "park"]


def test_small_block_merged():
    # 40 x 40 = 1600 m2 face (thickness 20 > 15) beside two big blocks
    roads = grid([0, 40, 140], [0, 40, 140])
    bs = build_blocks(roads)
    assert bs.stats["merged_small"] == 1
    assert len(bs.blocks) == 3
