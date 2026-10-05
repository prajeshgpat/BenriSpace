"""Wave 4 routing prototype (exploratory; read-only DB, no writes).

Walk minutes from every node of a small OSM walk network to the nearest 3 grocery places in
ONE multi-source search (Pandana k-nearest POIs), mapped to the geohash6 cells in the bbox.
Compares with the straight-line estimate used today (distance x 1.3 / 3 mph) and extrapolates
runtime / memory to the full metro.

    pip install -e ".[routing]" "psycopg[binary]" python-dotenv
    python scripts/routing_prototype.py [--lat 40.672 --lon -73.978 --km 1.5 --category grocery]

Needs DATABASE_URL (read-only SELECT on places) and network access to Overpass.
"""

from __future__ import annotations

import argparse
import math
import os
import resource
import sys
import time

WALK_M_PER_MIN = 80.467  # 3 mph
CIRCUITY = 1.3
MAX_MIN = 30.0
PAD_KM = 1.0  # fetch extra network so routes near the bbox edge are not truncated


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + (
        math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def bbox_around(lat: float, lon: float, km: float) -> tuple[float, float, float, float]:
    """(north, south, east, west)."""
    dlat = km / 111.32
    dlon = km / (111.32 * math.cos(math.radians(lat)))
    return lat + dlat, lat - dlat, lon + dlon, lon - dlon


def straight_line_minutes(lat: float, lon: float, places: list[tuple[float, float]], k: int):
    d = sorted(haversine_m(lat, lon, p[0], p[1]) for p in places)[:k]
    return [x * CIRCUITY / WALK_M_PER_MIN for x in d]


def main() -> None:
    import numpy as np
    import osmnx as ox
    import pandana as pdna
    import pandas as pd
    import psycopg
    import pygeohash as pgh
    from dotenv import load_dotenv

    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=40.672)
    ap.add_argument("--lon", type=float, default=-73.978)
    ap.add_argument("--km", type=float, default=1.5)
    ap.add_argument("--category", default="grocery")
    args = ap.parse_args()
    load_dotenv()

    n, s, e, w = bbox_around(args.lat, args.lon, args.km)
    pn, ps, pe, pw = bbox_around(args.lat, args.lon, args.km + PAD_KM)

    t0 = time.time()
    graph = ox.graph_from_bbox((pw, ps, pe, pn), network_type="walk", simplify=True)
    nodes, edges = ox.graph_to_gdfs(graph)
    t_download = time.time() - t0

    t0 = time.time()
    edges = edges.reset_index()
    edges["minutes"] = edges["length"] / WALK_M_PER_MIN
    net = pdna.Network(
        nodes["x"], nodes["y"], edges["u"], edges["v"], edges[["minutes"]], twoway=False
    )
    t_build = time.time() - t0

    with psycopg.connect(
        os.environ["DATABASE_URL"], options="-c default_transaction_read_only=on"
    ) as conn:
        rows = conn.execute(
            "select latitude, longitude from places where category = %s"
            " and latitude between %s and %s and longitude between %s and %s",
            (args.category, ps, pn, pw, pe),
        ).fetchall()
    places = [(float(a), float(b)) for a, b in rows]
    print(
        f"network: {len(nodes)} nodes, {len(edges)} directed edges; {len(places)} {args.category}"
    )

    t0 = time.time()
    net.set_pois(
        args.category,
        MAX_MIN,
        3,
        pd.Series([p[1] for p in places]),
        pd.Series([p[0] for p in places]),
    )
    result = net.nearest_pois(MAX_MIN, args.category, num_pois=3)  # minutes per node, cols 1..3
    t_search = time.time() - t0

    # Cells whose centre is inside the (unpadded) bbox
    t0 = time.time()
    cells = []
    lat = s
    while lat <= n:
        lon = w
        while lon <= e:
            g = pgh.encode(lat, lon, precision=6)
            clat, clon = pgh.decode(g)
            if s <= float(clat) <= n and w <= float(clon) <= e:
                cells.append((g, float(clat), float(clon)))
            lon += 0.0055
        lat += 0.0027
    cells = list({c[0]: c for c in cells}.values())
    node_ids = net.get_node_ids(pd.Series([c[2] for c in cells]), pd.Series([c[1] for c in cells]))
    t_map = time.time() - t0

    print(f"\ncells in bbox: {len(cells)}")
    print(
        f"runtime: osm download+graph {t_download:.1f}s | build network {t_build:.2f}s | "
        f"multi-source k=3 search {t_search:.2f}s | map to cells {t_map:.2f}s"
    )
    print(f"{'cell':8s} {'walk1':>6s} {'walk3':>6s} {'line1':>6s} {'line3':>6s}")
    ratios = []
    for (g, clat, clon), nid in list(zip(cells, node_ids, strict=True)):
        m = result.loc[nid]
        line = straight_line_minutes(clat, clon, places, 3)
        if m[1] < MAX_MIN and line:
            ratios.append(m[1] / max(line[0], 0.1))
        if len(ratios) <= 12:
            print(f"{g:8s} {m[1]:6.1f} {m[3]:6.1f} {line[0]:6.1f} {line[2]:6.1f}")
    print(f"median network/straight-line ratio (nearest): {float(np.median(ratios)):.2f}")

    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        1024 * 1024 if sys.platform == "darwin" else 1024
    )
    area_km2 = (2 * args.km) ** 2
    print(f"peak RSS {peak_mb:.0f} MB; node density {len(nodes) / area_km2:.0f} nodes/km2")


if __name__ == "__main__":
    main()
