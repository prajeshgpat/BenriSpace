"""Writes major roads (motorway..secondary, with links) and mainline rail to road_segments.

PostGIS foundation for indexed noise / frontage queries (docs/PLANNED.md Wave 3). Reuses the
road hierarchy from ingestion/roads.py (is_major_corridor: secondary and above) and the
shared Overpass retry / quadrant-split machinery. Ways are stored whole (one LineString per
OSM way, de-duplicated by osm_id across overlapping metro boxes). Table: migration 0012
(NOT yet applied). The pure functions are tested; run() is not.
"""

from __future__ import annotations

import sys

from common.db import get_connection
from common.ingestion_log import ingestion_job
from common.overpass import fetch_with_quadrant_split, post_overpass_query
from ingestion.grid import BOUNDING_BOXES
from ingestion.roads import is_major_corridor

OVERPASS_TIMEOUT_S = 180
MAJOR_HIGHWAYS = (
    "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link"
)
RAIL = "rail"


def build_query(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> str:
    bbox = f"({min_lat},{min_lon},{max_lat},{max_lon})"
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n"
        f'(way["highway"~"^({MAJOR_HIGHWAYS})$"]{bbox};'
        f'way["railway"="rail"]{bbox};);\n'
        "out geom tags;"
    )


def classify(tags: dict) -> str | None:
    """'rail', a major highway value, or None for anything else."""
    if tags.get("railway") == "rail":
        return RAIL
    highway = tags.get("highway")
    if highway and highway.split("_")[0] in {h.split("_")[0] for h in MAJOR_HIGHWAYS.split("|")}:
        return highway
    return None


def parse_ways(data: dict) -> list[dict]:
    """Overpass JSON -> [{osm_id, highway, name, is_emergency_route, coords [(lon, lat)]}].

    Ways without at least two nodes are dropped. Duplicate osm_ids (overlapping bbox tiles)
    keep the first occurrence. is_emergency_route is true for secondary-and-above roads
    (the same corridor grade ingestion/roads.py uses), never for rail."""
    seen: set[int] = set()
    out: list[dict] = []
    for el in data.get("elements", []):
        if el.get("type") != "way" or el.get("id") in seen:
            continue
        tags = el.get("tags") or {}
        kind = classify(tags)
        coords = [(g["lon"], g["lat"]) for g in el.get("geometry") or [] if g]
        if kind is None or len(coords) < 2:
            continue
        seen.add(el["id"])
        out.append(
            {
                "osm_id": el["id"],
                "highway": kind,
                "name": tags.get("name"),
                "is_emergency_route": kind != RAIL and is_major_corridor(kind),
                "coords": coords,
            }
        )
    return out


def to_wkt(coords: list[tuple[float, float]]) -> str:
    return "LINESTRING(" + ", ".join(f"{lon:.6f} {lat:.6f}" for lon, lat in coords) + ")"


def fetch_ways(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> dict:
    def fetch(lat0: float, lat1: float, lon0: float, lon1: float) -> dict:
        return post_overpass_query(
            build_query(lat0, lat1, lon0, lon1), timeout=OVERPASS_TIMEOUT_S + 30
        )

    return fetch_with_quadrant_split(fetch, min_lat, max_lat, min_lon, max_lon)


def run() -> None:
    ways: dict[int, dict] = {}
    for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
        print(f"road_segments: fetching {metro_area}...", file=sys.stderr)
        for way in parse_ways(fetch_ways(min_lat, max_lat, min_lon, max_lon)):
            ways.setdefault(way["osm_id"], way)
    with get_connection() as conn, ingestion_job("road_segments") as ctx:
        with conn.cursor() as cur:
            cur.execute("delete from road_segments")
            cur.executemany(
                "insert into road_segments (osm_id, highway, name, is_emergency_route, geom)"
                " values (%s, %s, %s, %s, st_geomfromtext(%s, 4326))",
                [
                    (
                        w["osm_id"],
                        w["highway"],
                        w["name"],
                        w["is_emergency_route"],
                        to_wkt(w["coords"]),
                    )
                    for w in ways.values()
                ],
            )
        conn.commit()
        ctx.rows_affected = len(ways)
    print(f"road_segments: wrote {len(ways)} ways.", file=sys.stderr)


if __name__ == "__main__":
    run()
