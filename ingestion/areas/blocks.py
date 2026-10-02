"""City blocks from road geometry.

Pipeline: split ways at junction nodes (topological, so a bridge never
connects to the road under it) -> node at-grade lines geometrically with
unary_union -> shapely polygonize -> classify faces -> merge tiny faces ->
label shared edges with the highest road class / street name.

Land clipping (no TIGER): faces mostly covered by OSM natural=water polygons
are dropped; faces not wholly inside the sample bbox are dropped (the ways
there are only partially fetched, so those faces are unreliable).
"""

from __future__ import annotations

from collections import defaultdict
from typing import NamedTuple

from shapely.geometry import LineString, MultiLineString, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from ingestion.areas.types import RAIL_WEIGHT, Block, ClusterParams, EdgeInfo, RoadWay
from ingestion.roads import ROAD_CLASS_WEIGHTS


class RoadEdge(NamedTuple):
    geom: LineString
    weight: float
    highway: str
    name: str | None
    bridge: bool


class BlockSet(NamedTuple):
    blocks: list[Block]
    edges: list[EdgeInfo]
    road_edges: list[RoadEdge]
    stats: dict


def road_weight(highway: str) -> float:
    if highway == "rail":
        return RAIL_WEIGHT
    return ROAD_CLASS_WEIGHTS.get(highway, 1.0)


def split_ways(roads: list[RoadWay]) -> list[RoadEdge]:
    """Cuts each way at nodes shared with any other way (or itself)."""
    count: dict[int, int] = defaultdict(int)
    for r in roads:
        for n in r.nodes:
            count[n] += 1
    out: list[RoadEdge] = []
    for r in roads:
        w = road_weight(r.highway)
        start = 0
        last = len(r.nodes) - 1
        for i in range(1, last + 1):
            if i == last or count[r.nodes[i]] > 1:
                pts = r.coords[start : i + 1]
                if len(pts) >= 2 and pts[0] != pts[-1] or len(pts) > 3:
                    out.append(RoadEdge(LineString(pts), w, r.highway, r.name, r.bridge))
                start = i
    return out


def polygonize_faces(edges: list[RoadEdge]) -> list[BaseGeometry]:
    ground = [e.geom for e in edges if not e.bridge]
    bridges = [e.geom for e in edges if e.bridge]
    parts = []
    if ground:
        parts.append(unary_union(MultiLineString([list(g.coords) for g in ground])))
    parts.extend(bridges)
    return sorted(polygonize(parts), key=lambda p: (round(p.centroid.x, 3), round(p.centroid.y, 3)))


def carve_hard_roads(
    faces: list[BaseGeometry], road_edges: list[RoadEdge], hard_weight: float, width_m: float = 3.0
) -> tuple[list[BaseGeometry], int]:
    """Faces can contain at-grade hard roads (secondary+, rail) that do not
    topologically split them (dangles: an expressway whose crossing streets
    are unmapped grade separations, a tunnel portal whose tunnel was dropped).
    Physically they still divide the area, so cut a `width_m` slit along them;
    pieces that separate become distinct faces with no adjacency to each
    other, and no neighbourhood can contain the road."""
    hard = [e.geom for e in road_edges if e.weight >= hard_weight and not e.bridge]
    if not hard:
        return faces, 0
    tree = STRtree(hard)
    out: list[BaseGeometry] = []
    carved = 0
    for f in faces:
        inner = f.buffer(-1.5)
        idx = tree.query(inner, predicate="intersects") if not inner.is_empty else []
        if len(idx) == 0:
            out.append(f)
            continue
        lines = unary_union([hard[i].intersection(f) for i in sorted(idx)])
        if lines.length < 20.0:
            out.append(f)
            continue
        carved += 1
        rest = f.difference(lines.buffer(width_m))
        pieces = [rest] if rest.geom_type == "Polygon" else list(getattr(rest, "geoms", []))
        out.extend(sorted((g for g in pieces if g.geom_type == "Polygon" and g.area > 300), key=lambda g: (round(g.centroid.x, 3), round(g.centroid.y, 3))))
    return out, carved


def cover(geom: BaseGeometry, layer: BaseGeometry | None) -> float:
    if layer is None or layer.is_empty or geom.area == 0:
        return 0.0
    return geom.intersection(layer).area / geom.area


def compute_edges(
    geoms: dict[int, BaseGeometry], road_edges: list[RoadEdge], tree: STRtree | None = None
) -> list[EdgeInfo]:
    ids = sorted(geoms)
    glist = [geoms[i] for i in ids]
    gtree = STRtree(glist)
    if tree is None:
        tree = STRtree([e.geom for e in road_edges])
    out: list[EdgeInfo] = []
    for ai, i in enumerate(ids):
        bi = glist[ai].boundary
        for aj in sorted(gtree.query(glist[ai], predicate="intersects")):
            j = ids[aj]
            if j <= i:
                continue
            shared = bi.intersection(glist[aj].boundary)
            length = shared.length
            if length < 1.0:
                continue
            buf = shared.buffer(2.0)
            weight, hw, by_name = 0.0, None, defaultdict(float)
            for k in tree.query(buf, predicate="intersects"):
                e = road_edges[k]
                ov = e.geom.intersection(buf).length
                if ov < max(3.0, 0.25 * length):
                    continue
                if e.weight > weight:
                    weight, hw = e.weight, e.highway
                if e.name:
                    by_name[e.name] += ov
            if weight == 0.0:
                # shared boundary not backed by any retained road (e.g. face
                # edge created by noding artefacts); treat as a local street.
                weight = 1.0
            name = min(by_name, key=lambda n: (-by_name[n], n)) if by_name else None
            out.append(EdgeInfo(i, j, length, weight, hw, name))
    return out


def build_blocks(
    roads: list[RoadWay],
    water: BaseGeometry | None = None,
    parks: BaseGeometry | None = None,
    bounds: tuple[float, float, float, float] | None = None,
    params: ClusterParams | None = None,
) -> BlockSet:
    p = params or ClusterParams()
    road_edges = split_ways(roads)
    rtree = STRtree([e.geom for e in road_edges])
    faces = polygonize_faces(road_edges)
    rect = box(*bounds) if bounds else None
    faces, carved = carve_hard_roads(faces, road_edges, p.hard_weight)
    stats = {
        "raw_faces": len(faces),
        "carved_faces": carved,
        "edge_faces": 0,
        "water": 0,
        "right_of_way": 0,
    }

    kept: dict[int, BaseGeometry] = {}
    kinds: dict[int, str] = {}
    for fid, f in enumerate(faces):
        if rect is not None and not rect.contains(f):
            stats["edge_faces"] += 1
            continue
        if f.area <= 0:
            continue
        if cover(f, water) > p.water_cover:
            stats["water"] += 1
            continue
        if 2 * f.area / f.length < p.thin_thickness_m:
            stats["right_of_way"] += 1
            continue
        kept[fid] = f
        kinds[fid] = "park" if cover(f, parks) >= p.park_cover else "block"

    # Merge tiny block faces into the neighbour sharing the longest non-hard edge.
    fedges = compute_edges(kept, road_edges, rtree)
    nbr: dict[int, dict[int, float]] = {i: {} for i in kept}
    for e in fedges:
        if (
            kinds[e.a] == "block"
            and kinds[e.b] == "block"
            and e.weight < p.hard_weight
            and e.length >= p.min_contact_m
        ):
            nbr[e.a][e.b] = nbr[e.a].get(e.b, 0.0) + e.length
            nbr[e.b][e.a] = nbr[e.b].get(e.a, 0.0) + e.length
    group = {i: [i] for i in kept}
    area = {i: kept[i].area for i in kept}
    merged = 0
    while True:
        small = sorted(
            (g for g in group if kinds[g] == "block" and area[g] < p.min_block_area_m2 and nbr[g]),
            key=lambda g: (area[g], g),
        )
        if not small:
            break
        g = small[0]
        h = min(nbr[g], key=lambda n: (-nbr[g][n], n))
        for n, ln in nbr[g].items():
            if n == h:
                continue
            nbr[h][n] = nbr[h].get(n, 0.0) + ln
            nbr[n][h] = nbr[n].get(h, 0.0) + ln
            del nbr[n][g]
        del nbr[h][g]
        del nbr[g]
        group[h].extend(group.pop(g))
        area[h] += area.pop(g)
        merged += 1
    stats["merged_small"] = merged

    blocks: list[Block] = []
    order = sorted(group, key=lambda g: (round(kept[g].centroid.x, 3), round(kept[g].centroid.y, 3)))
    for bid, g in enumerate(order):
        members = sorted(group[g])
        geom = kept[members[0]] if len(members) == 1 else unary_union([kept[m] for m in members])
        blocks.append(Block(bid, geom, kinds[g], tuple(members)))
    edges = compute_edges({b.id: b.geom for b in blocks}, road_edges, rtree)
    stats["blocks"] = sum(b.kind == "block" for b in blocks)
    stats["parks"] = sum(b.kind == "park" for b in blocks)
    return BlockSet(blocks, edges, road_edges, stats)
