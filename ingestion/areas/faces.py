"""AREAS: faces of the arrangement of secondary-and-above roads.

Pipeline (all geometry in a local metric projection until the final step):
  1. split ways at shared nodes (blocks.split_ways), keep hard-class edges,
     add natural=coastline ways and a frame ring at the fetch bbox;
  2. simplify every EDGE at 3 m (endpoints are preserved, so faces that share
     an edge keep sharing it exactly: no gaps or overlaps);
  3. polygonize the noded linework (blocks.polygonize_faces), keep faces whose
     representative point is inside the frame;
  4. coast rule: OSM coastlines have land on the LEFT. A face that touches the
     coast is land iff the point just left of its coastline pieces lies inside
     it (majority by length); faces not touching the coast are kept. Inland
     lakes/reservoirs are NOT clipped in v1 (only the coastline closes water);
  5. drop faces thinner than 15 m (2*area/perimeter) or under 5,000 m^2;
  6. project back to lon/lat, snap to 5 decimals, compute area (per-face local
     equirectangular), bounded_by (top road names by shared boundary length,
     naming.bounding_streets) and the geohash6 cells overlapped.

  7. size limits (limits.py, limits_apply.py): faces over 0.8 sq mi or with a
     bounding box over 1.4 mi are cut by a ~0.75 mi tile grid, and faces under
     0.02 sq mi merge into the neighbour sharing the longest boundary when
     the caps still hold. bounded_by and cells are computed per final piece.
     Each Face also carries extent_m and compactness (areas.extent_m /
     areas.compactness, migration 0006_area_shape.sql, which must be applied
     BEFORE build --write).
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from common.geo import encode
from ingestion.areas.blocks import RoadEdge, polygonize_faces, split_ways
from ingestion.areas.naming import bounding_streets
from ingestion.areas.osm_source import Projector
from ingestion.areas.types import RoadWay
from ingestion.roads import MAJOR_CLASS_WEIGHT_THRESHOLD

GEOHASH_PRECISION = 6
_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"
COAST_WEIGHT = 99.0
FRAME_WEIGHT = 99.0
_PIECE_M = 60.0  # coast subdivision length for the left-of-coast test


@dataclass(frozen=True)
class FaceParams:
    projector: Projector
    hard_weight: float = MAJOR_CLASS_WEIGHT_THRESHOLD
    simplify_m: float = 3.0
    min_thickness_m: float = 15.0
    min_area_m2: float = 5_000.0
    coast_offset_m: float = 2.0
    decimals: int = 5
    max_bounded_by: int = 4
    enforce_size_limits: bool = True  # split > 0.8 sq mi / 1.4 mi faces, merge slivers
    # None = every grid cell the face overlaps; else only these geohashes.
    geohashes: frozenset[str] | None = None


@dataclass
class Face:
    geometry: BaseGeometry  # lon/lat, snapped to `decimals`
    bounded_by: tuple[str, ...]
    area_sq_m: float
    bbox: tuple[float, float, float, float]  # min_lat, max_lat, min_lon, max_lon
    cells: tuple[tuple[str, float], ...] = field(default_factory=tuple)  # (geohash, overlap_sq_m)
    stats: dict = field(default_factory=dict)
    extent_m: float | None = None  # longest side of the bounding box, local metres
    compactness: float | None = None  # 4*pi*area/perimeter^2


# ---------------------------------------------------------------- geohash


def _interleave(ix: int, iy: int, precision: int) -> str:
    nbits = 5 * precision
    lon_bits = (nbits + 1) // 2
    lat_bits = nbits // 2
    val = 0
    li, ai = lon_bits - 1, lat_bits - 1
    for i in range(nbits):
        if i % 2 == 0:
            bit = (ix >> li) & 1
            li -= 1
        else:
            bit = (iy >> ai) & 1
            ai -= 1
        val = (val << 1) | bit
    return "".join(_B32[(val >> (5 * (precision - 1 - k))) & 31] for k in range(precision))


def _dims(precision: int) -> tuple[int, int]:
    nbits = 5 * precision
    return 1 << ((nbits + 1) // 2), 1 << (nbits // 2)


def geohash_bounds(gh: str) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lon, max_lon) of a geohash cell."""
    lat = [-90.0, 90.0]
    lon = [-180.0, 180.0]
    even = True
    for ch in gh:
        v = _B32.index(ch)
        for b in range(4, -1, -1):
            rng = lon if even else lat
            mid = (rng[0] + rng[1]) / 2
            if (v >> b) & 1:
                rng[0] = mid
            else:
                rng[1] = mid
            even = not even
    return lat[0], lat[1], lon[0], lon[1]


def cells_in_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    precision: int = GEOHASH_PRECISION,
) -> list[str]:
    """Every geohash cell of `precision` whose rectangle meets the bbox."""
    nlon, nlat = _dims(precision)
    dlon, dlat = 360.0 / nlon, 180.0 / nlat
    x0 = max(0, math.floor((min_lon + 180.0) / dlon))
    x1 = min(nlon - 1, math.floor((max_lon + 180.0) / dlon))
    y0 = max(0, math.floor((min_lat + 90.0) / dlat))
    y1 = min(nlat - 1, math.floor((max_lat + 90.0) / dlat))
    return [_interleave(x, y, precision) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


# --------------------------------------------------------------- projection


def local_projector(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> Projector:
    return Projector((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)


def _to_ll(geom: BaseGeometry, proj: Projector) -> BaseGeometry:
    return shapely.transform(
        geom,
        lambda a: np.column_stack((a[:, 0] / proj.kx + proj.lon0, a[:, 1] / proj.ky + proj.lat0)),
    )


def _to_m(geom: BaseGeometry, proj: Projector) -> BaseGeometry:
    return shapely.transform(
        geom,
        lambda a: np.column_stack(
            ((a[:, 0] - proj.lon0) * proj.kx, (a[:, 1] - proj.lat0) * proj.ky)
        ),
    )


def project_back(geom_m: BaseGeometry, proj: Projector, decimals: int) -> BaseGeometry:
    ll = _to_ll(geom_m, proj)
    return shapely.set_precision(ll, 10.0**-decimals)


# ------------------------------------------------------------------ linework


def _lines(g: BaseGeometry) -> list[LineString]:
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    return [x for p in getattr(g, "geoms", []) for x in _lines(p)]


def hard_edges(roads: list[RoadWay], hard_weight: float) -> list[RoadEdge]:
    return [e for e in split_ways(roads) if e.weight >= hard_weight]


def _simplified(e: RoadEdge, tol: float) -> RoadEdge:
    g = e.geom.simplify(tol, preserve_topology=True) if tol > 0 else e.geom
    return RoadEdge(g, e.weight, e.highway, e.name, e.bridge)


def classify_land(
    faces: list[BaseGeometry], coast: list[LineString], offset: float
) -> tuple[list[bool], list[bool]]:
    """(is_land, touches_coast) per face. Coast lines must be in OSM direction."""
    left: dict[int, float] = defaultdict(float)
    right: dict[int, float] = defaultdict(float)
    bounds = [f.boundary for f in faces]
    tree = STRtree(faces)
    for line in coast:
        pts = list(line.coords)
        for (x0, y0), (x1, y1) in itertools.pairwise(pts):
            seg = math.hypot(x1 - x0, y1 - y0)
            if seg < 1e-6:
                continue
            n = max(1, math.ceil(seg / _PIECE_M))
            nx, ny = -(y1 - y0) / seg, (x1 - x0) / seg
            for k in range(n):
                t = (k + 0.5) / n
                mx, my = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
                ln = seg / n
                pm = Point(mx, my)
                for fi in tree.query(pm.buffer(1.0)):
                    if bounds[fi].distance(pm) > 0.5:
                        continue
                    if faces[fi].contains(Point(mx + offset * nx, my + offset * ny)):
                        left[fi] += ln
                    elif faces[fi].contains(Point(mx - offset * nx, my - offset * ny)):
                        right[fi] += ln
    touches = [(left[i] + right[i]) > 0 for i in range(len(faces))]
    land = [(left[i] >= right[i]) if touches[i] else True for i in range(len(faces))]
    return land, touches


# --------------------------------------------------------------------- cells


def cell_overlaps(
    geom_ll: BaseGeometry, proj: Projector, geohashes: frozenset[str] | None, min_m2: float = 1.0
) -> list[tuple[str, float]]:
    """Land-clipped overlap area in m^2 of the face with each geohash6 cell,
    in the face-local equirectangular projection `proj`."""
    minx, miny, maxx, maxy = geom_ll.bounds
    cells = cells_in_bbox(miny, maxy, minx, maxx)
    if geohashes is not None:
        cells = [c for c in cells if c in geohashes]
    if not cells:
        return []
    geom = _to_m(geom_ll, proj)
    shapely.prepare(geom)
    boxes = []
    for c in cells:
        a, b, lo, hi = geohash_bounds(c)
        (x0, y0), (x1, y1) = proj.fwd(lo, a), proj.fwd(hi, b)
        boxes.append(shapely.box(x0, y0, x1, y1))
    areas = shapely.area(shapely.intersection(geom, np.array(boxes, dtype=object)))
    out = [(c, float(a)) for c, a in zip(cells, areas, strict=True) if a >= min_m2]
    out.sort()
    return out


# ----------------------------------------------------------------- main build


def build_faces(
    roads: list[RoadWay],
    coast: list[list[tuple[float, float]]],
    frame: Polygon,
    params: FaceParams,
) -> list[Face]:
    """Faces (no ids yet; see number_faces) of the hard-road arrangement.
    roads/coast/frame are in params.projector meters."""
    p = params
    reach = frame.buffer(2_000.0)
    edges = [e for e in hard_edges(roads, p.hard_weight) if e.geom.intersects(reach)]
    edges = [_simplified(e, p.simplify_m) for e in edges]
    coast_lines = [
        _simplified(
            RoadEdge(LineString(c), COAST_WEIGHT, "coastline", None, False), p.simplify_m
        ).geom
        for c in coast
        if len(c) >= 2 and LineString(c).intersects(reach)
    ]
    ring = LineString(list(frame.exterior.coords))
    base = [RoadEdge(g, COAST_WEIGHT, "coastline", None, False) for g in coast_lines]
    base.append(RoadEdge(ring, FRAME_WEIGHT, "frame", None, False))

    def arrange(lines: list[RoadEdge]) -> tuple[list[BaseGeometry], list[bool]]:
        # Planar arrangement: every hard line is noded with every other, bridge
        # or not (grade is irrelevant to the faces; polygonize_faces would keep
        # bridges un-noded, which drops enclosed regions).
        flat = [RoadEdge(e.geom, e.weight, e.highway, e.name, False) for e in lines + base]
        fs = [f for f in polygonize_faces(flat) if frame.contains(f.representative_point())]
        return fs, classify_land(fs, coast_lines, p.coast_offset_m)[0]

    ground = [e for e in edges if not e.bridge]
    bridges = [e for e in edges if e.bridge]
    raw, land = arrange(ground)
    if bridges:
        # Pass 2: bridges count, but only the parts over land (a bridge over the
        # harbour must not close a sliver "face" over water).
        sea = unary_union([f for f, is_land in zip(raw, land, strict=True) if not is_land])
        kept = []
        for e in bridges:
            for piece in _lines(e.geom.difference(sea)):
                kept.append(RoadEdge(piece, e.weight, e.highway, e.name, True))
        raw, land = arrange(ground + kept)
        edges = ground + kept

    named = [e for e in edges if e.name]
    tree = STRtree([e.geom for e in named]) if named else None

    kept: list[Polygon] = []
    for f, is_land in zip(raw, land, strict=True):
        if not is_land:
            continue
        if f.area < p.min_area_m2:
            continue
        if 2 * f.area / f.length < p.min_thickness_m:
            continue
        kept.extend(g for g in ([f] if f.geom_type == "Polygon" else getattr(f, "geoms", [])))

    from ingestion.areas.limits_apply import compactness, enforce_limits

    faces: list[Face] = []
    for f in enforce_limits(kept, p.projector) if p.enforce_size_limits else kept:
        ll = project_back(f, p.projector, p.decimals)
        if ll.is_empty or not ll.geom_type.endswith("Polygon"):
            continue
        minx, miny, maxx, maxy = ll.bounds
        local = local_projector(miny, maxy, minx, maxx)
        local_m = _to_m(ll, local)
        area = local_m.area
        x0, y0, x1, y1 = local_m.bounds
        streets = bounding_streets(f, named, tree) if tree is not None else []
        names = tuple(s[0] for s in streets[: p.max_bounded_by])
        cells = tuple(cell_overlaps(ll, local, p.geohashes))
        faces.append(
            Face(
                ll, names, area, (miny, maxy, minx, maxx), cells,
                extent_m=max(x1 - x0, y1 - y0),
                compactness=compactness(area, local_m.length),
            )
        )  # fmt: skip
    return faces


def representative_geohash(face: Face, precision: int = 9) -> str:
    pt = face.geometry.representative_point()
    return encode(pt.y, pt.x, precision)


def number_faces(faces: list[Face]) -> list[tuple[int, Face]]:
    """Deterministic ids from 1: sorted by (representative-point geohash, area)."""
    keyed = sorted(faces, key=lambda f: (representative_geohash(f), round(f.area_sq_m, 1)))
    return [(i, f) for i, f in enumerate(keyed, start=1)]
