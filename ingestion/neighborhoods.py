"""Human neighborhood names for every grid cell and road-bounded area
("Park Slope, Brooklyn", "Montclair, NJ") from Census boundaries plus OSM nodes.

Census TIGER/Line county subdivisions (towns, townships, cities, NYC boroughs)
say which town a point is inside, so a label never crosses a river or state
line. One Overpass query per metro bbox fetches place=neighbourhood|suburb|
quarter nodes, each filed under the town polygon containing it. label_point():

  NYC               'Neighbourhood, Borough': nearest node within 1.2 mi in the
                    SAME borough; fallback 'Borough'.
  Town with >= 5    'Neighbourhood, City' from nodes inside the same town
  nodes             within 1.2 mi; fallback 'City, ST'.
  Everywhere else   'Town, ST' (suffix words town/township/city/village/borough
                    dropped from the display name).
  In no town        nearest town polygon within 0.5 mi, else None.

The label is never built from coordinates. Helpers are pure and unit tested;
run() is DB/network glue writing the `neighborhood` columns (migration 0008).
"""

import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import psycopg
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from common.coverage import BOUNDING_BOXES
from common.db import get_connection, iter_geo_entities
from common.geo import haversine_m
from common.ingestion_log import ingestion_job
from common.overpass import fetch_with_quadrant_split, post_overpass_query
from ingestion.school_districts import download_cached, read_shapefile

OVERPASS_TIMEOUT_S = 180
HTTP_TIMEOUT_S = OVERPASS_TIMEOUT_S + 30
BATCH_SIZE = 2000

M_PER_MI = 1609.344
NEIGHBOURHOOD_RADIUS_M = 1.2 * M_PER_MI

PLACE_TYPES = ("neighbourhood", "suburb", "quarter")
NEIGHBOURHOOD_TYPES = frozenset(PLACE_TYPES)

# (lat, lon, name, place_type)
NamedPlace = tuple[float, float, str, str]


# --------------------------------------------------------------------------
# Overpass
# --------------------------------------------------------------------------


def build_overpass_query(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> str:
    types = "|".join(PLACE_TYPES)
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n"
        f'node["place"~"^({types})$"]["name"]({min_lat},{min_lon},{max_lat},{max_lon});\n'
        "out;"
    )


def parse_places(data: dict) -> list[NamedPlace]:
    """Named place nodes of a recognised type; anything else is dropped."""
    out: list[NamedPlace] = []
    for el in data.get("elements", []):
        if el.get("type") not in (None, "node"):
            continue
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        ptype = tags.get("place")
        lat, lon = el.get("lat"), el.get("lon")
        if not name or ptype not in PLACE_TYPES or lat is None or lon is None:
            continue
        out.append((float(lat), float(lon), name, ptype))
    return out


def fetch_places(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[NamedPlace]:
    def fetch(a: float, b: float, c: float, d: float) -> dict:
        return post_overpass_query(build_overpass_query(a, b, c, d), HTTP_TIMEOUT_S)

    return parse_places(fetch_with_quadrant_split(fetch, min_lat, max_lat, min_lon, max_lon))


# --------------------------------------------------------------------------
# Town polygons (Census TIGER/Line county subdivisions)
# --------------------------------------------------------------------------

COUSUB_URL = "https://www2.census.gov/geo/tiger/TIGER{year}/COUSUB/tl_{year}_{fips}_cousub.zip"
COUSUB_YEAR = 2024
COUSUB_CACHE_DIR = Path("data/cache/cousub")
STATE_ABBR = {"09": "CT", "34": "NJ", "36": "NY"}
# New York City boroughs are the county-equivalent subdivisions of these counties.
NYC_BOROUGHS = {
    "36005": "Bronx",
    "36047": "Brooklyn",
    "36061": "Manhattan",
    "36081": "Queens",
    "36085": "Staten Island",
}
NO_SUBDIVISION = "county subdivisions not defined"  # water; LSAD 00 is also Princeton
SUFFIX_WORDS = ("town", "township", "city", "village", "borough")
MIN_CITY_NODES = 5  # a town with this many neighbourhood nodes is labelled by them
EDGE_RADIUS_M = 0.5 * M_PER_MI
_EDGE_DEG = 0.012  # candidate window for the edge search (>= 0.5 mi in lat and lon)


@dataclass
class Town:
    name: str  # display name, suffix words stripped
    state: str  # NY / NJ / CT
    borough: str | None = None  # set for the five NYC boroughs
    nodes: list[NamedPlace] = field(default_factory=list)  # neighbourhood nodes inside


def strip_suffix(namelsad: str) -> str:
    """'Hoboken city' -> 'Hoboken', 'West Orange township' -> 'West Orange'.
    Only a trailing legal-status word is removed; names without one are kept."""
    words = namelsad.strip().split()
    if len(words) > 1 and words[-1].lower() in SUFFIX_WORDS:
        words = words[:-1]
    return " ".join(words)


def towns_from_records(records: Iterable[tuple[dict, dict]]) -> list[tuple[Town, BaseGeometry]]:
    """TIGER COUSUB (attributes, GeoJSON geometry) records -> towns. Undefined
    (water) subdivisions and states outside the metro are dropped."""
    out: list[tuple[Town, BaseGeometry]] = []
    for attrs, geom in records:
        state = STATE_ABBR.get(str(attrs.get("STATEFP") or ""))
        if state is None or geom is None:
            continue
        if NO_SUBDIVISION in str(attrs.get("NAMELSAD") or attrs.get("NAME") or "").lower():
            continue
        name = str(attrs.get("NAME") or "").strip() or strip_suffix(
            str(attrs.get("NAMELSAD") or "")
        )
        if not name:
            continue
        county = f"{attrs.get('STATEFP')}{attrs.get('COUNTYFP')}"
        out.append((Town(name, state, NYC_BOROUGHS.get(county)), shape(geom)))
    return out


class TownIndex:
    """Containing-town lookup plus the neighbourhood nodes inside each town."""

    def __init__(self, items: Iterable[tuple[Town, BaseGeometry]]):
        pairs = list(items)
        self._towns = [t for t, _ in pairs]
        self._geoms = [g for _, g in pairs]
        self._tree = STRtree(self._geoms) if self._geoms else None

    def __len__(self) -> int:
        return len(self._towns)

    def town_at(self, lat: float, lon: float, edge_m: float = EDGE_RADIUS_M) -> Town | None:
        """Town containing the point; else the nearest within edge_m; else None."""
        if self._tree is None:
            return None
        point = Point(lon, lat)
        hits = self._tree.query(point, predicate="intersects")
        if len(hits):
            return self._towns[min(hits)]
        best: tuple[float, int] | None = None
        window = point.buffer(_EDGE_DEG)
        for i in self._tree.query(window):
            near = nearest_points(self._geoms[i], point)[0]
            d = haversine_m(lat, lon, near.y, near.x)
            if d <= edge_m and (best is None or d < best[0]):
                best = (d, int(i))
        return self._towns[best[1]] if best else None

    def add_nodes(self, places: Iterable[NamedPlace]) -> None:
        """Files each neighbourhood-tier node under the town polygon that
        contains it (exact repeats and nodes in no town are dropped)."""
        seen: set[NamedPlace] = set()
        for p in places:
            if p in seen or p[3] not in NEIGHBOURHOOD_TYPES:
                continue
            seen.add(p)
            if self._tree is None:
                continue
            hits = self._tree.query(Point(p[1], p[0]), predicate="intersects")
            if len(hits):
                self._towns[min(hits)].nodes.append(p)


def build_town_index(
    records: Iterable[tuple[dict, dict]], places: Iterable[NamedPlace] = ()
) -> TownIndex:
    index = TownIndex(towns_from_records(records))
    index.add_nodes(places)
    return index


def load_town_index(places: Iterable[NamedPlace] = ()) -> TownIndex:
    items: list[tuple[Town, BaseGeometry]] = []
    for fips in STATE_ABBR:
        url = COUSUB_URL.format(year=COUSUB_YEAR, fips=fips)
        items.extend(towns_from_records(read_shapefile(download_cached(url, COUSUB_CACHE_DIR))))
    index = TownIndex(items)
    index.add_nodes(places)
    return index


# --------------------------------------------------------------------------
# Labeling
# --------------------------------------------------------------------------


def _nearest_node(town: Town, lat: float, lon: float, skip_name: str) -> str | None:
    best: tuple[float, str] | None = None
    for nlat, nlon, name, _ in town.nodes:
        if name == skip_name:
            continue
        d = haversine_m(lat, lon, nlat, nlon)
        if d <= NEIGHBOURHOOD_RADIUS_M and (best is None or d < best[0]):
            best = (d, name)
    return best[1] if best else None


def label_point(lat: float, lon: float, index: TownIndex) -> str | None:
    """'Neighbourhood, Borough' in NYC, 'Neighbourhood, City' in towns with
    many neighbourhood nodes, else 'Town, ST'. None when the point is in no
    town (and none within half a mile). Never coordinates."""
    town = index.town_at(lat, lon)
    if town is None:
        return None
    if town.borough is not None:
        hood = _nearest_node(town, lat, lon, town.borough)
        return f"{hood}, {town.borough}" if hood else town.borough
    if len(town.nodes) >= MIN_CITY_NODES:
        hood = _nearest_node(town, lat, lon, town.name)
        if hood:
            # "Downtown Jersey City, Jersey City" reads twice: use the state instead.
            parent = town.state if town.name.casefold() in hood.casefold() else town.name
            return f"{hood}, {parent}"
    return f"{town.name}, {town.state}"


# --------------------------------------------------------------------------
# Area representative point
# --------------------------------------------------------------------------


def _ring_centroid(ring: list) -> tuple[float, float, float] | None:
    """(signed area, cx, cy) of a closed [lon, lat] ring (shoelace)."""
    s = cx = cy = 0.0
    for (x0, y0), (x1, y1) in pairwise(ring):
        cross = x0 * y1 - x1 * y0
        s += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(s) < 1e-18:
        return None
    area = s / 2.0
    return area, cx / (6.0 * area), cy / (6.0 * area)


def geometry_centroid(geometry: dict | None) -> tuple[float, float] | None:
    """(lat, lon) centroid of a GeoJSON Polygon/MultiPolygon (exterior rings,
    area weighted), or None for anything unusable."""
    if not geometry:
        return None
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon":
        polygons = [coords]
    elif kind == "MultiPolygon":
        polygons = coords
    else:
        return None
    total = sx = sy = 0.0
    for poly in polygons or []:
        if not poly:
            continue
        c = _ring_centroid(poly[0])
        if c is None:
            continue
        area, cx, cy = abs(c[0]), c[1], c[2]
        total += area
        sx += cx * area
        sy += cy * area
    if total <= 0:
        return None
    return sy / total, sx / total


# --------------------------------------------------------------------------
# DB / network glue
# --------------------------------------------------------------------------


def _write_batches(conn, table: str, rows: list[tuple[str | None, object]]) -> int:
    for i in range(0, len(rows), BATCH_SIZE):
        with conn.cursor() as cur:
            cur.executemany(
                f"update {table} set neighborhood = %s where id = %s", rows[i : i + BATCH_SIZE]
            )
        conn.commit()
    return len(rows)


def run() -> None:
    with get_connection() as conn, ingestion_job("neighborhoods") as ctx:
        places: list[NamedPlace] = []
        for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
            print(f"neighborhoods: fetching place nodes for {metro_area}...", file=sys.stderr)
            places.extend(fetch_places(min_lat, max_lat, min_lon, max_lon))
        index = load_town_index(places)
        print(
            f"neighborhoods: {len(places)} neighbourhood nodes, {len(index)} towns.",
            file=sys.stderr,
        )

        cell_rows = [
            (label_point(c["latitude"], c["longitude"], index), c["id"])
            for c in iter_geo_entities(conn)
        ]
        written = _write_batches(conn, "geo_entities", cell_rows)
        ctx.rows_affected = written
        named = sum(1 for label, _ in cell_rows if label)
        print(f"neighborhoods: labeled {named}/{written} grid cells.", file=sys.stderr)

        try:
            with conn.cursor() as cur:
                cur.execute("select id, geometry, min_lat, max_lat, min_lon, max_lon from areas")
                areas = list(cur)
        except psycopg.errors.UndefinedTable:
            conn.rollback()
            areas = []
        area_rows = []
        for a in areas:
            point = geometry_centroid(a["geometry"]) or (
                (a["min_lat"] + a["max_lat"]) / 2,
                (a["min_lon"] + a["max_lon"]) / 2,
            )
            area_rows.append((label_point(point[0], point[1], index), a["id"]))
        written_areas = _write_batches(conn, "areas", area_rows)
        ctx.rows_affected += written_areas
        print(f"neighborhoods: labeled {written_areas} areas.", file=sys.stderr)


if __name__ == "__main__":
    run()
