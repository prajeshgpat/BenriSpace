"""Slim storage for road-bounded areas (`areas_slim`, migration 0014_areas_slim.sql).

One geometry column (PostGIS MultiPolygon, coordinates on a ~1e-5 degree grid and
lightly simplified), a few scalar attributes and the neighbourhood label. No jsonb
copy of the geometry and no area_cells: polygon scores come from on-demand point
sampling (api/point_score.py). Meant for a database that must stay under the free
500 MB limit.

The writer targets AREAS_DATABASE_URL (a local PostGIS container while testing) and
refuses to run without it, so it can never fall through to the production
DATABASE_URL by accident.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable

import shapely
from shapely.geometry import MultiPolygon
from shapely.geometry.base import BaseGeometry

from ingestion.areas.limits import M_PER_MI, SQ_M_PER_SQ_MI

GRID_DEG = 1e-5  # ~1.1 m of latitude
SIMPLIFY_DEG = 1e-5  # ~3.6 ft; Douglas-Peucker, topology preserving
AREAS_DATABASE_URL_ENV = "AREAS_DATABASE_URL"

INSERT_SLIM_SQL = (
    "insert into areas_slim (id, build_version, metro_area, geom, area_sq_mi, extent_mi, "
    "compactness, bounded_by, neighborhood) "
    "values (%s, %s, %s, st_setsrid(st_geomfromwkb(%s), 4326), %s, %s, %s, %s, %s)"
)


PROD_SIMPLIFY_DEG = 3e-5  # ~3 m: what the production copy keeps (scripts/copy_areas_slim.py)


def simplified_select_sql(tolerance_deg: float = PROD_SIMPLIFY_DEG) -> str:
    """SELECT of every areas_slim row, columns in INSERT_SLIM_SQL parameter order, with the
    geometry (WKB) simplified, snapped to GRID_DEG and made a valid MultiPolygon. A shape
    that collapses to nothing (a sub-metre sliver) keeps its original geometry."""
    shape = f"st_reduceprecision(st_simplifypreservetopology(geom, {tolerance_deg}), {GRID_DEG})"
    polygons = "st_multi(st_collectionextract(st_makevalid({}), 3))"
    return (
        "select id, build_version, metro_area, "
        f"st_asbinary(case when st_isempty({polygons.format(shape)}) "
        f"then {polygons.format('geom')} else {polygons.format(shape)} end), "
        "area_sq_mi, extent_mi, compactness, bounded_by, neighborhood "
        "from areas_slim order by id"
    )


def slim_geometry(
    geom: BaseGeometry, simplify_deg: float = SIMPLIFY_DEG, grid_deg: float = GRID_DEG
) -> MultiPolygon:
    """Lightly simplified, grid-snapped MultiPolygon (valid, polygons only). Falls
    back to the unsimplified shape if simplifying would empty or invalidate it."""
    cleaned = shapely.make_valid(geom) if not geom.is_valid else geom
    out = shapely.set_precision(cleaned.simplify(simplify_deg, preserve_topology=True), grid_deg)
    if out.is_empty or not out.is_valid:
        out = shapely.set_precision(cleaned, grid_deg)
    polys = [
        p
        for part in getattr(out, "geoms", [out])
        for p in (part.geoms if part.geom_type == "MultiPolygon" else [part])
        if p.geom_type == "Polygon" and not p.is_empty
    ]
    return MultiPolygon(polys)


def slim_row(
    i: int,
    face,
    build_version: str,
    metro_area: str | None,
    neighborhood: str | None,
) -> tuple:
    """One INSERT_SLIM_SQL parameter tuple for a numbered Face."""
    geom = slim_geometry(face.geometry)
    return (
        i,
        build_version,
        metro_area,
        shapely.to_wkb(geom),
        face.area_sq_m / SQ_M_PER_SQ_MI,
        None if face.extent_m is None else face.extent_m / M_PER_MI,
        face.compactness,
        list(face.bounded_by),
        neighborhood,
    )


def label_faces(
    numbered: Iterable[tuple[int, object]], labeler: Callable[[float, float], str | None]
) -> dict[int, str | None]:
    """{area id: label} from labeler(lat, lon) at each face's representative point."""
    out: dict[int, str | None] = {}
    for i, f in numbered:
        pt = f.geometry.representative_point()
        out[i] = labeler(pt.y, pt.x)
    return out


def areas_database_url() -> str:
    url = os.environ.get(AREAS_DATABASE_URL_ENV, "").strip()
    if not url:
        raise SystemExit(
            f"{AREAS_DATABASE_URL_ENV} is not set; refusing to write areas_slim "
            "(it never falls back to DATABASE_URL)."
        )
    return url


def write_areas_slim(
    conn,
    numbered,
    build_version: str,
    metro_of: Callable[[object], str | None],
    labels: dict[int, str | None] | None = None,
) -> dict:
    """Replaces areas_slim in ONE transaction. Refuses an empty build."""
    if not numbered:
        raise ValueError("refusing to replace areas_slim with an empty build")
    labels = labels or {}
    rows = [slim_row(i, f, build_version, metro_of(f), labels.get(i)) for i, f in numbered]
    try:
        with conn.cursor() as cur:
            cur.execute("delete from areas_slim")
            cur.executemany(INSERT_SLIM_SQL, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"areas_slim": len(rows)}


def table_sizes(conn) -> dict:
    """Exact on-disk size of areas_slim (heap + TOAST), its indexes and per-row figures."""
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) as n, "
            "pg_table_size('areas_slim') as table_bytes, "
            "pg_indexes_size('areas_slim') as index_bytes, "
            "pg_total_relation_size('areas_slim') as total_bytes, "
            "coalesce(sum(st_npoints(geom)), 0) as vertices, "
            "coalesce(sum(pg_column_size(geom)), 0) as geom_bytes "
            "from areas_slim"
        )
        r = dict(cur.fetchone())
    n = max(int(r["n"]), 1)
    r["bytes_per_area"] = r["total_bytes"] / n
    r["vertices_per_area"] = r["vertices"] / n
    return r
