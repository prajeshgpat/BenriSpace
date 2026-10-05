"""Road-hierarchy subdivision of the hard-road faces (replaces the straight tile cuts).

A face of the secondary-and-above arrangement that is over its density cap
(limits.DENSITY_CAPS) is polygonized with tertiary roads; any piece still over its cap
is polygonized with all lower roads (unclassified/residential/living_street); the
resulting small pieces are merged greedily, only along shared road edges and never
across the face's hard boundary, back up toward the cap. A piece with no internal roads
at all stays whole when <= HIER_MAX_AREA_SQ_MI, else the old tile cut is the fallback.

Pure geometry lives here (testable with synthetic grids); `Hierarchy.run` wires in the
density field and the cached Overpass lower-road tiles.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from ingestion.areas import limits
from ingestion.areas.blocks import RoadEdge
from ingestion.areas.osm_source import Projector

GAP_BOUNDARY_M = 8.0  # dangling road ends this close to the face boundary get connected
GAP_ROAD_M = 3.0
_SAFETY = 0.995
SQ_M = limits.SQ_M_PER_SQ_MI


def _lines(g: BaseGeometry) -> list[LineString]:
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    return [x for p in getattr(g, "geoms", []) for x in _lines(p)]


def _polys(g: BaseGeometry) -> list[Polygon]:
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for part in getattr(g, "geoms", []) for p in _polys(part)]


@dataclass(frozen=True)
class Lower:
    geom: LineString
    name: str | None
    tertiary: bool


def polygonize_within(poly: Polygon, lines: list[LineString]) -> list[Polygon]:
    """Pieces of `poly` cut by `lines` (clipped to poly; dangling road ends close to the
    boundary or to another road are connected). Returns [poly] when nothing cuts it."""
    if not lines:
        return [poly]
    inside = shapely.intersection(np.array(lines, dtype=object), poly)
    clipped = [ln for g in inside for ln in _lines(g) if ln.length > 0.5]
    if not clipped:
        return [poly]
    boundary = poly.boundary
    # connect dangling ends (endpoints used once) to the boundary / a nearby road
    ends: dict[tuple[int, int], list[tuple[int, Point]]] = defaultdict(list)
    for i, ln in enumerate(clipped):
        for c in (ln.coords[0], ln.coords[-1]):
            ends[(round(c[0] * 20), round(c[1] * 20))].append((i, Point(c)))
    tree = STRtree(clipped)
    extra: list[LineString] = []
    for occ in ends.values():
        if len(occ) != 1:
            continue
        i, p = occ[0]
        if boundary.distance(p) < 0.05:
            continue
        best, best_d = None, 0.0
        for k in tree.query(p.buffer(GAP_ROAD_M)):
            k = int(k)
            if k == i:
                continue
            d = clipped[k].distance(p)
            if d < 0.05:
                best = None
                best_d = -1.0
                break
            if best is None or d < best_d:
                best, best_d = clipped[k], d
        if best_d < 0:
            continue
        db = boundary.distance(p)
        target = None
        if best is not None and best_d <= GAP_ROAD_M and best_d <= db:
            target = best
        elif db <= GAP_BOUNDARY_M:
            target = boundary
        if target is not None:
            q = shapely.shortest_line(p, target)
            if q is not None and q.length > 0:
                extra.append(q)
    noded = unary_union([boundary, *clipped, *extra])
    out = [p for p in polygonize(noded) if poly.contains(p.representative_point())]
    return out or [poly]


# --------------------------------------------------------------------- merging


@dataclass
class Leaf:
    poly: Polygon
    area: float  # true m^2
    pop: float  # density * area
    parent: int = 0
    tile_cut: bool = False


def merge_leaves(
    leaves: list[Leaf],
    cap_of: Callable[[float], float],
    extent_cap_of: Callable[[float], float],
    min_shared_m: float = limits.MERGE_MIN_SHARED_M,
) -> list[list[int]]:
    """Greedy merge of adjacent leaves (groups of leaf indexes), smallest first, choosing
    the neighbour with the best (shared boundary, same-parent bonus) / sqrt(merged area),
    while merged area <= cap(merged density) and merged extent <= extent cap. cap_of maps
    a density to a cap in sq mi; extent_cap_of maps a cap in sq mi to metres."""
    n = len(leaves)
    if n < 2:
        return [[i] for i in range(n)]
    polys = np.array([lf.poly for lf in leaves], dtype=object)
    tree = STRtree(polys)
    a, b = tree.query(polys, predicate="intersects")
    m = a < b
    a, b = a[m], b[m]
    shared = shapely.length(
        shapely.intersection(shapely.boundary(polys[a]), shapely.boundary(polys[b]))
    )
    adj: dict[int, dict[int, float]] = {i: {} for i in range(n)}
    for i, j, s in zip(a.tolist(), b.tolist(), shared.tolist(), strict=True):
        if s >= min_shared_m:
            w = s * (2.0 if leaves[i].parent == leaves[j].parent else 1.0)
            adj[i][j] = adj[j][i] = w
    members = {i: [i] for i in range(n)}
    area = {i: leaves[i].area for i in range(n)}
    pop = {i: leaves[i].pop for i in range(n)}
    bnd = {i: leaves[i].poly.bounds for i in range(n)}

    def ok(g: int, h: int) -> bool:
        ar = area[g] + area[h]
        cap = cap_of(((pop[g] + pop[h]) / ar) if ar > 0 else 0.0) * SQ_M * _SAFETY
        if ar > cap:
            return False
        bg, bh = bnd[g], bnd[h]
        ext = max(max(bg[2], bh[2]) - min(bg[0], bh[0]), max(bg[3], bh[3]) - min(bg[1], bh[1]))
        return ext <= extent_cap_of(cap / SQ_M / _SAFETY) * _SAFETY

    changed = True
    while changed:
        changed = False
        for g in sorted(members, key=lambda k: (area[k], k)):
            if g not in members:
                continue
            best, best_s = None, -1.0
            for h, w in adj[g].items():
                if not ok(g, h):
                    continue
                s = w / math.sqrt(area[g] + area[h])
                if s > best_s or (s == best_s and best is not None and h < best):
                    best, best_s = h, s
            if best is None:
                continue
            h = best
            for k, w in adj[g].items():
                if k == h:
                    continue
                adj[h][k] = adj[h].get(k, 0.0) + w
                adj[k][h] = adj[h][k]
                del adj[k][g]
            del adj[h][g]
            del adj[g]
            members[h].extend(members.pop(g))
            area[h] += area.pop(g)
            pop[h] += pop.pop(g)
            bg, bh = bnd.pop(g), bnd[h]
            bnd[h] = (min(bg[0], bh[0]), min(bg[1], bh[1]), max(bg[2], bh[2]), max(bg[3], bh[3]))
            changed = True
    return [sorted(v) for v in members.values()]


def union_group(leaves: list[Leaf], idx: list[int]) -> BaseGeometry:
    if len(idx) == 1:
        return leaves[idx[0]].poly
    g = unary_union([leaves[i].poly for i in idx])
    if g.geom_type != "Polygon":
        g = g.buffer(0.01).buffer(-0.01)
    return g


# ------------------------------------------------------------------ subdivision


def tile_cut(poly: Polygon, max_sq_m: float, side_m: float) -> list[Polygon]:
    """Fallback: straight tile cuts until every piece is <= max_sq_m (approx, true area
    taken as projector area)."""
    from ingestion.areas.limits_apply import _cut

    if poly.area <= max_sq_m:
        return [poly]
    x0, y0, x1, y1 = poly.bounds
    nx, ny = max(1, round((x1 - x0) / side_m)), max(1, round((y1 - y0) / side_m))
    if nx == 1 and ny == 1:
        nx, ny = (2, 1) if (x1 - x0) >= (y1 - y0) else (1, 2)
    pieces = _cut(poly, nx, ny)
    if len(pieces) <= 1:
        return [poly]
    out: list[Polygon] = []
    for p in pieces:
        out.extend(tile_cut(p, max_sq_m, side_m))
    return out


@dataclass
class Subdivider:
    """Geometry-only subdivision of one face. `density_of(polys) -> array` supplies the
    people / sq mi of each polygon; `area_scale(poly)` converts projector m^2 to true m^2."""

    density_of: Callable[[list[Polygon]], np.ndarray]
    tertiary: STRtree | None
    tertiary_lines: list[LineString]
    lower: STRtree | None
    lower_lines: list[LineString]
    area_scale: Callable[[Polygon], float] = lambda p: 1.0
    stats: dict = field(default_factory=lambda: defaultdict(int))
    tile_cut_pts: list[Point] = field(default_factory=list)

    def _info(self, polys: list[Polygon]):
        dens = self.density_of(polys)
        areas = np.array([p.area * self.area_scale(p) for p in polys])
        caps = np.array([limits.cap_for_density(d) for d in dens])
        return areas, dens, caps

    def _over(self, p: Polygon, area: float, cap: float) -> bool:
        x0, y0, x1, y1 = p.bounds
        return (
            area > cap * SQ_M * _SAFETY
            or max(x1 - x0, y1 - y0) > limits.extent_cap_mi(cap) * limits.M_PER_MI * _SAFETY
        )

    def _lines_in(self, tree, lines, poly) -> list[LineString]:
        if tree is None:
            return []
        return [lines[int(i)] for i in tree.query(poly, predicate="intersects")]

    def subdivide(self, face: Polygon) -> list[Leaf]:
        areas, dens, caps = self._info([face])
        if not self._over(face, areas[0], caps[0]):
            return [Leaf(face, areas[0], dens[0] * areas[0])]
        self.stats["over_cap_faces"] += 1
        level1 = polygonize_within(face, self._lines_in(self.tertiary, self.tertiary_lines, face))
        a1, d1, c1 = self._info(level1)
        leaves: list[Leaf] = []
        for pid, (p, a, d, c) in enumerate(zip(level1, a1, d1, c1, strict=True), start=1):
            if not self._over(p, a, c):
                leaves.append(Leaf(p, a, d * a, pid))
                continue
            sub = polygonize_within(p, self._lines_in(self.lower, self.lower_lines, p))
            if len(sub) == 1:  # no internal roads
                leaves.extend(self._no_roads(p, a, d, pid))
                continue
            a2, d2, _ = self._info(sub)
            leaves.extend(Leaf(q, qa, qd * qa, pid) for q, qa, qd in zip(sub, a2, d2, strict=True))
        return leaves

    def _no_roads(self, p: Polygon, area: float, dens: float, pid: int) -> list[Leaf]:
        if area <= limits.HIER_MAX_AREA_SQ_MI * SQ_M * _SAFETY:
            self.stats["kept_whole_no_roads"] += 1
            return [Leaf(p, area, dens * area, pid)]
        self.stats["tile_cut_fallback"] += 1
        sc = self.area_scale(p)
        parts = tile_cut(
            p,
            limits.HIER_MAX_AREA_SQ_MI * SQ_M * _SAFETY / sc,
            limits.TARGET_TILE_M / math.sqrt(sc),
        )
        out = []
        for q in parts:
            qa = q.area * self.area_scale(q)
            out.append(Leaf(q, qa, dens * qa, pid, tile_cut=True))
            self.tile_cut_pts.append(q.representative_point())
        return out

    def process(self, face: Polygon) -> list[BaseGeometry]:
        leaves = self.subdivide(face)
        if len(leaves) == 1:
            return [leaves[0].poly]
        groups = merge_leaves(
            leaves,
            limits.cap_for_density,
            lambda cap: limits.extent_cap_mi(cap) * limits.M_PER_MI,
        )
        return [union_group(leaves, g) for g in groups]


def build_subdivider(
    density_of,
    lower: list[Lower],
    area_scale=lambda p: 1.0,
) -> Subdivider:
    tert = [lw.geom for lw in lower if lw.tertiary]
    allr = [lw.geom for lw in lower]
    return Subdivider(
        density_of,
        STRtree(tert) if tert else None,
        tert,
        STRtree(allr) if allr else None,
        allr,
        area_scale,
    )


# --------------------------------------------------------------- full pipeline


def parse_lower_ways(ways, proj: Projector, region: STRtree | None = None) -> list[Lower]:
    """Lower roads in projector metres; when `region` (STRtree of boxes) is given, only
    ways whose lon/lat bounds meet it are kept (memory)."""
    from ingestion.areas.local_source import TERTIARY

    out: list[Lower] = []
    for el in ways:
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        pts = [proj.fwd(p["lon"], p["lat"]) for p in geom if p]
        if len(pts) < 2:
            continue
        if region is not None:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if len(region.query(box(min(xs), min(ys), max(xs), max(ys)))) == 0:
                continue
        tags = el.get("tags") or {}
        out.append(Lower(LineString(pts), tags.get("name"), tags.get("highway") in TERTIARY))
    return out


class Hierarchy:
    """Plugs into faces.build_faces as FaceParams.subdivider."""

    def __init__(self, proj: Projector, field, cache_dir: Path, allow_network: bool = False):
        self.proj, self.field = proj, field
        self.cache_dir, self.allow_network = Path(cache_dir), allow_network
        self.stats: dict = {}
        self.named: list[RoadEdge] = []
        self.tile_cut_pts: list[Point] = []
        self._cos0 = math.cos(math.radians(proj.lat0))

    def area_scale(self, p: BaseGeometry) -> float:
        lat = self.proj.lat0 + p.centroid.y / self.proj.ky
        return math.cos(math.radians(lat)) / self._cos0

    def run(self, faces: list[Polygon]) -> list[BaseGeometry]:
        from ingestion.areas import limits_apply
        from ingestion.areas.local_source import ensure_region, iter_ways

        dens = self.field.of_many(faces)
        over = [
            f
            for f, d in zip(faces, dens, strict=True)
            if f.area * self.area_scale(f) > limits.cap_for_density(d) * SQ_M * _SAFETY
            or max(f.bounds[2] - f.bounds[0], f.bounds[3] - f.bounds[1])
            > limits.extent_cap_mi(limits.cap_for_density(d)) * limits.M_PER_MI * _SAFETY
        ]
        self.stats["hard_faces"] = len(faces)
        self.stats["hard_faces_over_cap"] = len(over)
        if not over:
            return list(faces)
        region = STRtree([f.buffer(15.0) for f in over])
        lo = self.proj  # tiles needed: those meeting an over-cap face
        paths = ensure_region(
            self.cache_dir,
            allow_network=self.allow_network,
            only=lambda t: self._tile_needed(t, region),
        )
        lower = parse_lower_ways(iter_ways(paths), lo, region)
        self.stats["lower_ways_kept"] = len(lower)
        sub = build_subdivider(self.field.of_many, lower, self.area_scale)
        out: list[BaseGeometry] = []
        over_ids = {id(f) for f in over}
        for f in faces:
            if id(f) in over_ids:
                out.extend(sub.process(f))
            else:
                out.append(f)
        self.stats.update(sub.stats)
        self.tile_cut_pts = sub.tile_cut_pts
        self.named = [RoadEdge(lw.geom, 1.0, "lower", lw.name, False) for lw in lower if lw.name]

        def ok(g: BaseGeometry) -> bool:
            d = float(self.field.of_many([g])[0])
            cap = limits.cap_for_density(d)
            x0, y0, x1, y1 = g.bounds
            return (
                g.area * self.area_scale(g) <= cap * SQ_M * _SAFETY
                and max(x1 - x0, y1 - y0) <= limits.extent_cap_mi(cap) * limits.M_PER_MI * _SAFETY
            )

        before = len(out)
        out = limits_apply.merge_slivers(out, self.proj, ok=ok)
        self.stats["sliver_merges"] = before - len(out)
        return out

    def _tile_needed(self, tile, region: STRtree) -> bool:
        s, w, n, e = tile
        (x0, y0), (x1, y1) = self.proj.fwd(w, s), self.proj.fwd(e, n)
        return len(region.query(box(x0, y0, x1, y1), predicate="intersects")) > 0

    def is_tile_cut(self, poly_m: BaseGeometry) -> bool:
        return any(poly_m.contains(p) for p in self.tile_cut_pts)
