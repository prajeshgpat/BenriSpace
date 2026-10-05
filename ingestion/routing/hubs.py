"""Drive minutes from every cell to airports and to rail stations, on a sparse backbone.

Hubs are tens to hundreds of miles from many cells, so they cannot share a drive tile's local
network (its pad is sized for the nearest grocery store, not for JFK). Instead one arterial-only
drive network (motorway to secondary roads, `network.ARTERIAL_FILTER`) is built for the whole
region in sub-boxes and merged. Each cell reaches it through a local access leg (straight line to
the nearest backbone node at 15 mph) and then one multi-source search per hub kind gives the
nearest `K_HUBS` hubs and their ids for every node at once.

This is the same approach as the amenity search (one search per category, not one per cell), at
a coarser network; for a 5 hour radius the backbone grows to a few million nodes, which is why it
is held as flat arrays and not a networkx graph.
"""

from __future__ import annotations

import numpy as np

from common.routing import AIRPORTS, RAIL_ID_BASE, UNREACHABLE
from ingestion.routing import network, tiles, travel

K_HUBS = 3
HUB_CAP_MIN = 120.0
BACKBONE_SUBBOX_DEG = 0.5
BACKBONE_PAD_DEG = 0.5
MAX_ACCESS_M = 5000.0  # farther than this from the backbone = no hub minutes for the cell


def airport_rows() -> list[tuple[int, str, str, str, float, float]]:
    return [
        (i + 1, "airport", code, name, lat, lon) for i, (code, name, lat, lon) in enumerate(AIRPORTS)
    ]


def rail_rows(stations) -> list[tuple[int, str, str, str, float, float]]:
    return [
        (RAIL_ID_BASE + i, "rail", s.key, s.name, s.lat, s.lon) for i, s in enumerate(stations)
    ]


def fetch_backbone(region: tuple[float, float, float, float]) -> network.NetworkData:
    """Arterial drive network over region (south, west, north, east) + BACKBONE_PAD_DEG, fetched
    in sub-boxes and merged."""
    south, west, north, east = region
    south, west = south - BACKBONE_PAD_DEG, west - BACKBONE_PAD_DEG
    north, east = north + BACKBONE_PAD_DEG, east + BACKBONE_PAD_DEG
    merged = None
    lat = south
    while lat < north:
        lon = west
        while lon < east:
            box = (lat, lon, min(lat + BACKBONE_SUBBOX_DEG, north), min(lon + BACKBONE_SUBBOX_DEG, east))
            part = network.fetch_network(box, "drive", arterial_only=True)
            merged = part if merged is None else network.merge_networks(merged, part)
            lon += BACKBONE_SUBBOX_DEG
        lat += BACKBONE_SUBBOX_DEG
    assert merged is not None
    return merged


def nearest_hubs(
    net,
    cell_lat: np.ndarray,
    cell_lon: np.ndarray,
    hubs: list[tuple[int, float, float]],
    k: int = K_HUBS,
) -> tuple[np.ndarray, np.ndarray]:
    """(hub_ids, deci-minutes), both (n_cells, k); missing slots are -1. hubs: (id, lat, lon)."""
    import pandas as pd

    node_ids, snap_m, snap_min, _ = travel.snap(net, cell_lat, cell_lon, "drive")
    n = len(cell_lat)
    ids = np.full((n, k), -1, dtype=np.int64)
    dm = np.full((n, k), UNREACHABLE, dtype=np.int16)
    if not hubs:
        return ids, dm
    index = pd.Index([h[0] for h in hubs])
    net.set_pois(
        "hub",
        HUB_CAP_MIN,
        k,
        pd.Series([h[2] for h in hubs], index=index),
        pd.Series([h[1] for h in hubs], index=index),
    )
    res = net.nearest_pois(HUB_CAP_MIN, "hub", num_pois=k, include_poi_ids=True)
    ok_access = snap_m <= MAX_ACCESS_M
    for slot in range(k):
        minutes = res[slot + 1].reindex(node_ids).to_numpy(dtype=np.float64) + snap_min
        hub = res[f"poi{slot + 1}"].reindex(node_ids).to_numpy()
        valid = ok_access & (minutes < HUB_CAP_MIN) & ~pd.isna(hub)
        dm[:, slot] = np.where(valid, np.rint(minutes * 10), UNREACHABLE).astype(np.int16)
        ids[:, slot] = np.where(valid, np.nan_to_num(hub, nan=-1), -1).astype(np.int64)
    return ids, dm
