"""Builds the AREAS (faces of the secondary-and-above road network, closed by
the coastline and a frame at the fetch bbox) and either previews them or
replaces the `areas` / `area_cells` tables.

  python -m ingestion.areas.build                      # --dry-run on the cached sample
  python -m ingestion.areas.build --source region --allow-network --write \\
      --build-version areas-v1-2026-10                 # the real run (needs approval)

Dry-run (default) never touches the network or the database and writes
areas.geojson, metrics.json and areas_preview.png to --out-dir. --write
replaces both tables in ONE transaction and is only allowed with
--source region. Network fetches need --allow-network; cached tiles are used
without it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from shapely.geometry import Point, box, mapping

from common.coverage import BOUNDING_BOXES
from ingestion.areas.faces import Face, FaceParams, _to_m, build_faces, number_faces
from ingestion.areas.hard_source import (
    fetch_region,
    parse_hard,
    region_bbox,
    street_points,
)
from ingestion.areas.osm_source import SAMPLE_BBOX, Projector, cache_path, parse_layers

SQ_M_PER_SQ_MI = 2_589_988.11
DEFAULT_BUILD_VERSION = "areas-v1-2026-10"
Numbered = list[tuple[int, Face]]


def projector_for(bbox: tuple[float, float, float, float]) -> Projector:
    s, w, n, e = bbox
    return Projector((s + n) / 2, (w + e) / 2)


def frame_for(bbox: tuple[float, float, float, float], proj: Projector):
    s, w, n, e = bbox
    (x0, y0), (x1, y1) = proj.fwd(w, s), proj.fwd(e, n)
    return box(x0, y0, x1, y1)


def metro_of(face: Face) -> str | None:
    pt = face.geometry.representative_point()
    for name, s, n, w, e in BOUNDING_BOXES:
        if s <= pt.y <= n and w <= pt.x <= e:
            return name
    return None


def build_numbered(
    data: dict,
    bbox: tuple[float, float, float, float],
    geohashes: frozenset[str] | None = None,
    include_rail: bool = False,
) -> tuple[Numbered, Projector]:
    proj = projector_for(bbox)
    roads, coast = parse_hard(data, proj, include_rail)
    faces = build_faces(roads, coast, frame_for(bbox, proj), FaceParams(proj, geohashes=geohashes))
    return number_faces(faces), proj


# ------------------------------------------------------------------ metrics


def compute_metrics(
    numbered: Numbered,
    proj: Projector,
    runtime_s: float,
    street_pts: list[tuple[float, float]] | None = None,
    water=None,
) -> dict:
    from shapely import STRtree
    areas_mi = np.array([f.area_sq_m / SQ_M_PER_SQ_MI for _, f in numbered]) if numbered else None
    m: dict = {"face_count": len(numbered), "runtime_s": round(runtime_s, 2)}
    if areas_mi is not None:
        q = np.quantile(areas_mi, [0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0])
        m["area_sq_mi_quantiles"] = {
            k: round(float(v), 4) for k, v in zip(
                ["min", "p10", "p25", "median", "p75", "p90", "p99", "max"], q, strict=True)
        }
        m["total_area_sq_mi"] = round(float(areas_mi.sum()), 3)
    metric_geoms = [_to_m(f.geometry, proj) for _, f in numbered]
    if street_pts and metric_geoms:
        tree = STRtree(metric_geoms)
        pts = [Point(x, y) for x, y in street_pts]
        hit = tree.query(pts, predicate="intersects")
        covered = len(set(hit[0].tolist()))
        m["street_points"] = len(pts)
        m["street_points_in_face_pct"] = round(100.0 * covered / max(len(pts), 1), 2)
        used = set(hit[1].tolist())
        m["faces_without_street_points"] = len(metric_geoms) - len(used)
    if water is not None:
        m["faces_over_water"] = sum(
            1 for g in metric_geoms if g.area > 0 and g.intersection(water).area / g.area > 0.5
        )
    return m


def to_geojson(numbered: Numbered) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": i,
                "properties": {
                    "id": i,
                    "area_sq_m": round(f.area_sq_m, 1),
                    "bounded_by": list(f.bounded_by),
                    "cells": len(f.cells),
                },
                "geometry": mapping(f.geometry),
            }
            for i, f in numbered
        ],
    }


def render_preview(numbered: Numbered, path: Path, street_pts_ll=None) -> bool:
    """Writes a PNG preview; returns False (and writes nothing) when the optional
    matplotlib (the `geo` extra) is not installed."""
    try:
        import matplotlib
    except ImportError:
        return False

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 10), dpi=110)
    cmap = plt.get_cmap("tab20")
    for i, f in numbered:
        for poly in getattr(f.geometry, "geoms", [f.geometry]):
            x, y = poly.exterior.xy
            ax.fill(x, y, facecolor=cmap(i % 20), alpha=0.55, edgecolor="black", linewidth=0.5)
            for hole in poly.interiors:
                hx, hy = hole.xy
                ax.fill(hx, hy, facecolor="white", edgecolor="black", linewidth=0.5)
    if street_pts_ll:
        ax.scatter([p[0] for p in street_pts_ll], [p[1] for p in street_pts_ll], s=0.6, c="k")
    ax.set_aspect(1 / np.cos(np.radians(40.7)))
    ax.set_title(f"{len(numbered)} areas")
    fig.savefig(path)
    plt.close(fig)
    return True


# ----------------------------------------------------------------------- DB


def read_geohashes(conn) -> frozenset[str]:
    """Read-only: every geohash in geo_entities."""
    with conn.cursor() as cur:
        cur.execute("select geohash from geo_entities")
        return frozenset(row["geohash"] for row in cur)


INSERT_AREA_SQL = (
    "insert into areas (id, build_version, metro_area, min_lat, max_lat, min_lon, max_lon, "
    "area_sq_m, geometry, bounded_by) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
INSERT_CELL_SQL = "insert into area_cells (area_id, geohash, overlap_sq_m) values (%s, %s, %s)"


def write_areas(conn, numbered: Numbered, build_version: str) -> dict:
    """Replaces areas + area_cells in ONE transaction (commit at the end,
    rollback on any error). Refuses to wipe the tables with an empty build."""
    from psycopg.types.json import Jsonb

    if not numbered:
        raise ValueError("refusing to replace areas with an empty build")
    area_rows = [
        (i, build_version, metro_of(f), f.bbox[0], f.bbox[1], f.bbox[2], f.bbox[3],
         f.area_sq_m, Jsonb(mapping(f.geometry)), list(f.bounded_by))
        for i, f in numbered
    ]  # fmt: skip
    cell_rows = [(i, gh, ov) for i, f in numbered for gh, ov in f.cells]
    try:
        with conn.cursor() as cur:
            cur.execute("delete from area_cells")
            cur.execute("delete from areas")
            cur.executemany(INSERT_AREA_SQL, area_rows)
            cur.executemany(INSERT_CELL_SQL, cell_rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"areas": len(area_rows), "area_cells": len(cell_rows)}


# ---------------------------------------------------------------------- CLI


def _load_sample(cache_dir: Path) -> dict:
    path = cache_path(SAMPLE_BBOX, cache_dir)
    if not path.exists():
        raise SystemExit(f"cached sample not found: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build road-bounded AREAS.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: files only, no DB")
    mode.add_argument("--write", action="store_true", help="replace areas + area_cells (1 txn)")
    ap.add_argument("--source", choices=["sample", "region"], default="sample")
    ap.add_argument("--allow-network", action="store_true", help="permit Overpass fetches")
    ap.add_argument("--include-rail", action="store_true", help="rails as walls (default off)")
    ap.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    ap.add_argument("--out-dir", type=Path, default=Path("data/areas"))
    ap.add_argument("--build-version", default=DEFAULT_BUILD_VERSION)
    args = ap.parse_args(argv)

    if args.write and args.source != "region":
        ap.error("--write requires --source region")

    t0 = time.monotonic()
    geohashes = None
    if args.write:
        from common.db import get_connection

        with get_connection() as conn:
            geohashes = read_geohashes(conn)
        print(f"{len(geohashes)} geohashes in geo_entities")

    street_ll = water = None
    if args.source == "sample":
        bbox = SAMPLE_BBOX
        data = _load_sample(args.cache_dir)
        proj = projector_for(bbox)
        frame = frame_for(bbox, proj)
        street_m = [q for q in street_points(data, proj) if frame.contains(Point(*q))]
        water = parse_layers(data, bbox).water
    else:
        bbox = region_bbox()
        data = fetch_region(
            bbox, args.cache_dir, allow_network=args.allow_network, include_rail=args.include_rail
        )
        street_m = None
    numbered, proj = build_numbered(data, bbox, geohashes, args.include_rail)
    metrics = compute_metrics(numbered, proj, time.monotonic() - t0, street_m, water)
    if street_m is not None:
        street_ll = [proj.inv(x, y) for x, y in street_m]

    if args.write:
        from common.db import get_connection

        with get_connection() as conn:
            metrics["written"] = write_areas(conn, numbered, args.build_version)
    else:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "areas.geojson").write_text(json.dumps(to_geojson(numbered)))
        render_preview(numbered, args.out_dir / "areas_preview.png", street_ll)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
