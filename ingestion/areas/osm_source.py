"""Overpass source for the area prototype: ONE request for the sample bbox,
cached gzipped on disk (never re-fetched once cached).

Layers: road/rail ways (with node ids so junctions are topological), water and
park/cemetery polygons (ways + multipolygon relations), place points.
Land clipping approach: no TIGER; faces covered >50% by OSM water polygons are
dropped (see blocks.py).
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from common.overpass import post_overpass_query
from ingestion.areas.types import RoadWay

SAMPLE_BBOX = (40.680, -74.020, 40.735, -73.970)  # south, west, north, east

ROAD_CLASSES = (
    "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link"
    "|tertiary|tertiary_link|unclassified|residential|living_street|pedestrian"
)
ALLOWED_HIGHWAYS = set(ROAD_CLASSES.split("|"))
PARK_LEISURE = "park|garden|playground|pitch|recreation_ground|nature_reserve|golf_course"
PARK_LANDUSE = "cemetery|recreation_ground|village_green|grass"
PLACE_TAGS = "neighbourhood|suburb|quarter"


class Projector:
    """Equirectangular projection about a bbox center, in meters."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 111_320.0 * math.cos(math.radians(lat0))
        self.ky = 110_574.0

    def fwd(self, lon: float, lat: float) -> tuple[float, float]:
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def inv(self, x: float, y: float) -> tuple[float, float]:
        return (x / self.kx + self.lon0, y / self.ky + self.lat0)


@dataclass
class Layers:
    roads: list[RoadWay] = field(default_factory=list)
    water: BaseGeometry | None = None
    parks: BaseGeometry | None = None
    places: list[tuple[str, float, float]] = field(default_factory=list)  # name, x, y
    projector: Projector | None = None


def build_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    b = f"({s},{w},{n},{e})"
    return f"""[out:json][timeout:240];
(
  way["highway"~"^({ROAD_CLASSES})$"]{b};
  way["railway"="rail"]{b};
  way["natural"="water"]{b};
  relation["natural"="water"]{b};
  way["natural"="coastline"]{b};
  way["leisure"~"^({PARK_LEISURE})$"]{b};
  relation["leisure"~"^({PARK_LEISURE})$"]{b};
  way["landuse"~"^({PARK_LANDUSE})$"]{b};
  relation["landuse"~"^({PARK_LANDUSE})$"]{b};
  node["place"~"^({PLACE_TAGS})$"]{b};
);
out geom;
"""


def cache_path(bbox: tuple[float, float, float, float], cache_dir: Path) -> Path:
    s, w, n, e = bbox
    return Path(cache_dir) / f"areas_overpass_{s}_{w}_{n}_{e}.json.gz"


def fetch_layers_raw(bbox: tuple[float, float, float, float], cache_dir: Path) -> dict:
    """Returns the raw Overpass JSON; hits the network only if not cached."""
    path = cache_path(bbox, cache_dir)
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = post_overpass_query(build_query(bbox), timeout=300)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(path)
    return data


def fetch_layers(bbox: tuple[float, float, float, float], cache_dir: Path) -> Layers:
    return parse_layers(fetch_layers_raw(bbox, cache_dir), bbox)


def _line(geom: list[dict | None], proj: Projector) -> list[tuple[float, float]]:
    return [proj.fwd(p["lon"], p["lat"]) for p in geom if p]


def _polygons_from_rings(outers: list[list], inners: list[list]) -> BaseGeometry | None:
    from shapely.geometry import LineString

    def rings(lines):
        lines = [LineString(c) for c in lines if len(c) >= 2]
        if not lines:
            return None
        polys = list(polygonize(unary_union(lines)))
        return unary_union(polys) if polys else None

    o = rings(outers)
    if o is None:
        return None
    i = rings(inners)
    return o.difference(i) if i is not None else o


def parse_layers(data: dict, bbox: tuple[float, float, float, float]) -> Layers:
    s, w, n, e = bbox
    proj = Projector((s + n) / 2, (w + e) / 2)
    out = Layers(projector=proj)
    water_parts: list[BaseGeometry] = []
    park_parts: list[BaseGeometry] = []
    coast_lines: list[list] = []

    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        typ = el.get("type")
        if typ == "node":
            if tags.get("place") and tags.get("name"):
                x, y = proj.fwd(el["lon"], el["lat"])
                out.places.append((tags["name"], x, y))
            continue
        is_water = tags.get("natural") == "water"
        is_park = bool(
            tags.get("leisure") in PARK_LEISURE.split("|")
            or tags.get("landuse") in PARK_LANDUSE.split("|")
        )
        if typ == "way":
            coords = _line(el.get("geometry") or [], proj)
            if len(coords) < 2:
                continue
            hw = tags.get("highway")
            if hw in ALLOWED_HIGHWAYS or tags.get("railway") == "rail":
                tunnel = tags.get("tunnel")
                if tunnel and tunnel != "no":
                    continue
                if tags.get("area") == "yes":
                    continue
                if tags.get("railway") and tags.get("service"):
                    continue  # yard / siding / spur: not a neighbourhood barrier
                nodes = tuple(el.get("nodes") or [])
                if len(nodes) != len(coords):
                    continue  # geometry had holes; skip rather than mis-index
                out.roads.append(
                    RoadWay(
                        id=el["id"],
                        highway=hw or "rail",
                        name=tags.get("name"),
                        nodes=nodes,
                        coords=tuple(coords),
                        bridge=bool(tags.get("bridge") and tags.get("bridge") != "no"),
                    )
                )
            elif tags.get("natural") == "coastline":
                coast_lines.append(coords)
            elif (is_water or is_park) and len(coords) >= 4 and coords[0] == coords[-1]:
                poly = Polygon(coords)
                if poly.is_valid and poly.area > 0:
                    (water_parts if is_water else park_parts).append(poly)
        elif typ == "relation" and (is_water or is_park):
            outers, inners = [], []
            for m in el.get("members", []):
                if m.get("type") != "way" or not m.get("geometry"):
                    continue
                (inners if m.get("role") == "inner" else outers).append(_line(m["geometry"], proj))
            g = _polygons_from_rings(outers, inners)
            if g is not None and not g.is_empty:
                (water_parts if is_water else park_parts).append(g)

    out.water = unary_union([g.buffer(0) for g in water_parts]) if water_parts else None
    out.parks = unary_union([g.buffer(0) for g in park_parts]) if park_parts else None
    out.roads.sort(key=lambda r: r.id)
    out.places.sort()
    return out


def point_in(geom: BaseGeometry, x: float, y: float) -> bool:
    return geom.contains(Point(x, y))
