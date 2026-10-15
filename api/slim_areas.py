"""GET /v1/area against the compact `areas_slim` table (migration 0014).

Active when AREAS_TABLE=areas_slim. The table lives in DATABASE_URL, or in the
database named by AREAS_DATABASE_URL (a local PostGIS container while testing).
The area under a point is the SMALLEST polygon containing it (ST_Contains on the
GiST-indexed geom); a point on a road line snaps to the nearest polygon within 40 m
(ST_DWithin). The GeoJSON comes from ST_AsGeoJSON(geom). Polygons carry no stored
scores: the caller scores them by on-demand point sampling.
"""

import json
import os

from api.areas import SNAP_M, SQ_M_PER_SQ_MI
from common.db import api_connection

AREAS_TABLE_ENV = "AREAS_TABLE"
AREAS_DATABASE_URL_ENV = "AREAS_DATABASE_URL"
GEOJSON_DECIMALS = 6
# Degrees that cover SNAP_M at these latitudes (index prefilter before the exact test).
_PREFILTER_DEG = 0.0007

FIND_AREA_SQL = f"""
    with p as (select st_setsrid(st_makepoint(%(lon)s, %(lat)s), 4326) as pt)
    select a.id, a.area_sq_mi, a.extent_mi, a.compactness, a.bounded_by, a.neighborhood,
           st_asgeojson(a.geom, {GEOJSON_DECIMALS}) as geojson,
           st_contains(a.geom, p.pt) as inside
    from areas_slim a, p
    where a.geom && st_expand(p.pt, {_PREFILTER_DEG})
      and (st_contains(a.geom, p.pt)
           or st_dwithin(a.geom::geography, p.pt::geography, %(snap)s))
    order by st_contains(a.geom, p.pt) desc,
             case when st_contains(a.geom, p.pt) then a.area_sq_mi end asc,
             st_distance(a.geom::geography, p.pt::geography) asc
    limit 1
"""


def enabled() -> bool:
    return os.environ.get(AREAS_TABLE_ENV, "").strip() == "areas_slim"


def row_to_area(row: dict) -> dict:
    """An areas_slim row as the dict api.areas.build_area_response expects."""
    return {
        "id": row["id"],
        "area_sq_m": float(row["area_sq_mi"]) * SQ_M_PER_SQ_MI,
        "extent_m": None if row.get("extent_mi") is None else float(row["extent_mi"]) * 1609.344,
        "geometry": json.loads(row["geojson"]),
        "bounded_by": list(row.get("bounded_by") or []),
        "neighborhood": row.get("neighborhood"),
    }


def _query(conn, lat: float, lon: float) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(FIND_AREA_SQL, {"lat": lat, "lon": lon, "snap": SNAP_M})
        row = cur.fetchone()
    return None if row is None else row_to_area(row)


def has_own_database() -> bool:
    return bool(os.environ.get(AREAS_DATABASE_URL_ENV, "").strip())


def find_area(conn, lat: float, lon: float) -> dict | None:
    """Smallest containing area, else the nearest within 40 m, else None. Uses the
    AREAS_DATABASE_URL database when set, otherwise the caller's connection."""
    url = os.environ.get(AREAS_DATABASE_URL_ENV, "").strip()
    if url:
        with api_connection(url) as aconn:
            return _query(aconn, lat, lon)
    return _query(conn, lat, lon)


# A grid cell whose centre is in the water still has land within about half its diagonal
# (0.58 x 0.38 mi cells); a centre farther than this from every area is open water.
LAND_SNAP_MAX_MI = 0.35
_M_PER_MI = 1609.344

LAND_SNAP_SQL = """
    select r.ord, st_y(c.pt) as lat, st_x(c.pt) as lon, c.dist_m
    from unnest(%(lats)s::float8[], %(lons)s::float8[]) with ordinality as r(lat, lon, ord)
    cross join lateral (select st_setsrid(st_makepoint(r.lon, r.lat), 4326) as pt) p
    cross join lateral (
        select st_closestpoint(a.geom, p.pt) as pt,
               st_distance(a.geom::geography, p.pt::geography) as dist_m
        from areas_slim a
        order by a.geom <-> p.pt
        limit 1
    ) c
    order by r.ord
"""


def _snap(conn, points: list[tuple[float, float]]) -> list[tuple[float, float] | None]:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            LAND_SNAP_SQL,
            {"lats": [p[0] for p in points], "lons": [p[1] for p in points]},
        )
        rows = cur.fetchall()
    by_ord = {int(r["ord"]): r for r in rows}
    out: list[tuple[float, float] | None] = []
    for i in range(1, len(points) + 1):
        row = by_ord.get(i)
        if row is None or float(row["dist_m"]) > LAND_SNAP_MAX_MI * _M_PER_MI:
            out.append(None)
        else:
            out.append((float(row["lat"]), float(row["lon"])))
    return out


def snap_to_land(conn, points: list[tuple[float, float]]) -> list[tuple[float, float] | None] | None:
    """Each point moved onto the nearest road-bounded area (unchanged when it is already on
    one), or None for a point in open water, so a map pin never sits in a river. The whole
    answer is None when the areas table is unavailable; callers then keep the points as they
    are."""
    if not points:
        return []
    try:
        url = os.environ.get(AREAS_DATABASE_URL_ENV, "").strip()
        if url:
            with api_connection(url) as aconn:
                return _snap(aconn, points)
        return _snap(conn, points)
    except Exception:  # noqa: BLE001 -- a missing table or index must not fail the request
        return None
