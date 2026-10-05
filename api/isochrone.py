"""Isochrones from the precomputed cell graph (pure Python: no numpy, shapely or PostGIS).

Why not a routing engine: pandana + osmnx + numpy do not fit the Lambda bundle (50 MB zip) and an
OSM graph cannot be loaded inside the 29 s cap. So the road network is folded into a graph of
geohash6 cells ahead of time (ingestion/routing: `cell_graph`, travel minutes from each cell to
its 8 neighbours measured on the real network). A request is then:

  1. load the cell_graph rows around the origin (one indexed query),
  2. Dijkstra over them up to the time budget (thousands of nodes, well under a second),
  3. turn the reached cells into a polygon (boundary tracing + corner smoothing).

Resolution is one cell (0.58 x 0.38 mi): good for commute-scale questions (15+ minutes), coarse
for a 5 minute walk. ingestion/routing/isochrone.py makes the street-level version offline.

Set operations for triangulation (intersect / union of several anchors) are done on the cell sets,
which is exact on this grid, and the combined polygon is traced from the resulting set.
"""

from __future__ import annotations

import heapq
import math

from common.cellgrid import LAT_STEP, LON_STEP, NEIGHBORS, CellKey, cell_index
from common.routing import UNREACHABLE

WALK_M_PER_MIN = 80.467
SQ_MI_PER_CELL_AT_LAT_40_7 = 0.58 * 0.38

Graph = dict[CellKey, list[int]]  # cell -> 8 neighbour deci-minutes (-1 = none)


def dijkstra(graph: Graph, start: CellKey, max_minutes: float) -> dict[CellKey, float]:
    """Minutes to every cell reachable from `start` within max_minutes."""
    limit = max_minutes * 10.0
    best: dict[CellKey, float] = {start: 0.0}
    heap = [(0.0, start)]
    while heap:
        dist, key = heapq.heappop(heap)
        if dist > best.get(key, math.inf):
            continue
        edges = graph.get(key)
        if edges is None:
            continue
        iy, ix = key
        for (dy, dx), dm in zip(NEIGHBORS, edges, strict=True):
            if dm == UNREACHABLE:
                continue
            nd = dist + dm
            if nd > limit:
                continue
            nkey = (iy + dy, ix + dx)
            if nkey in graph and nd < best.get(nkey, math.inf):
                best[nkey] = nd
                heapq.heappush(heap, (nd, nkey))
    return {k: v / 10.0 for k, v in best.items()}


def nearest_graph_cell(graph: Graph, lat: float, lon: float, max_ring: int = 3) -> CellKey | None:
    """The cell holding (lat, lon), or the closest graph cell within max_ring cells."""
    iy, ix = cell_index(lat, lon)
    if (iy, ix) in graph:
        return (iy, ix)
    for ring in range(1, max_ring + 1):
        found = [
            (iy + dy, ix + dx)
            for dy in range(-ring, ring + 1)
            for dx in range(-ring, ring + 1)
            if max(abs(dy), abs(dx)) == ring and (iy + dy, ix + dx) in graph
        ]
        if found:
            return min(found, key=lambda k: (k[0] - iy) ** 2 + (k[1] - ix) ** 2)
    return None


def disc_cells(lat: float, lon: float, radius_m: float) -> set[CellKey]:
    """Cells whose centre is within radius_m of (lat, lon) (straight line)."""
    iy, ix = cell_index(lat, lon)
    m_lat = LAT_STEP * 111_320.0
    m_lon = LON_STEP * 111_320.0 * math.cos(math.radians(lat))
    ry, rx = int(radius_m // m_lat) + 1, int(radius_m // m_lon) + 1
    out = set()
    for dy in range(-ry, ry + 1):
        for dx in range(-rx, rx + 1):
            if math.hypot(dy * m_lat, dx * m_lon) <= radius_m:
                out.add((iy + dy, ix + dx))
    return out


def area_sq_mi(n_cells: int, lat: float) -> float:
    m2 = n_cells * LAT_STEP * 111_320.0 * LON_STEP * 111_320.0 * math.cos(math.radians(lat))
    return m2 / (1609.344**2)


# ------------------------------------------------------------------------------ polygons


def _boundary_rings(cells: set[CellKey]) -> list[list[tuple[int, int]]]:
    """Closed rings of grid corners (cy, cx) around the cell set; interior on the left, so outer
    rings run counter-clockwise and holes clockwise."""
    nxt: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for iy, ix in cells:
        if (iy - 1, ix) not in cells:
            nxt.setdefault((iy, ix), []).append((iy, ix + 1))
        if (iy, ix + 1) not in cells:
            nxt.setdefault((iy, ix + 1), []).append((iy + 1, ix + 1))
        if (iy + 1, ix) not in cells:
            nxt.setdefault((iy + 1, ix + 1), []).append((iy + 1, ix))
        if (iy, ix - 1) not in cells:
            nxt.setdefault((iy + 1, ix), []).append((iy, ix))
    rings = []
    while nxt:
        start = next(iter(nxt))
        ring = [start]
        cur = start
        prev_dir = None
        while True:
            options = nxt[cur]
            if len(options) > 1 and prev_dir is not None:
                # pinch point: take the leftmost turn so rings stay separate
                def turn(p, prev_dir=prev_dir, cur=cur):
                    d = (p[0] - cur[0], p[1] - cur[1])
                    return prev_dir[1] * d[0] - prev_dir[0] * d[1]

                options.sort(key=turn, reverse=True)
            to = options.pop(0)
            if not options:
                del nxt[cur]
            prev_dir = (to[0] - cur[0], to[1] - cur[1])
            cur = to
            if cur == start:
                break
            ring.append(cur)
        rings.append(ring)
    return rings


def _drop_collinear(ring: list[tuple[int, int]]) -> list[tuple[int, int]]:
    n = len(ring)
    out = []
    for i in range(n):
        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) != 0:
            out.append(b)
    return out


def _chaikin(points: list[tuple[float, float]], rounds: int) -> list[tuple[float, float]]:
    for _ in range(rounds):
        out = []
        for i, p in enumerate(points):
            q = points[(i + 1) % len(points)]
            out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        points = out
    return points


def _signed_area(ring) -> float:
    return 0.5 * sum(
        ring[i][1] * ring[(i + 1) % len(ring)][0] - ring[(i + 1) % len(ring)][1] * ring[i][0]
        for i in range(len(ring))
    )


def _inside(point, ring) -> bool:
    y, x = point
    hit = False
    n = len(ring)
    for i in range(n):
        y1, x1 = ring[i]
        y2, x2 = ring[(i + 1) % n]
        if (x1 > x) != (x2 > x) and y < (y2 - y1) * (x - x1) / (x2 - x1) + y1:
            hit = not hit
    return hit


def cells_to_geometry(cells: set[CellKey], smooth: int = 2) -> dict | None:
    """GeoJSON MultiPolygon (lon/lat) tracing the union of the cells; None when empty."""
    if not cells:
        return None
    outers, holes = [], []
    for ring in _boundary_rings(cells):
        ring = _drop_collinear(ring)
        if len(ring) < 3:
            continue
        pts = _chaikin([(float(y), float(x)) for y, x in ring], smooth) if smooth else ring
        (outers if _signed_area(pts) > 0 else holes).append(pts)
    polygons = [[o] for o in outers]
    for hole in holes:
        for poly in polygons:
            if _inside(hole[0], poly[0]):
                poly.append(hole)
                break

    def lonlat(ring):
        coords = [[round(x * LON_STEP - 180.0, 5), round(y * LAT_STEP - 90.0, 5)] for y, x in ring]
        return [*coords, coords[0]]

    # GeoJSON wants exterior counter-clockwise (lon/lat) and holes clockwise: same as traced.
    return {
        "type": "MultiPolygon",
        "coordinates": [[lonlat(r) for r in poly] for poly in polygons],
    }


def combine(sets: list[set[CellKey]], mode: str) -> set[CellKey]:
    """Intersect (default) or union cell sets."""
    if not sets:
        return set()
    out = set(sets[0])
    for s in sets[1:]:
        out = out | s if mode == "union" else out & s
    return out
