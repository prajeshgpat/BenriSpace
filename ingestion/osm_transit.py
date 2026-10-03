"""OpenStreetMap transit stops, used by ingestion/gtfs_transit.py as an extra
pseudo-agency ('osm') to fill coverage gaps (NJ Transit without a key, CT /
Westchester / Long Island buses, PATH-adjacent areas).

One Overpass union query per metro bbox (ingestion.grid.BOUNDING_BOXES) with
quadrant split on timeout, the same pattern as ingestion/osm_poi.py. Nodes only:
railway=station|halt|tram_stop, public_transport=station, and highway=bus_stop
that carries a name or ref. Subway entrances are deliberately excluded.

Pure functions (query, parse, dedupe, places) are unit tested; the fetch is
thin network glue.
"""

import math
import sys
from dataclasses import dataclass

from common.geo import haversine_m
from common.overpass import fetch_with_quadrant_split, post_overpass_query
from common.places import Place, clean_name
from ingestion.grid import BOUNDING_BOXES

OVERPASS_TIMEOUT_S = 180
HTTP_TIMEOUT_S = OVERPASS_TIMEOUT_S + 30

DEDUPE_M = 40.0
PLACES_SOURCE = "osmtransit"  # distinct from 'osm' so replace_places('osm') never touches it
BUCKET_DEG = 0.001  # ~111 m x ~84 m: a 40 m radius needs ring 1


@dataclass(frozen=True)
class OsmStop:
    lat: float
    lon: float
    name: str | None  # cleaned name tag, or None (ref-only bus stops)
    osm_id: str  # "node/123"
    ref: str | None = None


def build_query(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> str:
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    statements = [
        f'node["railway"="station"]({bbox});',
        f'node["railway"="halt"]({bbox});',
        f'node["railway"="tram_stop"]({bbox});',
        f'node["public_transport"="station"]({bbox});',
        f'node["highway"="bus_stop"]["name"]({bbox});',
        f'node["highway"="bus_stop"]["ref"]({bbox});',
    ]
    body = "\n  ".join(statements)
    return f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n(\n  {body}\n);\nout;"


def parse_stops(data: dict) -> list[OsmStop]:
    """Nodes with a location; bus stops with neither name nor ref are skipped
    (they are untrustworthy). Duplicate node ids collapse."""
    stops: list[OsmStop] = []
    seen: set[str] = set()
    for el in data.get("elements", []):
        if el.get("type") != "node" or el.get("id") is None:
            continue
        lat, lon = el.get("lat"), el.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags") or {}
        name = clean_name(tags.get("name"))
        ref = clean_name(tags.get("ref"))
        if tags.get("highway") == "bus_stop" and name is None and ref is None:
            continue
        osm_id = f"node/{el['id']}"
        if osm_id in seen:
            continue
        seen.add(osm_id)
        stops.append(OsmStop(float(lat), float(lon), name, osm_id, ref))
    return stops


def _key(lat: float, lon: float) -> tuple[int, int]:
    return math.floor(lat / BUCKET_DEG), math.floor(lon / BUCKET_DEG)


def _near_any(lat: float, lon: float, index: dict, within_m: float, name: str | None = None) -> bool:
    cx, cy = _key(lat, lon)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for qlat, qlon, qname in index.get((cx + dx, cy + dy), ()):
                if name is not None and qname != name:
                    continue
                if haversine_m(lat, lon, qlat, qlon) <= within_m:
                    return True
    return False


def dedupe_osm_stops(
    stops: list[OsmStop],
    gtfs_coords: list[tuple[float, float]],
    within_m: float = DEDUPE_M,
) -> list[OsmStop]:
    """Drops OSM stops within within_m of any GTFS stop, and OSM stops with the
    same (casefolded) name within within_m of an already kept one. Unnamed
    ref-only stops are only deduped against GTFS and by identical ref."""
    gtfs_index: dict[tuple[int, int], list] = {}
    for lat, lon in gtfs_coords:
        gtfs_index.setdefault(_key(lat, lon), []).append((lat, lon, None))
    kept_index: dict[tuple[int, int], list] = {}
    kept: list[OsmStop] = []
    for s in stops:
        if _near_any(s.lat, s.lon, gtfs_index, within_m):
            continue
        ident = (s.name or f"ref:{s.ref}").casefold()
        if _near_any(s.lat, s.lon, kept_index, within_m, ident):
            continue
        kept_index.setdefault(_key(s.lat, s.lon), []).append((s.lat, s.lon, ident))
        kept.append(s)
    return kept


def stops_to_places(stops: list[OsmStop]) -> list[Place]:
    """Named stops only; ref-only bus stops still score but are not listed."""
    return [
        Place(PLACES_SOURCE, s.osm_id, "transit", s.name, s.lat, s.lon)
        for s in stops
        if s.name is not None
    ]


def fetch_metro_stops(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> list[OsmStop]:
    def fetch(lat0: float, lat1: float, lon0: float, lon1: float) -> dict:
        return post_overpass_query(build_query(lat0, lat1, lon0, lon1), timeout=HTTP_TIMEOUT_S)

    return parse_stops(fetch_with_quadrant_split(fetch, min_lat, max_lat, min_lon, max_lon))


def fetch_all_stops() -> list[OsmStop]:
    """Every metro bbox, merged by OSM id. Raises if any bbox fails (the caller
    isolates that and falls back to GTFS only)."""
    by_id: dict[str, OsmStop] = {}
    for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
        print(f"osm_transit: fetching Overpass stops for {metro_area}...", file=sys.stderr)
        for s in fetch_metro_stops(min_lat, max_lat, min_lon, max_lon):
            by_id.setdefault(s.osm_id, s)
    return list(by_id.values())
