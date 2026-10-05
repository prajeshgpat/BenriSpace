"""Cells reachable from a point within N minutes, by mode (walk, drive, transit).

walk / drive  Dijkstra over the precomputed cell graph (api/isochrone.py).
transit       walk to nearby rail stations on the walk graph, ride the precomputed station-to-
              station minutes (rail_matrix), then walk out from every station reached: the
              cells within the remaining walking time (straight line / 1.3 circuity).
Returns None when the routing tables have nothing for the area; callers then fall back to the
straight-line circle (api/triangulate.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from api import isochrone, routing_data
from common.cellgrid import CellKey, cell_index
from common.routing import CIRCUITY, WALK_M_PER_MIN, from_dm

MAX_MINUTES = {"walk": 45, "drive": 90, "transit": 120}
DEFAULT_MINUTES = {"walk": 15, "drive": 30, "transit": 45}


@dataclass
class Reach:
    cells: dict[CellKey, float]  # cell -> minutes from the origin
    mode: str
    minutes: float


def clamp_minutes(mode: str, minutes: float | None) -> float:
    value = DEFAULT_MINUTES[mode] if minutes is None else minutes
    return float(max(1, min(MAX_MINUTES[mode], value)))


def reach(conn, lat: float, lon: float, mode: str, minutes: float) -> Reach | None:
    minutes = clamp_minutes(mode, minutes)
    if mode == "transit":
        cells = _transit_cells(conn, lat, lon, minutes)
    else:
        graph = routing_data.load_graph(conn, mode, routing_data.graph_box(lat, lon, minutes, mode))
        start = isochrone.nearest_graph_cell(graph, lat, lon)
        cells = isochrone.dijkstra(graph, start, minutes) if start is not None else {}
    return Reach(cells, mode, minutes) if cells else None


def _transit_cells(conn, lat: float, lon: float, minutes: float) -> dict[CellKey, float]:
    walk_cap = min(minutes, routing_data.WALK_ACCESS_MAX_MIN)
    graph = routing_data.load_graph(
        conn, "walk", routing_data.graph_box(lat, lon, walk_cap, "walk")
    )
    start = isochrone.nearest_graph_cell(graph, lat, lon)
    if start is None:
        return {}
    cells = isochrone.dijkstra(graph, start, walk_cap)
    stations = routing_data.rail_stations(conn)
    if not stations:
        return cells
    access = []  # (walk minutes, column, station id)
    for col, (sid, _name, slat, slon) in enumerate(stations):
        t = cells.get(cell_index(slat, slon))
        if t is not None:
            access.append((t, col, sid))
    access.sort()
    access = access[: routing_data.STATION_CANDIDATES]
    rows = routing_data.rail_rows(conn, [sid for _, _, sid in access])
    arrive: dict[int, float] = {}
    for walk_in, _col, sid in access:
        row = rows.get(sid)
        if row is None:
            continue
        for col_b, dm in enumerate(row):
            ride = from_dm(dm)
            if ride is None:
                continue
            total = walk_in + ride
            if total < minutes and total < arrive.get(col_b, minutes):
                arrive[col_b] = total
    for col_b, at in arrive.items():
        _sid, _name, slat, slon = stations[col_b]
        left = min(minutes - at, routing_data.WALK_ACCESS_MAX_MIN)
        for key in isochrone.disc_cells(slat, slon, left * WALK_M_PER_MIN / CIRCUITY):
            if at + 0.0 < cells.get(key, minutes + 1):
                cells[key] = at
    return cells
