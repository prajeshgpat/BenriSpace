"""Routing precompute: tiles, OSM parsing, CSA train times, Pandana products (no network/DB)."""

import numpy as np
import pytest

from common import cellgrid
from ingestion.routing import tiles, transit
from ingestion.routing.network import NetworkData, merge_networks, parse_osm


def test_tiles_partition_cells_exactly_once():
    box = (40.70, -74.10, 40.77, -74.02)
    plan = tiles.plan_tiles(box, 10, 8)
    iy_a, ix_a = cellgrid.cell_index(box[0], box[1])
    iy_b, ix_b = cellgrid.cell_index(box[2], box[3])
    for iy in range(iy_a, iy_b + 1):
        for ix in range(ix_a, ix_b + 1):
            assert sum(t.contains(iy, ix) for t in plan) == 1
    assert plan[0].n_cells == 80
    south, west, north, east = plan[0].box()
    assert north > south and east > west


def test_pad_box_grows_by_metres():
    s, w, _n, _e = tiles.pad_box((40.7, -74.0, 40.8, -73.9), 1000.0)
    assert abs((40.7 - s) - 1000 / 111_320) < 1e-9
    assert (-74.0 - w) > (40.7 - s)  # a degree of longitude is shorter, so more degrees


def elements():
    nodes = [
        {"type": "node", "id": i, "lat": 40.7, "lon": -74.0 + 0.001 * i} for i in range(1, 4)
    ]
    ways = [
        {"type": "way", "id": 10, "nodes": [1, 2, 3], "tags": {"highway": "residential"}},
        {
            "type": "way",
            "id": 11,
            "nodes": [3, 2],
            "tags": {"highway": "primary", "oneway": "yes", "maxspeed": "30 mph"},
        },
    ]
    return nodes + ways


def test_parse_osm_walk_is_bidirectional_and_drive_respects_oneway():
    walk = parse_osm(elements(), "walk")
    assert walk.n_nodes == 3 and walk.n_edges == 2 * 2 + 2 * 1
    drive = parse_osm(elements(), "drive")
    assert drive.n_edges == 2 * 2 + 1  # the one-way contributes one edge
    one_way = (drive.edge_u == 3) & (drive.edge_v == 2)
    assert one_way.sum() >= 1 and ((drive.edge_u == 2) & (drive.edge_v == 3)).sum() == 1
    # 30 mph primary is faster than the residential default over the same ~85 m
    fast = drive.minutes[one_way].min()
    slow = drive.minutes[(drive.edge_u == 1) & (drive.edge_v == 2)][0]
    assert fast < slow


def test_merge_networks_dedupes_nodes_and_keeps_fastest_edge():
    a = NetworkData(
        np.array([1, 2]), np.array([0.0, 1.0]), np.array([0.0, 0.0]),
        np.array([1]), np.array([2]), np.array([5.0], dtype=np.float32),
    )  # fmt: skip
    b = NetworkData(
        np.array([2, 3]), np.array([1.0, 2.0]), np.array([0.0, 0.0]),
        np.array([1, 2]), np.array([2, 3]), np.array([3.0, 4.0], dtype=np.float32),
    )  # fmt: skip
    m = merge_networks(a, b)
    assert sorted(m.node_ids.tolist()) == [1, 2, 3] and m.n_edges == 2
    assert float(m.minutes[(m.edge_u == 1) & (m.edge_v == 2)][0]) == 3.0


# ------------------------------------------------------------------------------- CSA


def tiny_timetable():
    """A -> B -> C on one trip (08:00 A, 08:10 B, 08:25 C), plus a late D link at C."""
    stations = [
        transit.Station("x:A", "A", "x", 40.70, -74.00),
        transit.Station("x:B", "B", "x", 40.72, -74.00),
        transit.Station("x:C", "C", "x", 40.74, -74.00),
        transit.Station("y:D", "D", "y", 40.7401, -74.0001),  # ~15 m from C: walking link
    ]
    h = 3600
    conns = [
        (8 * h, 8 * h + 600, 0, 1, 0),
        (8 * h + 600, 8 * h + 1500, 1, 2, 0),
    ]
    return transit.Timetable(
        stations,
        [c[0] for c in conns], [c[1] for c in conns],
        [c[2] for c in conns], [c[3] for c in conns], [c[4] for c in conns],
        1,
        transit.build_links(stations),
    )  # fmt: skip


def test_csa_rides_through_and_walks_between_stations():
    tt = tiny_timetable()
    arr = transit.earliest_arrivals(tt, 0, 8 * 3600 - 300, 7200)
    assert arr[1] == 8 * 3600 + 600 and arr[2] == 8 * 3600 + 1500
    assert 8 * 3600 + 1500 < arr[3] < 8 * 3600 + 1500 + 120  # walk link from C to D
    assert transit.earliest_arrivals(tt, 2, 8 * 3600, 7200)[0] == transit.INF  # wrong direction


def test_ride_minutes_median_and_unreachable():
    tt = tiny_timetable()
    out = transit.ride_minutes_from(tt, 0)
    assert out[0] == 0.0
    # only the 08:05 and 08:25 departures sample before the single train: reachable in 1 of 3
    # samples at most, so the median rule marks it unreachable or returns a wait-inclusive time
    assert out[2] is None or out[2] >= 25.0


def test_parse_time_and_links():
    assert transit.parse_time("25:10:00") == 25 * 3600 + 600
    assert transit.parse_time("bad") is None
    links = transit.build_links(tiny_timetable().stations)
    assert any(j == 3 for j, _ in links[2]) and not links[0]


def test_merge_stations_same_name_same_agency():
    s = [
        transit.Station("a:1", "Penn Station", "a", 40.7500, -73.9930),
        transit.Station("a:2", "Penn Station", "a", 40.7502, -73.9932),
        transit.Station("b:1", "Penn Station", "b", 40.7500, -73.9930),
    ]
    rep = transit.merge_stations(s)
    assert rep[0] == rep[1] and rep[2] != rep[0]


# ------------------------------------------------------------------- pandana products


def line_network():
    """Nodes every ~0.001 deg of longitude along y=40.7, both directions."""
    n = 40
    ids = np.arange(1, n + 1)
    x = -74.02 + 0.001 * np.arange(n)
    y = np.full(n, 40.7)
    u = np.concatenate([ids[:-1], ids[1:]])
    v = np.concatenate([ids[1:], ids[:-1]])
    seg_m = 0.001 * 111_320 * np.cos(np.radians(40.7))
    return NetworkData(ids, x, y, u, v, np.full(len(u), seg_m / 80.467, dtype=np.float32))


def test_amenity_minutes_and_graph_on_a_line():
    pytest.importorskip("pandana")
    from common.routing import CATEGORIES, K_NEAREST
    from ingestion.routing import network, travel

    net = network.to_pandana(line_network())
    lat = np.array([40.7, 40.7])
    lon = np.array([-74.02 + 0.002, -74.02 + 0.03])
    node_ids, _snap_m, snap_min, ok = travel.snap(net, lat, lon, "walk")
    assert ok.all()
    places = {"grocery": (np.array([40.7]), np.array([-74.02 + 0.012]))}
    out = travel.amenity_minutes(net, node_ids, snap_min, ok, places, "walk")
    assert out.shape == (2, len(CATEGORIES) * K_NEAREST)
    # first cell is 10 segments (~0.85 km, ~10.5 min) from the store; second is 18 away (~19 min)
    first, second = out[0, 0], out[1, 0]
    assert 90 <= first <= 130 and 160 <= second <= 230
    assert out[0, 1] == -1  # only one grocery place: no 2nd nearest
    assert (out[:, 3:] == -1).all()  # other categories have no places


def test_neighbor_minutes_edges_are_symmetric_on_a_two_way_line():
    pytest.importorskip("pandana")
    from ingestion.routing import network, travel

    net = network.to_pandana(line_network())
    iy, ix = cellgrid.cell_index(40.7, -74.0)
    _iys, _ixs, edges = travel.neighbor_minutes(net, iy, ix, iy + 1, ix + 1, "walk")
    assert edges.shape == (1, 8)
    east, west = edges[0, 2], edges[0, 6]
    assert east > 0 and abs(int(east) - int(west)) <= 2
    assert edges[0, 0] == -1 or edges[0, 0] > 0  # north cell centre is off the line: allowed


def test_pbf_tag_rules_match_the_overpass_filters():
    from ingestion.routing.pbf import drive_ok, walk_ok

    assert walk_ok({"highway": "footway"})
    assert walk_ok({"highway": "residential"})
    assert not walk_ok({"highway": "motorway_link"})
    assert not walk_ok({"highway": "steps"})
    assert not walk_ok({"highway": "residential", "access": "private"})
    assert not walk_ok({"highway": "pedestrian", "area": "yes"})
    assert drive_ok({"highway": "residential"})
    assert drive_ok({"highway": "service"})
    assert not drive_ok({"highway": "service", "service": "driveway"})
    assert not drive_ok({"highway": "footway"})
    assert not drive_ok({"highway": "primary", "motor_vehicle": "no"})


def test_pbf_builder_costs_minutes_from_miles_and_dedupes():
    from ingestion.routing.pbf import _Builder

    b = _Builder()
    # 0.01 deg of latitude = 0.69172 mi; at 3 mph that is 13.83 minutes.
    b.add_way([1, 2], [-74.0, -74.0], [40.70, 40.71], 3.0, 0)
    b.add_way([1, 2], [-74.0, -74.0], [40.70, 40.71], 30.0, 1)  # same pair, faster, one way
    data = b.finish()
    assert list(data.node_ids) == [1, 2]
    pairs = dict(zip(zip(data.edge_u.tolist(), data.edge_v.tolist()), data.minutes.tolist()))
    assert pairs[(1, 2)] == pytest.approx(1.383, abs=0.01)  # the faster duplicate wins
    assert pairs[(2, 1)] == pytest.approx(13.83, abs=0.05)


def test_keep_connected_drops_small_fragments():
    from ingestion.routing.pbf import keep_connected

    data = NetworkData(
        node_ids=np.array([1, 2, 3, 10, 11], dtype=np.int64),
        x=np.zeros(5),
        y=np.zeros(5),
        edge_u=np.array([1, 2, 10], dtype=np.int64),
        edge_v=np.array([2, 3, 11], dtype=np.int64),
        minutes=np.ones(3, dtype=np.float32),
    )
    kept = keep_connected(data, min_nodes=3)
    assert list(kept.node_ids) == [1, 2, 3]
    assert list(kept.edge_u) == [1, 2]
