"""Enforces the size limits (limits.py) on road-bounded faces.

Works on shapely polygons in the build's metric frame (a Projector). Sizes are
always measured the way the final Face is: reproject to lon/lat, then use the
polygon's own local equirectangular frame (so a Long Island face is not
measured with Manhattan's metres).

  1. split: a polygon over MAX_AREA_SQ_MI or MAX_EXTENT_MI is cut by a grid of
     about TARGET_TILE_MI squares aligned to its bounding box (recursively,
     halving the longer side if a cut is still too big). Pieces keep the
     original road edges where they exist; the cuts are straight tile edges.
  2. merge: polygons under MIN_SLIVER_SQ_MI merge into the neighbour sharing
     the longest boundary, only when the result still satisfies the caps.
"""

from __future__ import annotations

import math

import shapely
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from ingestion.areas.faces import _to_ll, _to_m, local_projector
from ingestion.areas.limits import (
    MAX_AREA_M2,
    MAX_EXTENT_M,
    MIN_SLIVER_M2,
    TARGET_TILE_M,
)
from ingestion.areas.osm_source import Projector

_SAFETY = 0.998  # headroom for the later 5-decimal snapping of coordinates
_SNAP_M = 0.001  # mm grid for cut edges so neighbouring pieces share vertices
_MIN_SHARED_M = 1.0
_MAX_DEPTH = 8


def measure(geom: BaseGeometry, proj: Projector) -> tuple[float, float]:
    """(area_m2, extent_m) in the geometry's own local frame; extent is the
    longest side of its bounding box."""
    ll = _to_ll(geom, proj)
    minx, miny, maxx, maxy = ll.bounds
    local = _to_m(ll, local_projector(miny, maxy, minx, maxx))
    x0, y0, x1, y1 = local.bounds
    return local.area, max(x1 - x0, y1 - y0)


def within_caps(geom: BaseGeometry, proj: Projector) -> bool:
    area, extent = measure(geom, proj)
    return area <= MAX_AREA_M2 * _SAFETY and extent <= MAX_EXTENT_M * _SAFETY


def _polys(g: BaseGeometry) -> list[Polygon]:
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for part in getattr(g, "geoms", []) for p in _polys(part)]


def _cut(poly: Polygon, nx: int, ny: int) -> list[Polygon]:
    x0, y0, x1, y1 = poly.bounds
    dx, dy = (x1 - x0) / nx, (y1 - y0) / ny
    shapely.prepare(poly)
    out: list[Polygon] = []
    for i in range(nx):
        for j in range(ny):
            tile = box(
                x0 if i == 0 else x0 + i * dx,
                y0 if j == 0 else y0 + j * dy,
                x1 if i == nx - 1 else x0 + (i + 1) * dx,
                y1 if j == ny - 1 else y0 + (j + 1) * dy,
            )
            if not poly.intersects(tile):
                continue
            part = shapely.set_precision(poly.intersection(tile), _SNAP_M)
            out.extend(p for p in _polys(part) if p.area > 0)
    return out


def split_oversized(poly: Polygon, proj: Projector, _depth: int = 0) -> list[Polygon]:
    """Pieces of `poly`, each within the caps (best effort at _MAX_DEPTH)."""
    if within_caps(poly, proj) or _depth >= _MAX_DEPTH:
        return [poly]
    x0, y0, x1, y1 = poly.bounds
    nx = max(1, round((x1 - x0) / TARGET_TILE_M))
    ny = max(1, round((y1 - y0) / TARGET_TILE_M))
    if nx == 1 and ny == 1:  # compact but over the area cap: halve the longer side
        nx, ny = (2, 1) if (x1 - x0) >= (y1 - y0) else (1, 2)
    pieces = _cut(poly, nx, ny)
    if len(pieces) == 1 and pieces[0].equals(poly):  # no progress
        return [poly]
    out: list[Polygon] = []
    for p in pieces:
        out.extend(split_oversized(p, proj, _depth + 1))
    return out


def _shared_length(a: Polygon, b: Polygon) -> float:
    return b.boundary.intersection(a.buffer(0.05)).length


def merge_slivers(polys: list[Polygon], proj: Projector, max_rounds: int = 6) -> list[Polygon]:
    """Merges each sliver into the neighbour sharing the longest boundary when
    the union is one polygon within the caps. Slivers with no taker stay."""
    cur = list(polys)
    for _ in range(max_rounds):
        areas = [measure(p, proj)[0] for p in cur]
        slivers = sorted(
            (i for i, a in enumerate(areas) if a < MIN_SLIVER_M2), key=lambda i: areas[i]
        )
        if not slivers:
            break
        tree = STRtree(cur)
        gone: set[int] = set()
        replaced: dict[int, Polygon] = {}
        touched: set[int] = set()
        for i in slivers:
            if i in touched:
                continue
            cand = []
            for k in tree.query(cur[i].buffer(0.05)):
                k = int(k)
                if k == i or k in touched:
                    continue
                ln = _shared_length(cur[i], cur[k])
                if ln >= _MIN_SHARED_M:
                    cand.append((-ln, k))
            for _, k in sorted(cand):
                merged = shapely.unary_union([cur[i], cur[k]])
                if merged.geom_type != "Polygon":
                    merged = merged.buffer(0.01).buffer(-0.01)
                if merged.geom_type != "Polygon" or not within_caps(merged, proj):
                    continue
                replaced[k] = merged
                gone.add(i)
                touched.update((i, k))
                break
        if not gone:
            break
        cur = [replaced.get(j, p) for j, p in enumerate(cur) if j not in gone]
    return cur


def enforce_limits(polys: list[Polygon], proj: Projector) -> list[Polygon]:
    """split_oversized on every polygon, then merge_slivers over all pieces."""
    pieces: list[Polygon] = []
    for p in polys:
        pieces.extend(split_oversized(p, proj))
    return merge_slivers(pieces, proj)


def compactness(area: float, perimeter: float) -> float:
    """Polsby-Popper: 4*pi*A/P^2 (1 = circle)."""
    return 4.0 * math.pi * area / (perimeter**2) if perimeter > 0 else 0.0
