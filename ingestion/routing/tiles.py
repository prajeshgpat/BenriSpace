"""Tile planning for the routing precompute: bounded memory at any radius.

A tile is a rectangle of whole geohash6 cells (its "core"). Each cell belongs to exactly one
tile, so tiles can be computed independently, in any order, in parallel, and re-run alone.
For one tile the network is fetched for the core plus a pad as wide as the search cap, so
routes that start in the core and leave it are still found. Memory is therefore set by the
tile size and the pad, never by the size of the region: a 5 hour radius is just more tiles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from common.cellgrid import LAT_STEP, LON_STEP, cell_index

M_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class Tile:
    iy0: int  # inclusive
    ix0: int
    iy1: int  # exclusive
    ix1: int

    @property
    def n_cells(self) -> int:
        return (self.iy1 - self.iy0) * (self.ix1 - self.ix0)

    def box(self) -> tuple[float, float, float, float]:
        """Core as (south, west, north, east)."""
        return (
            self.iy0 * LAT_STEP - 90.0,
            self.ix0 * LON_STEP - 180.0,
            self.iy1 * LAT_STEP - 90.0,
            self.ix1 * LON_STEP - 180.0,
        )

    def contains(self, iy: int, ix: int) -> bool:
        return self.iy0 <= iy < self.iy1 and self.ix0 <= ix < self.ix1

    def label(self) -> str:
        return f"{self.iy0}_{self.ix0}"


def plan_tiles(
    bbox: tuple[float, float, float, float], cells_y: int, cells_x: int
) -> list[Tile]:
    """Cover bbox (south, west, north, east) with tiles of cells_y x cells_x cells, aligned to a
    fixed global lattice so the same cell always lands in the same tile."""
    south, west, north, east = bbox
    iy_a, ix_a = cell_index(south, west)
    iy_b, ix_b = cell_index(north, east)
    tiles = []
    for ty in range(iy_a // cells_y, iy_b // cells_y + 1):
        for tx in range(ix_a // cells_x, ix_b // cells_x + 1):
            tiles.append(Tile(ty * cells_y, tx * cells_x, (ty + 1) * cells_y, (tx + 1) * cells_x))
    return tiles


def pad_box(
    box: tuple[float, float, float, float], pad_m: float
) -> tuple[float, float, float, float]:
    """Grow (south, west, north, east) by pad_m metres on every side."""
    south, west, north, east = box
    d_lat = pad_m / M_PER_DEG_LAT
    mid_lat = (south + north) / 2.0
    d_lon = pad_m / (M_PER_DEG_LAT * max(0.05, math.cos(math.radians(mid_lat))))
    return south - d_lat, west - d_lon, north + d_lat, east + d_lon


def box_to_nsew(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    south, west, north, east = box
    return north, south, east, west
