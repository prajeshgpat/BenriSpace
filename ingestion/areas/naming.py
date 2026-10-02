"""Names for neighborhoods: 'W 4th St & 7th Ave S' from the bounding streets.

Title = longest bounding named street + longest roughly perpendicular named
street. Optional subtitle = an OSM place=neighbourhood/suburb point inside.
Duplicates get a third street, then a numeric suffix as a last resort.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from shapely.geometry import Point
from shapely.strtree import STRtree

from ingestion.areas.blocks import RoadEdge
from ingestion.areas.types import AreaName, Cluster

_ABBR = {
    "street": "St", "avenue": "Ave", "road": "Rd", "boulevard": "Blvd", "drive": "Dr",
    "place": "Pl", "lane": "Ln", "court": "Ct", "parkway": "Pkwy", "highway": "Hwy",
    "expressway": "Expy", "terrace": "Ter", "square": "Sq", "plaza": "Plz",
    "north": "N", "south": "S", "east": "E", "west": "W",
}  # fmt: skip


_DIRECTIONS = {"north", "south", "east", "west"}


def abbreviate(name: str) -> str:
    """'West 4th Street' -> 'W 4th St'. Road-type words are abbreviated only
    after the first word ('Court Street' -> 'Court St'); directions only at
    the start or end."""
    words = re.split(r"\s+", name.strip())
    out = []
    for i, w in enumerate(words):
        key = w.lower().rstrip(".")
        if key in _DIRECTIONS:
            edge = i == 0 or i == len(words) - 1
            others = [x.lower().rstrip(".") for j, x in enumerate(words) if j != i]
            only_type = all(o in _ABBR and o not in _DIRECTIONS for o in others)
            out.append(_ABBR[key] if edge and not only_type else w)
        elif key in _ABBR and i > 0:
            out.append(_ABBR[key])
        else:
            out.append(w)
    return " ".join(out)


def _bearing_diff(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def bounding_streets(geom, road_edges: list[RoadEdge], tree: STRtree, buffer_m: float = 3.0):
    """[(display_name, length_m, bearing_deg_mod_180)] sorted longest first."""
    buf = geom.boundary.buffer(buffer_m)
    acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for k in tree.query(buf, predicate="intersects"):
        e = road_edges[k]
        if not e.name or e.bridge:
            continue
        ov = e.geom.intersection(buf).length
        if ov < 1.0:
            continue
        (x0, y0), (x1, y1) = e.geom.coords[0], e.geom.coords[-1]
        ang = math.atan2(y1 - y0, x1 - x0) * 2.0
        a = acc[abbreviate(e.name)]
        a[0] += ov
        a[1] += ov * math.cos(ang)
        a[2] += ov * math.sin(ang)
    res = []
    for name, (ln, c, s) in acc.items():
        bearing = (math.degrees(math.atan2(s, c)) / 2.0) % 180.0
        res.append((name, ln, bearing))
    res.sort(key=lambda t: (-t[1], t[0]))
    return res


def make_title(streets: list[tuple[str, float, float]]) -> str:
    if not streets:
        return ""
    first = streets[0]
    rest = streets[1:]
    if not rest:
        return first[0]
    perp = [s for s in rest if _bearing_diff(first[2], s[2]) >= 50.0]
    second = perp[0] if perp else rest[0]
    return f"{first[0]} & {second[0]}"


def name_clusters(
    clusters: list[Cluster],
    road_edges: list[RoadEdge],
    places: list[tuple[str, float, float]] | None = None,
) -> dict:
    """Sets cluster.name on every cluster; returns naming stats."""
    tree = STRtree([e.geom for e in road_edges])
    titles: dict[int, str] = {}
    streets_of: dict[int, list] = {}
    for c in clusters:
        streets = bounding_streets(c.geom, road_edges, tree)
        streets_of[c.id] = streets
        titles[c.id] = make_title(streets)

    initial = dict(titles)
    counts: dict[str, int] = defaultdict(int)
    for t in initial.values():
        counts[t] += 1
    dup_initial = sum(n for t, n in counts.items() if t and n > 1)

    for c in clusters:
        t = titles[c.id]
        if t and counts[t] > 1:
            used = set(t.split(" & "))
            extra = [s[0] for s in streets_of[c.id] if s[0] not in used]
            if extra:
                titles[c.id] = f"{t} & {extra[0]}"
    final_counts: dict[str, int] = defaultdict(int)
    for c in clusters:
        t = titles[c.id] or f"Area {c.id}"
        final_counts[t] += 1
        titles[c.id] = t if final_counts[t] == 1 else f"{t} ({final_counts[t]})"

    for c in clusters:
        sub = ""
        for nm, x, y in places or []:
            if c.geom.contains(Point(x, y)):
                sub = nm
                break
        c.name = AreaName(titles[c.id], sub, tuple(s[0] for s in streets_of[c.id][:6]))
    n = max(len(clusters), 1)
    return {
        "empty_names": sum(1 for c in clusters if not c.name.title),
        "duplicate_rate_initial": dup_initial / n,
        "duplicate_rate_final": sum(1 for t in titles.values() if "(" in t and t.endswith(")")) / n,
    }
