"""Routing precompute job (Wave 4). Needs the `routing` extra and a database with migration 0022.

    python -m ingestion.routing.run --region jersey_city_hoboken --steps amenity,graph
    python -m ingestion.routing.run --region jersey_city_hoboken --steps transit,hubs
    python -m ingestion.routing.run --all --steps amenity,graph,transit,hubs      # whole metro
    python -m ingestion.routing.run --all --networks build/routing --steps amenity,graph,hubs
        # whole metro from the saved Geofabrik networks (ingestion/routing/pbf.py): no Overpass

Steps (any subset, in this order):
  amenity  cell_travel: minutes to the 1st-3rd nearest place of each category, in the cell's own
           travel mode (walk or drive)
  graph    cell_graph: minutes to the 8 neighbouring cells, for walk and drive (isochrones)
  transit  routing_hubs (rail) + rail_matrix from GTFS
  hubs     routing_hubs (airport) + cell_hubs: drive minutes to the 3 nearest airports / stations

Work is split into tiles (ingestion/routing/tiles.py) so peak memory depends on tile size, not on
the region; a tile is committed before the next starts, so a failed run resumes by re-running
(`--skip-done` skips tiles that already have all their cells). `--dry-run` computes and prints
timings without writing. Timings and peak RSS are printed per tile and in total.
"""

from __future__ import annotations

import argparse
import gc
import json
import resource
import sys
import time
from dataclasses import dataclass, field

import numpy as np

from common.db import get_connection
from common.routing import CAP_MIN, MODES, meta_blob
from ingestion.routing import hubs, network, store, tiles, transit, travel

REGIONS: dict[str, tuple[float, float, float, float]] = {  # south, west, north, east
    "jersey_city_hoboken": (40.700, -74.100, 40.770, -74.020),
    "brooklyn": (40.570, -74.050, 40.740, -73.830),
    "park_slope": (40.660, -73.995, 40.685, -73.960),
}
STEPS = ("amenity", "graph", "transit", "hubs")

# Tile shape in cells (lat x lon) and the pad around it, per mode.
TILE_CELLS = {"walk": (10, 8), "drive": (30, 20)}
PAD_M = {"walk": 3000.0, "drive": 6000.0}
FAR_PAD_M = 45_000.0  # drive pad beyond PAD_M carries arterials only (nearest places up to 45 min)


@dataclass
class Stats:
    tiles: int = 0
    cells: int = 0
    nodes: int = 0
    edges: int = 0
    seconds: dict[str, float] = field(default_factory=dict)

    def add(self, key: str, seconds: float) -> None:
        self.seconds[key] = self.seconds.get(key, 0.0) + seconds


def peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024 if sys.platform == "darwin" else 1024)


def build_tile_network(tile: tiles.Tile, mode: str, stats: Stats):
    core = tile.box()
    t0 = time.time()
    data = network.fetch_network(tiles.pad_box(core, PAD_M[mode]), mode)
    if mode == "drive":
        far = network.fetch_network(tiles.pad_box(core, FAR_PAD_M), "drive", arterial_only=True)
        data = network.merge_networks(data, far)
    stats.add("fetch", time.time() - t0)
    t0 = time.time()
    net = network.to_pandana(data)
    stats.add("build", time.time() - t0)
    stats.nodes += data.n_nodes
    stats.edges += data.n_edges
    return net


def load_pandana(networks_dir, name: str, stats: Stats):
    """A saved network (ingestion/routing/pbf.py) as a Pandana network, with road fragments
    that are not joined to the main network dropped."""
    from pathlib import Path

    from ingestion.routing import pbf

    t0 = time.time()
    data = pbf.keep_connected(pbf.load_network(Path(networks_dir) / f"{name}.npz"))
    net = network.to_pandana(data)
    stats.add(f"{name}_network", time.time() - t0)
    stats.nodes += data.n_nodes
    stats.edges += data.n_edges
    return net


def fast_snapper(networks_dir, net):
    """Snapper onto the saved collector network's nodes (pbf.py `collector`), or None."""
    from pathlib import Path

    from ingestion.routing import pbf

    path = Path(networks_dir) / "collector.npz"
    if not path.exists():
        return None
    data = pbf.load_network(path)
    return travel.FastSnapper(data.node_ids, data.x, data.y, net.nodes_df.index.to_numpy())


GRAPH_ROWS = 25  # grid rows per neighbour-minutes call: bounds memory and snapping cost


def run_region(conn, networks_dir, region, modes, steps, stats: Stats, dry_run: bool) -> None:
    """The whole region at once from saved networks: amenity minutes for every cell in its own
    mode, then the cell-to-cell graph, one mode network at a time."""
    cells = store.read_cells(conn, region)
    stats.tiles, stats.cells = 1, len(cells)
    by_key = {(c.iy, c.ix): i for i, c in enumerate(cells)}
    iy_min = min(c.iy for c in cells)
    iy_max = max(c.iy for c in cells) + 1
    ix_min = min(c.ix for c in cells)
    ix_max = max(c.ix for c in cells) + 1
    places = store.read_places(conn, tiles.pad_box(region, 5000.0)) if "amenity" in steps else {}
    for mode in modes:
        mode_cells = [c for c in cells if c.mode == mode]
        net = load_pandana(networks_dir, mode, stats)
        print(f"[routing] {mode} network ready, peak {peak_rss_mb():.0f} MB", file=sys.stderr)
        if "amenity" in steps and mode_cells:
            t0 = time.time()
            lat = np.array([c.lat for c in mode_cells])
            lon = np.array([c.lon for c in mode_cells])
            node_ids, _, snap_min, on_net = travel.snap(net, lat, lon, mode)
            minutes = travel.amenity_minutes(net, node_ids, snap_min, on_net, places, mode)
            stats.add("amenity_search", time.time() - t0)
            written = 0 if dry_run else store.write_cell_travel(conn, mode_cells, minutes)
            reached = int((minutes >= 0).any(axis=1).sum())
            print(
                f"[routing] {mode} amenity: {len(mode_cells):,} cells, {reached:,} reach a place,"
                f" {written:,} written, {time.time() - t0:.0f}s",
                file=sys.stderr,
            )
        if "graph" in steps:
            t0 = time.time()
            total = 0
            fast = fast_snapper(networks_dir, net) if mode == "drive" else None
            for y0 in range(iy_min, iy_max, GRAPH_ROWS):
                y1 = min(y0 + GRAPH_ROWS, iy_max)
                iys, ixs, edges = travel.neighbor_minutes(net, y0, ix_min, y1, ix_max, mode, fast)
                pick = [by_key.get((int(y), int(x))) for y, x in zip(iys, ixs, strict=True)]
                keep = [r for r, p in enumerate(pick) if p is not None]
                if keep and not dry_run:
                    total += store.write_cell_graph(
                        conn, [cells[pick[r]] for r in keep], mode, edges[np.array(keep)]
                    )
            stats.add("graph_search", time.time() - t0)
            print(
                f"[routing] {mode} graph: {total:,} cells written, {time.time() - t0:.0f}s",
                file=sys.stderr,
            )
        del net
        gc.collect()


def run_hubs_region(conn, networks_dir, region, stats: Stats, dry_run: bool) -> dict:
    """Airport and rail-station drive minutes for every cell, on the saved arterial network."""
    t0 = time.time()
    net = load_pandana(networks_dir, "arterial", stats)
    airports = hubs.airport_rows()
    if not dry_run:
        store.write_hubs(conn, airports)
    kinds = {"airport": [(r[0], r[4], r[5]) for r in airports]}
    rail = store.read_hubs(conn, "rail")
    if rail:
        kinds["rail"] = [(r[0], r[3], r[4]) for r in rail]
    cells = store.read_cells(conn, region)
    lat = np.array([c.lat for c in cells])
    lon = np.array([c.lon for c in cells])
    written = {}
    for kind, hub_list in kinds.items():
        ids, dm = hubs.nearest_hubs(net, lat, lon, hub_list)
        if not dry_run:
            written[kind] = store.write_cell_hubs(conn, [c.geohash for c in cells], kind, ids, dm)
        else:
            written[kind] = int((ids[:, 0] >= 0).sum())
    stats.add("hubs_search", time.time() - t0)
    print(f"[routing] hubs: {written}, {time.time() - t0:.0f}s", file=sys.stderr)
    return {"cells_with_hubs": written, "rail_stations": len(rail)}


def run_tile(conn, tile: tiles.Tile, modes, steps, stats: Stats, dry_run: bool) -> None:
    cells = store.read_cells(conn, tile.box())
    if not cells:
        return
    stats.tiles += 1
    stats.cells += len(cells)
    for mode in modes:
        mode_cells = [c for c in cells if c.mode == mode]
        want_amenity = "amenity" in steps and mode_cells
        want_graph = "graph" in steps
        if not (want_amenity or want_graph):
            continue
        net = build_tile_network(tile, mode, stats)
        if want_amenity:
            t0 = time.time()
            lat = np.array([c.lat for c in mode_cells])
            lon = np.array([c.lon for c in mode_cells])
            node_ids, _, snap_min, on_net = travel.snap(net, lat, lon, mode)
            pad = tiles.pad_box(tile.box(), CAP_MIN[mode] * (80.0 if mode == "walk" else 1100.0))
            places = store.read_places(conn, pad)
            minutes = travel.amenity_minutes(net, node_ids, snap_min, on_net, places, mode)
            stats.add("amenity_search", time.time() - t0)
            if not dry_run:
                store.write_cell_travel(conn, mode_cells, minutes)
        if want_graph:
            t0 = time.time()
            iys, ixs, edges = travel.neighbor_minutes(
                net, tile.iy0, tile.ix0, tile.iy1, tile.ix1, mode
            )
            stats.add("graph_search", time.time() - t0)
            by_key = {(c.iy, c.ix): i for i, c in enumerate(cells)}
            pick = [by_key.get((int(y), int(x))) for y, x in zip(iys, ixs, strict=True)]
            keep = [r for r, p in enumerate(pick) if p is not None]
            if keep and not dry_run:
                store.write_cell_graph(
                    conn, [cells[pick[r]] for r in keep], mode, edges[np.array(keep)]
                )
        del net


def run_transit(conn, stats: Stats, dry_run: bool) -> dict:
    t0 = time.time()
    feeds = transit.fetch_feeds()
    stats.add("transit_fetch", time.time() - t0)
    t0 = time.time()
    tt = transit.build_timetable(feeds)
    stats.add("transit_build", time.time() - t0)
    t0 = time.time()
    n = len(tt.stations)
    matrix = np.full((n, n), -1, dtype=np.int16)
    for o in range(n):
        for d, minutes in enumerate(transit.ride_minutes_from(tt, o)):
            if minutes is not None:
                matrix[o, d] = round(minutes * 10)
    stats.add("transit_scan", time.time() - t0)
    rows = hubs.rail_rows(tt.stations)
    if not dry_run:
        store.write_hubs(conn, rows)
        store.write_rail_matrix(conn, [r[0] for r in rows], matrix)
    reach = float((matrix >= 0).mean())
    return {"stations": n, "connections": len(tt.dep), "reachable_share": round(reach, 3)}


def run_hubs(conn, region, stats: Stats, dry_run: bool) -> dict:
    t0 = time.time()
    data = hubs.fetch_backbone(region)
    stats.add("hubs_fetch", time.time() - t0)
    t0 = time.time()
    net = network.to_pandana(data)
    stats.add("hubs_build", time.time() - t0)
    airports = hubs.airport_rows()
    if not dry_run:
        store.write_hubs(conn, airports)
    kinds = {"airport": [(r[0], r[4], r[5]) for r in airports]}
    rail = store.read_hubs(conn, "rail")
    if rail:
        kinds["rail"] = [(r[0], r[3], r[4]) for r in rail]
    south, west, north, east = region
    cells = store.read_cells(conn, (south, west, north, east))
    lat = np.array([c.lat for c in cells])
    lon = np.array([c.lon for c in cells])
    t0 = time.time()
    written = {}
    for kind, hub_list in kinds.items():
        ids, dm = hubs.nearest_hubs(net, lat, lon, hub_list)
        if not dry_run:
            written[kind] = store.write_cell_hubs(conn, [c.geohash for c in cells], kind, ids, dm)
        else:
            written[kind] = int((ids[:, 0] >= 0).sum())
    stats.add("hubs_search", time.time() - t0)
    stats.nodes += data.n_nodes
    return {"backbone_nodes": data.n_nodes, "cells_with_hubs": written}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--region", choices=sorted(REGIONS))
    where.add_argument("--bbox", help="south,west,north,east")
    where.add_argument("--all", action="store_true", help="every cell in geo_entities")
    ap.add_argument("--steps", default="amenity,graph")
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-tiles", type=int, default=0)
    ap.add_argument(
        "--networks",
        help="directory of saved networks (walk.npz, drive.npz, arterial.npz from "
        "ingestion.routing.pbf): the whole region at once, no Overpass",
    )
    args = ap.parse_args(argv)

    steps = [s for s in args.steps.split(",") if s]
    bad = [s for s in steps if s not in STEPS]
    if bad:
        raise SystemExit(f"unknown steps {bad}; choose from {STEPS}")
    modes = [m for m in args.modes.split(",") if m in MODES]
    stats = Stats()
    started = time.time()
    summary: dict = {}
    with get_connection() as conn:
        if args.all:
            south, west, north, east = store.cell_bounds_of(conn)
            eps = 1e-6  # read_cells is half-open: keep the cells on the north / east edge
            region = (south - eps, west - eps, north + eps, east + eps)
        elif args.bbox:
            region = tuple(float(v) for v in args.bbox.split(","))
        else:
            region = REGIONS[args.region]
        if "transit" in steps:
            summary["transit"] = run_transit(conn, stats, args.dry_run)
        if args.networks:
            if "amenity" in steps or "graph" in steps:
                run_region(conn, args.networks, region, modes, steps, stats, args.dry_run)
            if "hubs" in steps:
                summary["hubs"] = run_hubs_region(conn, args.networks, region, stats, args.dry_run)
        elif "amenity" in steps or "graph" in steps:
            by_mode: dict[str, list[tiles.Tile]] = {
                m: tiles.plan_tiles(region, *TILE_CELLS[m]) for m in modes
            }
            for mode in modes:
                plan = by_mode[mode]
                if args.max_tiles:
                    plan = plan[: args.max_tiles]
                for i, tile in enumerate(plan):
                    t0 = time.time()
                    run_tile(conn, tile, [mode], steps, stats, args.dry_run)
                    print(
                        f"[routing] {mode} tile {i + 1}/{len(plan)} {tile.label()} "
                        f"{time.time() - t0:.1f}s peak {peak_rss_mb():.0f} MB",
                        file=sys.stderr,
                    )
        if "hubs" in steps and not args.networks:
            summary["hubs"] = run_hubs(conn, region, stats, args.dry_run)
        if not args.dry_run and ("amenity" in steps or "graph" in steps):
            store.write_meta(conn, "layout", meta_blob())
    summary.update(
        {
            "region": region,
            "tiles": stats.tiles,
            "cells": stats.cells,
            "nodes_total": stats.nodes,
            "edges_total": stats.edges,
            "seconds": {k: round(v, 1) for k, v in stats.seconds.items()},
            "wall_seconds": round(time.time() - started, 1),
            "peak_rss_mb": round(peak_rss_mb()),
        }
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
