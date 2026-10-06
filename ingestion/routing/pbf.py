"""Road networks from Geofabrik .osm.pbf extracts: the full-region replacement for Overpass.

    python -m ingestion.routing.pbf                       # every build/osm/*.osm.pbf, whole grid
    python -m ingestion.routing.pbf --bbox 40.70,-74.10,40.77,-74.02 --out build/routing/jc

One pass over each extract builds the walk and the drive network for a bounding box, with the
same tag rules and edge costs as the Overpass path (`network.WALK_FILTER` / `DRIVE_FILTER`,
`network.parse_osm`), and saves each as flat arrays (`build/routing/<mode>.npz`). Ways that
cross a state line appear in two extracts; duplicate edges collapse to the fastest.

Distances are miles and speeds mph. Needs the `routing` extra plus `osmium` (pyosmium).
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from array import array
from pathlib import Path

import numpy as np

from common.routing import WALK_MPH
from ingestion.routing.network import (
    DRIVE_SPEED_FACTOR,
    MI_PER_DEG_LAT,
    NetworkData,
    oneway,
    way_speed_mph,
)

DEFAULT_PBF_DIR = Path("build/osm")
DEFAULT_OUT_DIR = Path("build/routing")
# Bounds of the geohash6 grid (south, west, north, east), padded so trips that leave the region
# and come back are still found.
GRID_BBOX = (39.85, -75.20, 42.00, -71.85)
REGION_PAD_MI = 15.0

# The Overpass filters, as Python. Overpass `!~` is a regex search, so these match substrings.
WALK_EXCLUDED_HIGHWAY = (
    "motorway", "bus_guideway", "construction", "proposed", "raceway", "abandoned", "razed",
    "planned", "platform", "no", "corridor", "elevator", "steps",
)  # fmt: skip
DRIVE_HIGHWAYS = frozenset(
    {
        "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
        "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
        "residential", "living_street", "service",
    }
)  # fmt: skip
ARTERIAL_HIGHWAYS = frozenset(
    {
        "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
        "secondary", "secondary_link",
    }
)  # fmt: skip
# Roads a drive-mode cell is snapped to when building the cell graph (see travel.fast_snapper).
COLLECTOR_HIGHWAYS = ARTERIAL_HIGHWAYS | {"tertiary", "tertiary_link"}
_BLOCKED_ACCESS = ("private", "no")
_BLOCKED_SERVICE = ("parking_aisle", "driveway", "private")


def _has(value: str | None, needles: tuple[str, ...]) -> bool:
    return value is not None and any(n in value for n in needles)


def walk_ok(tags: dict) -> bool:
    highway = tags.get("highway")
    return (
        highway is not None
        and not _has(highway, WALK_EXCLUDED_HIGHWAY)
        and tags.get("foot") != "no"
        and not _has(tags.get("access"), _BLOCKED_ACCESS)
        and tags.get("area") != "yes"
    )


def drive_ok(tags: dict) -> bool:
    return (
        tags.get("highway") in DRIVE_HIGHWAYS
        and not _has(tags.get("access"), _BLOCKED_ACCESS)
        and tags.get("motor_vehicle") != "no"
        and not _has(tags.get("service"), _BLOCKED_SERVICE)
        and tags.get("area") != "yes"
    )


def arterial_ok(tags: dict) -> bool:
    """The sparse backbone for long drives (airports, rail stations): `network.ARTERIAL_FILTER`."""
    return tags.get("highway") in ARTERIAL_HIGHWAYS and not _has(
        tags.get("access"), _BLOCKED_ACCESS
    )


def collector_ok(tags: dict) -> bool:
    return tags.get("highway") in COLLECTOR_HIGHWAYS and not _has(
        tags.get("access"), _BLOCKED_ACCESS
    )


class _Builder:
    """Edges and node positions accumulated in typed arrays (a few bytes each, not objects)."""

    def __init__(self) -> None:
        self.node_ids = array("q")
        self.x = array("d")
        self.y = array("d")
        self.u = array("q")
        self.v = array("q")
        self.minutes = array("f")

    def add_way(
        self, refs: list[int], xs: list[float], ys: list[float], mph: float, direction: int
    ):
        self.node_ids.extend(refs)
        self.x.extend(xs)
        self.y.extend(ys)
        for i in range(len(refs) - 1):
            ya, yb = ys[i], ys[i + 1]
            dy = (yb - ya) * MI_PER_DEG_LAT
            dx = (xs[i + 1] - xs[i]) * MI_PER_DEG_LAT * math.cos(math.radians((ya + yb) * 0.5))
            minutes = math.hypot(dx, dy) / mph * 60.0
            if direction >= 0:
                self.u.append(refs[i])
                self.v.append(refs[i + 1])
                self.minutes.append(minutes)
            if direction <= 0:
                self.u.append(refs[i + 1])
                self.v.append(refs[i])
                self.minutes.append(minutes)

    def finish(self) -> NetworkData:
        ids = np.frombuffer(self.node_ids, dtype=np.int64)
        uniq, first = np.unique(ids, return_index=True)
        u = np.frombuffer(self.u, dtype=np.int64)
        v = np.frombuffer(self.v, dtype=np.int64)
        m = np.frombuffer(self.minutes, dtype=np.float32)
        order = np.lexsort((m, v, u))  # per (u, v): fastest first
        u, v, m = u[order], v[order], m[order]
        keep = np.ones(len(u), dtype=bool)
        keep[1:] = (u[1:] != u[:-1]) | (v[1:] != v[:-1])
        keep &= u != v
        return NetworkData(
            node_ids=uniq,
            x=np.frombuffer(self.x, dtype=np.float64)[first],
            y=np.frombuffer(self.y, dtype=np.float64)[first],
            edge_u=u[keep],
            edge_v=v[keep],
            minutes=m[keep],
        )


def read_extracts(
    paths: list[Path],
    bbox: tuple[float, float, float, float],
    modes: tuple[str, ...] = ("walk", "drive"),
) -> dict[str, NetworkData]:
    """{mode: NetworkData} for every routable way with at least one node inside bbox =
    (south, west, north, east). Modes: walk, drive, arterial (drive speeds, big roads only), collector (arterials + tertiary)."""
    import osmium

    south, west, north, east = bbox
    builders = {m: _Builder() for m in modes}
    for path in paths:
        t0 = time.time()
        processor = (
            osmium.FileProcessor(str(path))
            .with_locations()
            .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
            .with_filter(osmium.filter.KeyFilter("highway"))
        )
        for way in processor:
            tags = dict(way.tags)
            want_walk = "walk" in builders and walk_ok(tags)
            want_drive = "drive" in builders and drive_ok(tags)
            want_arterial = "arterial" in builders and arterial_ok(tags)
            want_collector = "collector" in builders and collector_ok(tags)
            if not (want_walk or want_drive or want_arterial or want_collector):
                continue
            refs: list[int] = []
            xs: list[float] = []
            ys: list[float] = []
            inside = False
            for node in way.nodes:
                loc = node.location
                if not loc.valid():
                    continue
                x, y = loc.lon, loc.lat
                refs.append(node.ref)
                xs.append(x)
                ys.append(y)
                inside = inside or (south <= y <= north and west <= x <= east)
            if not inside or len(refs) < 2:
                continue
            if want_walk:
                builders["walk"].add_way(refs, xs, ys, WALK_MPH, 0)
            if want_drive or want_arterial or want_collector:
                mph = way_speed_mph(tags) * DRIVE_SPEED_FACTOR
                direction = oneway(tags)
                if want_collector:
                    builders["collector"].add_way(refs, xs, ys, mph, direction)
                if want_drive:
                    builders["drive"].add_way(refs, xs, ys, mph, direction)
                if want_arterial:
                    builders["arterial"].add_way(refs, xs, ys, mph, direction)
        print(f"[pbf] {path.name}: {time.time() - t0:.0f}s", file=sys.stderr)
    return {m: b.finish() for m, b in builders.items()}


def keep_connected(data: NetworkData, min_nodes: int = 5000) -> NetworkData:
    """Drops road fragments (parking-lot loops, private estates, mapping gaps) that are not
    joined to the main network, so a point never snaps onto one and finds nothing reachable.
    Components are weakly connected; any of at least `min_nodes` nodes is kept."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    n = data.n_nodes
    u = np.searchsorted(data.node_ids, data.edge_u)
    v = np.searchsorted(data.node_ids, data.edge_v)
    graph = coo_matrix((np.ones(len(u), dtype=np.int8), (u, v)), shape=(n, n))
    _, label = connected_components(graph, directed=False)
    keep_node = np.bincount(label)[label] >= min_nodes
    keep_edge = keep_node[u] & keep_node[v]
    return NetworkData(
        data.node_ids[keep_node],
        data.x[keep_node],
        data.y[keep_node],
        data.edge_u[keep_edge],
        data.edge_v[keep_edge],
        data.minutes[keep_edge],
    )


def save_network(data: NetworkData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        node_ids=data.node_ids,
        x=data.x,
        y=data.y,
        edge_u=data.edge_u,
        edge_v=data.edge_v,
        minutes=data.minutes,
    )


def load_network(path: Path) -> NetworkData:
    with np.load(path) as z:
        return NetworkData(z["node_ids"], z["x"], z["y"], z["edge_u"], z["edge_v"], z["minutes"])


def pad_bbox(
    bbox: tuple[float, float, float, float], pad_mi: float
) -> tuple[float, float, float, float]:
    south, west, north, east = bbox
    d_lat = pad_mi / MI_PER_DEG_LAT
    d_lon = pad_mi / (MI_PER_DEG_LAT * math.cos(math.radians((south + north) / 2.0)))
    return south - d_lat, west - d_lon, north + d_lat, east + d_lon


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pbf", nargs="*", type=Path, help="extracts (default build/osm/*.osm.pbf)")
    ap.add_argument("--bbox", help="south,west,north,east (default: the grid, padded)")
    ap.add_argument("--modes", default="walk,drive,arterial,collector")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args(argv)

    paths = args.pbf or sorted(DEFAULT_PBF_DIR.glob("*.osm.pbf"))
    if not paths:
        raise SystemExit(f"no .osm.pbf files in {DEFAULT_PBF_DIR}")
    if args.bbox:
        bbox = tuple(float(v) for v in args.bbox.split(","))
    else:
        bbox = pad_bbox(GRID_BBOX, REGION_PAD_MI)
    modes = tuple(m for m in args.modes.split(",") if m)
    started = time.time()
    networks = read_extracts(paths, bbox, modes)  # type: ignore[arg-type]
    for mode, data in networks.items():
        save_network(data, args.out / f"{mode}.npz")
        print(f"[pbf] {mode}: {data.n_nodes:,} nodes, {data.n_edges:,} edges", file=sys.stderr)
    print(f"[pbf] done in {time.time() - started:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
