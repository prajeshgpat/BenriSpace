"""Per-tile travel times on a Pandana network: amenity minutes and the cell-to-cell graph.

Two products, both from the same network and the same snapping of cell centres to nodes:

  amenity_minutes  for each cell, minutes to the nearest, 2nd and 3rd nearest place of every
                   category: ONE multi-source search per category over the whole tile (not one
                   routed query per cell), then a lookup at each cell's node.
  neighbor_minutes for each cell, minutes to each of the 8 neighbouring cell centres: the
                   edges the API runs Dijkstra over for isochrones and triangulation.

Everything here is numpy in, numpy out, so it is unit-testable with a hand-made network.
"""

from __future__ import annotations

import warnings

import numpy as np

from common.cellgrid import NEIGHBORS
from common.routing import (
    CAP_MIN,
    CATEGORIES,
    K_NEAREST,
    MAX_DM,
    UNREACHABLE,
    WALK_M_PER_MIN,
)

MAX_SNAP_M = 1000.0  # a cell centre farther than this from any node is "not on the network"
LOCAL_M_PER_MIN = {"walk": WALK_M_PER_MIN, "drive": 402.0}  # 15 mph from door to the road
M_PER_DEG_LAT = 111_320.0
MIN_EDGE_M_PER_MIN = {"walk": WALK_M_PER_MIN, "drive": 1700.0}  # speed of light for an edge


def _to_dm(minutes: np.ndarray, valid: np.ndarray) -> np.ndarray:
    dm = np.rint(minutes * 10.0)
    dm = np.where(valid & np.isfinite(dm) & (dm >= 0) & (dm <= MAX_DM), dm, UNREACHABLE)
    return dm.astype(np.int16)


def snap(net, lat: np.ndarray, lon: np.ndarray, mode: str):
    """Nearest network node per point. Returns (node_ids, snap_m, snap_min, on_network)."""
    import pandas as pd

    node_ids = np.asarray(net.get_node_ids(pd.Series(lon), pd.Series(lat)))
    nodes = net.nodes_df
    nx_ = nodes["x"].reindex(node_ids).to_numpy()
    ny_ = nodes["y"].reindex(node_ids).to_numpy()
    dy = (ny_ - lat) * M_PER_DEG_LAT
    dx = (nx_ - lon) * M_PER_DEG_LAT * np.cos(np.radians(lat))
    snap_m = np.hypot(dx, dy)
    return node_ids, snap_m, snap_m / LOCAL_M_PER_MIN[mode], snap_m <= MAX_SNAP_M


def amenity_minutes(
    net,
    node_ids: np.ndarray,
    snap_min: np.ndarray,
    on_network: np.ndarray,
    places: dict[str, tuple[np.ndarray, np.ndarray]],
    mode: str,
) -> np.ndarray:
    """(n_cells, len(CATEGORIES) * K_NEAREST) int16 deci-minutes; -1 = not within the cap.
    places maps category -> (lat array, lon array) for places inside the padded tile."""
    import pandas as pd

    cap = CAP_MIN[mode]
    out = np.full((len(node_ids), len(CATEGORIES) * K_NEAREST), UNREACHABLE, dtype=np.int16)
    for ci, category in enumerate(CATEGORIES):
        pts = places.get(category)
        if pts is None or len(pts[0]) == 0:
            continue
        lat, lon = pts
        net.set_pois(category, cap, K_NEAREST, pd.Series(lon), pd.Series(lat))
        res = net.nearest_pois(cap, category, num_pois=K_NEAREST)
        vals = res.reindex(node_ids).to_numpy(dtype=np.float64)  # (n, K)
        total = vals + snap_min[:, None]
        ok = on_network[:, None] & (vals < cap - 1e-6) & (total <= cap)
        out[:, ci * K_NEAREST : (ci + 1) * K_NEAREST] = _to_dm(total, ok)
    return out


def _grid_centres(iy0: int, ix0: int, iy1: int, ix1: int):
    iys, ixs = np.meshgrid(np.arange(iy0, iy1), np.arange(ix0, ix1), indexing="ij")
    iys, ixs = iys.ravel(), ixs.ravel()
    lat = (iys + 0.5) * (180.0 / 2**15) - 90.0
    lon = (ixs + 0.5) * (360.0 / 2**15) - 180.0
    return iys, ixs, lat, lon


def neighbor_minutes(
    net, iy0: int, ix0: int, iy1: int, ix1: int, mode: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Edge minutes for every cell of [iy0,iy1) x [ix0,ix1) to its 8 neighbours.

    Returns (iys, ixs, edges) where edges is (n_cells, 8) int16 deci-minutes in NEIGHBORS order
    (-1 = no usable edge). Time = network time between the two cell centres' nodes + half of each
    centre's door-to-node leg (so a chain of cells counts every leg once), never faster than a
    straight line at the mode's top speed, and capped at the mode's search cap."""
    # Snap the core plus a one-cell ring so edges that cross the tile border are exact.
    ey0, ex0, ey1, ex1 = iy0 - 1, ix0 - 1, iy1 + 1, ix1 + 1
    w = ex1 - ex0
    eys, exs, lat, lon = _grid_centres(ey0, ex0, ey1, ex1)
    node_ids, _, snap_min, on_net = snap(net, lat, lon, mode)
    cap = CAP_MIN[mode]
    core = (eys >= iy0) & (eys < iy1) & (exs >= ix0) & (exs < ix1)
    core_idx = np.flatnonzero(core)
    edges = np.full((len(core_idx), len(NEIGHBORS)), UNREACHABLE, dtype=np.int16)
    for d, (dy, dx) in enumerate(NEIGHBORS):
        nb_idx = core_idx + dy * w + dx
        a, b = node_ids[core_idx], node_ids[nb_idx]
        with warnings.catch_warnings():
            # Pandana warns (and returns a huge value) for pairs in disconnected components.
            warnings.simplefilter("ignore", UserWarning)
            net_min = np.asarray(net.shortest_path_lengths(list(a), list(b)), dtype=np.float64)
        net_min = np.where((net_min < 0) | (net_min > 1e5), np.inf, net_min)
        dlat = (lat[nb_idx] - lat[core_idx]) * M_PER_DEG_LAT
        dlon = (lon[nb_idx] - lon[core_idx]) * M_PER_DEG_LAT * np.cos(np.radians(lat[core_idx]))
        floor = np.hypot(dlat, dlon) / MIN_EDGE_M_PER_MIN[mode]
        total = np.maximum(net_min + 0.5 * (snap_min[core_idx] + snap_min[nb_idx]), floor)
        ok = on_net[core_idx] & on_net[nb_idx] & np.isfinite(net_min) & (total <= cap)
        edges[:, d] = _to_dm(np.where(ok, total, 0.0), ok)
    return eys[core_idx], exs[core_idx], edges
