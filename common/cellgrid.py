"""The geohash6 grid as plain integer arithmetic (no geohash library, no numpy).

A geohash6 cell is 15 longitude bits x 15 latitude bits: 360/2^15 = 0.010986 degrees of
longitude (0.58 mi at NYC) by 180/2^15 = 0.005493 degrees of latitude (0.38 mi). Cells are
addressed by an integer (iy, ix) pair so neighbours are +-1 steps. Shared by the routing
precompute (ingestion/routing) and the API's isochrone search (api/isochrone.py), which
ships to Lambda, so keep it dependency-free.
"""

from __future__ import annotations

LAT_STEP = 180.0 / 2**15
LON_STEP = 360.0 / 2**15

# (d_iy, d_ix) for N, NE, E, SE, S, SW, W, NW: the order of cell_graph.edges_dm.
NEIGHBORS: tuple[tuple[int, int], ...] = (
    (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1),
)  # fmt: skip

CellKey = tuple[int, int]  # (iy, ix)


def cell_index(lat: float, lon: float) -> CellKey:
    return int((lat + 90.0) // LAT_STEP), int((lon + 180.0) // LON_STEP)


def cell_center(iy: int, ix: int) -> tuple[float, float]:
    return (iy + 0.5) * LAT_STEP - 90.0, (ix + 0.5) * LON_STEP - 180.0


def cell_bounds(iy: int, ix: int) -> tuple[float, float, float, float]:
    """(south, west, north, east)."""
    south = iy * LAT_STEP - 90.0
    west = ix * LON_STEP - 180.0
    return south, west, south + LAT_STEP, west + LON_STEP
