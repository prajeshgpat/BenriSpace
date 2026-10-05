"""OSM road network -> Pandana contraction-hierarchy network, one tile at a time.

`fetch_network` is the only place that touches OpenStreetMap, so it is the swap point when the
region grows: Overpass (plain JSON, parsed to arrays) is fine for a few hundred tiles; a 5 hour radius should read a
Geofabrik extract instead (osmium / pyrosm, one `NetworkData` per tile) and keep everything else.

Edge cost is minutes:
  walk   length / 80.467 m per minute (3 mph), every way both directions
  drive  length / (OSM maxspeed, else the highway-class speed below) x 1 / DRIVE_SPEED_FACTOR,
         one-way streets respected. Free flow only: no live or historical traffic.
"""

from __future__ import annotations

import itertools
import math
import os
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


WALK_FILTER = (
    '["highway"]["highway"!~"motorway|motorway_link|bus_guideway|construction|proposed|raceway|'
    'abandoned|razed|planned|platform|no|corridor|elevator|steps"]'
    '["foot"!="no"]["access"!~"private|no"]["area"!="yes"]'
)
DRIVE_FILTER = (
    '["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|'
    'secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service)$"]'
    '["access"!~"private|no"]["motor_vehicle"!="no"]["service"!~"parking_aisle|driveway|private"]'
    '["area"!="yes"]'
)
MAX_CHUNK_DEG = {"walk": 0.12, "drive": 0.2, "arterial": 0.6}
M_PER_DEG_LAT = 111_320.0
OVERPASS_TIMEOUT_S = 300


def _maxspeed_kmh(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        value = float(raw.split()[0])
    except ValueError:
        return None
    return value * KMH_PER_MPH if "mph" in raw else value


def _way_speed_kmh(tags: dict) -> float:
    explicit = _maxspeed_kmh(tags.get("maxspeed"))
    if explicit and explicit > 0:
        return explicit
    highway = tags.get("highway", "")
    return DRIVE_HWY_SPEEDS.get(highway.removesuffix("_link"), DRIVE_FALLBACK_KMH)


def _oneway(tags: dict) -> int:
    """1 = forward only, -1 = reverse only, 0 = both ways (drive)."""
    value = tags.get("oneway")
    if value in ("yes", "true", "1"):
        return 1
    if value == "-1":
        return -1
    if tags.get("junction") in ("roundabout", "circular") or tags.get("highway") in (
        "motorway",
        "motorway_link",
    ):
        return 1 if value != "no" else 0
    return 0


def parse_osm(elements: list[dict], mode: str) -> NetworkData:
    """Overpass JSON elements (ways with tags + their nodes) -> NetworkData. Every consecutive
    node pair of a way is an edge (no simplification: Pandana's contraction hierarchy does the
    shortcutting), so memory stays flat arrays instead of a networkx graph."""
    coords: dict[int, tuple[float, float]] = {}
    ways = []
    for el in elements:
        if el["type"] == "node":
            coords[el["id"]] = (el["lon"], el["lat"])
        elif el["type"] == "way" and len(el.get("nodes", ())) >= 2:
            ways.append(el)
    us: list[int] = []
    vs: list[int] = []
    mins: list[float] = []
    for way in ways:
        tags = way.get("tags", {})
        nodes = [n for n in way["nodes"] if n in coords]
        if mode == "walk":
            m_per_min, direction = WALK_M_PER_MIN, 0
        else:
            m_per_min = _way_speed_kmh(tags) * 1000.0 / 60.0 * DRIVE_SPEED_FACTOR
            direction = _oneway(tags)
        for a, b in itertools.pairwise(nodes):
            (xa, ya), (xb, yb) = coords[a], coords[b]
            dy = (yb - ya) * M_PER_DEG_LAT
            dx = (xb - xa) * M_PER_DEG_LAT * math.cos(math.radians((ya + yb) / 2.0))
            minutes = math.hypot(dx, dy) / m_per_min
            if direction >= 0:
                us.append(a), vs.append(b), mins.append(minutes)
            if direction <= 0:
                us.append(b), vs.append(a), mins.append(minutes)
    used = np.unique(np.array(us + vs, dtype=np.int64)) if us else np.empty(0, dtype=np.int64)
    xy = np.array([coords[int(n)] for n in used], dtype=np.float64).reshape(-1, 2)
    return NetworkData(
        node_ids=used,
        x=xy[:, 0],
        y=xy[:, 1],
        edge_u=np.array(us, dtype=np.int64),
        edge_v=np.array(vs, dtype=np.int64),
        minutes=np.array(mins, dtype=np.float32),
    )


def _query(box: tuple[float, float, float, float], tag_filter: str) -> str:
    south, west, north, east = box
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];"
        f"way{tag_filter}({south:.5f},{west:.5f},{north:.5f},{east:.5f});"
        "(._;>;);out body qt;"
    )


def _overpass(query: str, client) -> dict:
    """One Overpass query with a patient retry loop (the public server 504s under bulk load)
    and an on-disk cache so a re-run of a tile costs no network."""
    import hashlib
    import json
    import sys
    import time
    from pathlib import Path

    from common.overpass import post_overpass_query

    cache = Path(os.environ.get("ROUTING_CACHE_DIR", "data/cache/routing")) / (
        hashlib.sha1(query.encode()).hexdigest() + ".json"
    )
    if cache.exists():
        return json.loads(cache.read_text())
    for attempt in range(1, 9):
        try:
            data = post_overpass_query(query, OVERPASS_TIMEOUT_S + 30, client)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
            return data
        except Exception as exc:
            if attempt == 8:
                raise
            wait = min(300, 30 * attempt)
            print(f"[routing] overpass failed ({exc!s:.80}); retry {attempt}/7 in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_network(
    box: tuple[float, float, float, float], mode: str, arterial_only: bool = False
) -> NetworkData:
    """Download and convert the network inside box = (south, west, north, east), in chunks of at
    most MAX_CHUNK_DEG so one Overpass query stays small. This is the swap point for a Geofabrik
    extract at larger scale (see module docstring)."""
    from common.overpass import make_client

    if mode == "walk":
        tag_filter, chunk = WALK_FILTER, MAX_CHUNK_DEG["walk"]
    elif arterial_only:
        tag_filter, chunk = ARTERIAL_FILTER, MAX_CHUNK_DEG["arterial"]
    else:
        tag_filter, chunk = DRIVE_FILTER, MAX_CHUNK_DEG["drive"]
    south, west, north, east = box
    merged: NetworkData | None = None
    with make_client() as client:
        lat = south
        while lat < north:
            lon = west
            while lon < east:
                part_box = (lat, lon, min(lat + chunk, north), min(lon + chunk, east))
                data = _overpass(_query(part_box, tag_filter), client)
                part = parse_osm(data.get("elements", []), mode)
                merged = part if merged is None else merge_networks(merged, part)
                lon += chunk
            lat += chunk
    assert merged is not None
    return merged


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
