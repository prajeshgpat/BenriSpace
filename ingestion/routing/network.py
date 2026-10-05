"""OSM road network -> Pandana contraction-hierarchy network, one tile at a time.

`fetch_network` is the only place that touches OpenStreetMap, so it is the swap point when the
region grows: Overpass (via osmnx) is fine for a few hundred tiles; a 5 hour radius should read a
Geofabrik extract instead (osmium / pyrosm, one `NetworkData` per tile) and keep everything else.

Edge cost is minutes:
  walk   length / 80.467 m per minute (3 mph), every way both directions
  drive  length / (OSM maxspeed, else the highway-class speed below) x 1 / DRIVE_SPEED_FACTOR,
         one-way streets respected. Free flow only: no live or historical traffic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common.routing import WALK_M_PER_MIN

DRIVE_SPEED_FACTOR = 0.8  # signals, turns, parking and congestion on top of free-flow speed
KMH_PER_MPH = 1.609344
# Highway-class defaults (km/h) for ways without a maxspeed tag.
DRIVE_HWY_SPEEDS = {
    "motorway": 50 * KMH_PER_MPH,
    "trunk": 40 * KMH_PER_MPH,
    "primary": 30 * KMH_PER_MPH,
    "secondary": 27 * KMH_PER_MPH,
    "tertiary": 24 * KMH_PER_MPH,
    "unclassified": 22 * KMH_PER_MPH,
    "residential": 20 * KMH_PER_MPH,
    "living_street": 10 * KMH_PER_MPH,
    "service": 10 * KMH_PER_MPH,
}
DRIVE_FALLBACK_KMH = 20 * KMH_PER_MPH
# The sparse network used for the far pad of a drive tile and for long hub trips.
ARTERIAL_FILTER = (
    '["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|'
    'secondary_link"]["access"!~"private|no"]'
)


@dataclass
class NetworkData:
    """A road network as flat arrays: the memory-light form kept between steps."""

    node_ids: np.ndarray  # int64
    x: np.ndarray  # longitude, float64
    y: np.ndarray  # latitude, float64
    edge_u: np.ndarray  # int64 node ids
    edge_v: np.ndarray
    minutes: np.ndarray  # float32

    @property
    def n_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def n_edges(self) -> int:
        return len(self.edge_u)


def configure_osmnx(cache_folder: str = "data/cache/osmnx") -> None:
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.cache_folder = cache_folder
    ox.settings.log_console = False
    ox.settings.requests_timeout = 300
    ox.settings.http_user_agent = "BenriSpace-ingestion/1.0 (contact: prajeshgpat@gmail.com)"


def fetch_network(
    box: tuple[float, float, float, float], mode: str, arterial_only: bool = False
) -> NetworkData:
    """Download and convert the network inside box = (south, west, north, east).
    The networkx graph is dropped before returning."""
    import osmnx as ox

    south, west, north, east = box
    bbox = (west, south, east, north)  # osmnx order: left, bottom, right, top
    if mode == "walk":
        graph = ox.graph_from_bbox(bbox, network_type="walk", simplify=True)
    elif arterial_only:
        graph = ox.graph_from_bbox(bbox, custom_filter=ARTERIAL_FILTER, simplify=True)
    else:
        graph = ox.graph_from_bbox(bbox, network_type="drive", simplify=True)
    if mode == "drive":
        graph = ox.routing.add_edge_speeds(
            graph, hwy_speeds=DRIVE_HWY_SPEEDS, fallback=DRIVE_FALLBACK_KMH
        )
        graph = ox.routing.add_edge_travel_times(graph)
    nodes, edges = ox.graph_to_gdfs(graph)
    edges = edges.reset_index()
    if mode == "walk":
        minutes = edges["length"].to_numpy() / WALK_M_PER_MIN
    else:
        minutes = edges["travel_time"].to_numpy() / 60.0 / DRIVE_SPEED_FACTOR
    data = NetworkData(
        node_ids=nodes.index.to_numpy(dtype=np.int64),
        x=nodes["x"].to_numpy(dtype=np.float64),
        y=nodes["y"].to_numpy(dtype=np.float64),
        edge_u=edges["u"].to_numpy(dtype=np.int64),
        edge_v=edges["v"].to_numpy(dtype=np.int64),
        minutes=minutes.astype(np.float32),
    )
    del graph, nodes, edges
    return data


def merge_networks(a: NetworkData, b: NetworkData) -> NetworkData:
    """Union of two networks (same mode). Nodes dedupe by OSM id; of parallel edges keep the
    fastest."""
    ids = np.concatenate([a.node_ids, b.node_ids])
    _, first = np.unique(ids, return_index=True)
    x = np.concatenate([a.x, b.x])[first]
    y = np.concatenate([a.y, b.y])[first]
    u = np.concatenate([a.edge_u, b.edge_u])
    v = np.concatenate([a.edge_v, b.edge_v])
    m = np.concatenate([a.minutes, b.minutes])
    order = np.lexsort((m, v, u))  # per (u, v): fastest first
    u, v, m = u[order], v[order], m[order]
    keep = np.ones(len(u), dtype=bool)
    keep[1:] = (u[1:] != u[:-1]) | (v[1:] != v[:-1])
    return NetworkData(ids[first], x, y, u[keep], v[keep], m[keep])


def to_pandana(data: NetworkData):
    """Build the Pandana network (contraction hierarchy). Edges whose ends are not nodes are
    dropped, as are self loops."""
    import pandana as pdna
    import pandas as pd

    known = np.isin(data.edge_u, data.node_ids) & np.isin(data.edge_v, data.node_ids)
    keep = known & (data.edge_u != data.edge_v)
    nodes_x = pd.Series(data.x, index=pd.Index(data.node_ids, name="id"))
    nodes_y = pd.Series(data.y, index=nodes_x.index)
    return pdna.Network(
        nodes_x,
        nodes_y,
        pd.Series(data.edge_u[keep]),
        pd.Series(data.edge_v[keep]),
        pd.DataFrame({"minutes": data.minutes[keep].astype(np.float64)}),
        twoway=False,
    )
