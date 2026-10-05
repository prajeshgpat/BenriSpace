"""High-resolution isochrones straight from a road network (offline / QA path).

reachable nodes -> polygon. Two shapes:
  buffer  union of a small disc around every reachable node (radius = what the leftover minutes
          could still cover, capped at BUFFER_CAP_M). Tight, follows the street grid.
  hull    concave hull of the reachable nodes (shapely >= 2.0 / GEOS >= 3.11).

This needs Pandana and shapely, so it is NOT in the Lambda bundle. The API's isochrones
(api/isochrone.py) come from the precomputed cell graph instead; this module is how that
approximation is checked (`--compare`) and how a finer path would be produced for a specific
place.

    python -m ingestion.routing.isochrone --lat 40.7178 --lon -74.0431 --mode walk --minutes 15
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np

from common.routing import CIRCUITY, WALK_M_PER_MIN
from ingestion.routing import network, tiles

BUFFER_CAP_M = 120.0
DRIVE_M_PER_MIN = 700.0  # ~26 mph, only used to size the candidate-node prefilter
M_PER_DEG_LAT = 111_320.0


def reachable(net, lat: float, lon: float, minutes: float, mode: str):
    """(lon, lat, remaining minutes) of every node reachable from (lat, lon) within `minutes`."""
    import pandas as pd

    m_per_min = WALK_M_PER_MIN if mode == "walk" else DRIVE_M_PER_MIN * 2.2
    radius_m = minutes * m_per_min
    nodes = net.nodes_df
    d_lat = radius_m / M_PER_DEG_LAT
    d_lon = d_lat / max(0.05, math.cos(math.radians(lat)))
    near = nodes[
        (nodes["y"].between(lat - d_lat, lat + d_lat))
        & (nodes["x"].between(lon - d_lon, lon + d_lon))
    ]
    if near.empty:
        return np.empty(0), np.empty(0), np.empty(0)
    origin = int(net.get_node_ids(pd.Series([lon]), pd.Series([lat])).iloc[0])
    times = np.asarray(
        net.shortest_path_lengths([origin] * len(near), list(near.index)), dtype=np.float64
    )
    ok = (times >= 0) & (times <= minutes)
    return near["x"].to_numpy()[ok], near["y"].to_numpy()[ok], minutes - times[ok]


def polygon(xs, ys, remaining, mode: str, shape: str = "buffer", simplify_m: float = 15.0):
    """GeoJSON-like dict (Polygon / MultiPolygon) for the reachable nodes, or None if empty."""
    import shapely
    from shapely.geometry import MultiPoint, Point, mapping

    if len(xs) == 0:
        return None
    mid_lat = float(np.mean(ys))
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(mid_lat))
    if shape == "hull":
        geom = shapely.concave_hull(MultiPoint(list(zip(xs, ys, strict=True))), ratio=0.3)
    else:
        speed = WALK_M_PER_MIN if mode == "walk" else DRIVE_M_PER_MIN
        discs = []
        for x, y, r in zip(xs, ys, remaining, strict=True):
            radius_m = min(BUFFER_CAP_M, max(15.0, r * speed / CIRCUITY))
            # ellipse in degrees so the disc is round on the ground
            disc = Point(x, y).buffer(1.0, quad_segs=2)
            discs.append(
                shapely.affinity.scale(disc, radius_m / m_per_deg_lon, radius_m / M_PER_DEG_LAT)
            )
        geom = shapely.union_all(discs)
    geom = geom.simplify(simplify_m / M_PER_DEG_LAT)
    return mapping(geom)


def area_sq_mi(geojson: dict, lat: float) -> float:
    from shapely.geometry import shape

    g = shape(geojson)
    m2 = g.area * M_PER_DEG_LAT * M_PER_DEG_LAT * math.cos(math.radians(lat))
    return m2 / (1609.344**2)


def isochrone_from_osm(lat: float, lon: float, minutes: float, mode: str, shape: str = "buffer"):
    """Fetch the network around the point and return (geojson, n_nodes). One-off, slow."""
    speed = WALK_M_PER_MIN if mode == "walk" else DRIVE_M_PER_MIN * 2.2
    box = tiles.pad_box((lat, lon, lat, lon), minutes * speed + 500)
    net = network.to_pandana(network.fetch_network(box, mode))
    xs, ys, rem = reachable(net, lat, lon, minutes, mode)
    return polygon(xs, ys, rem, mode, shape), len(xs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--mode", choices=("walk", "drive"), default="walk")
    ap.add_argument("--minutes", type=float, default=15.0)
    ap.add_argument("--shape", choices=("buffer", "hull"), default="buffer")
    args = ap.parse_args()
    geo, n = isochrone_from_osm(args.lat, args.lon, args.minutes, args.mode, args.shape)
    if geo is None:
        raise SystemExit("nothing reachable")
    print(json.dumps({"type": "Feature", "properties": {"nodes": n}, "geometry": geo}))


if __name__ == "__main__":
    main()
