"""Cell-graph isochrones, reach by mode and the DB readers: no database, no network."""

from api import isochrone, reach, routing_data
from common import cellgrid
from common.routing import category_slot, from_dm, to_dm


def line_graph(n: int, dm: int = 50) -> isochrone.Graph:
    """A west-east row of n cells; each hop costs dm deci-minutes (E and W only)."""
    graph = {}
    for ix in range(n):
        edges = [-1] * 8
        if ix + 1 < n:
            edges[2] = dm  # E
        if ix > 0:
            edges[6] = dm  # W
        graph[(100, ix)] = edges
    return graph


def test_grid_round_trip_and_neighbours():
    iy, ix = cellgrid.cell_index(40.7178, -74.0431)
    lat, lon = cellgrid.cell_center(iy, ix)
    assert cellgrid.cell_index(lat, lon) == (iy, ix)
    s, w, n, e = cellgrid.cell_bounds(iy, ix)
    assert s < 40.7178 < n and w < -74.0431 < e
    assert abs((e - w) - cellgrid.LON_STEP) < 1e-12


def test_dm_codec():
    assert to_dm(12.34) == 123 and from_dm(123) == 12.3
    assert to_dm(None) == -1 and from_dm(-1) is None
    assert category_slot("grocery", 1) == 0
    assert category_slot("grocery", 3) == 2
    assert category_slot("gym", 1) == 3  # gym is the 2nd category


def test_dijkstra_respects_budget():
    graph = line_graph(10)  # 5 minutes a hop
    reached = isochrone.dijkstra(graph, (100, 0), 12.0)
    assert sorted(ix for _, ix in reached) == [0, 1, 2]
    assert reached[(100, 2)] == 10.0


def test_dijkstra_takes_the_shortcut():
    graph = line_graph(3, dm=100)
    graph[(100, 0)][2] = 300  # slow direct edge ...
    graph[(100, 0)][1] = 40  # ... NE of cell 0 is a faster way around
    graph[(101, 1)] = [-1] * 8
    graph[(101, 1)][3] = 40  # SE back down to (100, 2)
    reached = isochrone.dijkstra(graph, (100, 0), 30.0)
    assert reached[(100, 2)] == 8.0


def test_nearest_graph_cell_and_disc():
    graph = line_graph(3)
    lat, lon = cellgrid.cell_center(100, 1)
    assert isochrone.nearest_graph_cell(graph, lat, lon) == (100, 1)
    lat2, lon2 = cellgrid.cell_center(102, 1)  # two rows up: found within the ring limit
    assert isochrone.nearest_graph_cell(graph, lat2, lon2) == (100, 1)
    assert isochrone.nearest_graph_cell(graph, lat2 + 5, lon2) is None
    disc = isochrone.disc_cells(40.7, -74.0, 1000.0)
    assert len(disc) >= 3 and cellgrid.cell_index(40.7, -74.0) in disc


def ring_area(ring):
    return 0.5 * sum(
        ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)
    )


def test_polygon_of_a_rectangle_of_cells():
    cells = {(10 + dy, 20 + dx) for dy in range(2) for dx in range(3)}
    geo = isochrone.cells_to_geometry(cells, smooth=0)
    assert geo["type"] == "MultiPolygon" and len(geo["coordinates"]) == 1
    ring = geo["coordinates"][0][0]
    assert ring[0] == ring[-1] and len(ring) == 5  # 4 corners, closed
    expected = 6 * cellgrid.LAT_STEP * cellgrid.LON_STEP
    assert abs(ring_area(ring) - expected) < expected * 0.01


def test_polygon_has_hole_and_separate_islands():
    ring_cells = {(y, x) for y in range(5) for x in range(5)} - {(2, 2)}
    geo = isochrone.cells_to_geometry(ring_cells, smooth=0)
    assert len(geo["coordinates"]) == 1 and len(geo["coordinates"][0]) == 2  # outer + hole
    two = isochrone.cells_to_geometry({(0, 0), (0, 5)}, smooth=2)
    assert len(two["coordinates"]) == 2
    assert isochrone.cells_to_geometry(set()) is None


def test_combine_and_area():
    a, b = {(0, 0), (0, 1)}, {(0, 1), (0, 2)}
    assert isochrone.combine([a, b], "intersect") == {(0, 1)}
    assert isochrone.combine([a, b], "union") == {(0, 0), (0, 1), (0, 2)}
    assert isochrone.combine([], "union") == set()
    assert 0.2 < isochrone.area_sq_mi(1, 40.7) < 0.3


class FakeCursor:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.rows = next((r for t, r in self.rows_by_table.items() if t in sql), [])

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table

    def cursor(self):
        return FakeCursor(self.rows_by_table)

    def rollback(self):
        pass


def test_load_graph_and_reach_walk():
    lat, lon = cellgrid.cell_center(100, 1)
    rows = []
    for ix in range(4):
        la, lo = cellgrid.cell_center(100, ix)
        edges = [-1] * 8
        edges[2] = 60
        edges[6] = 60
        rows.append({"latitude": la, "longitude": lo, "edges_dm": edges})
    conn = FakeConn({"cell_graph": rows})
    got = reach.reach(conn, lat, lon, "walk", 7)
    assert got is not None and got.mode == "walk"
    assert set(got.cells) == {(100, 0), (100, 1), (100, 2)}  # 6 min per hop, 7 min budget


def test_reach_returns_none_without_data():
    assert reach.reach(FakeConn({"cell_graph": []}), 40.7, -74.0, "drive", 30) is None


def test_clamp_minutes():
    assert reach.clamp_minutes("walk", None) == 15
    assert reach.clamp_minutes("walk", 1000) == 45
    assert reach.clamp_minutes("drive", 0) == 1


def test_rail_trip_minutes_uses_matrix_and_walks():
    routing_data.clear_cache()
    stations = [(1000, "Alpha", 40.7000, -74.0000), (1001, "Beta", 40.7500, -73.9000)]
    # Alpha -> Beta takes 25.0 min (250 dm); Beta -> Alpha unreachable
    conn = FakeConn(
        {
            "routing_hubs": stations,
            "rail_matrix": [(1000, [-1, 250]), (1001, [-1, -1])],
        }
    )
    # origin ~0.1 mi from Alpha, destination ~0.1 mi from Beta
    got = routing_data.rail_trip_minutes(conn, (40.7010, -74.0000), (40.7510, -73.9000))
    assert got is not None
    minutes, label = got
    assert label == "Alpha to Beta"
    assert 25.0 < minutes < 35.0
    routing_data.clear_cache()
    assert routing_data.rail_trip_minutes(FakeConn({"routing_hubs": []}), (40.7, -74.0), (40.75, -73.9)) is None
