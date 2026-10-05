"""Database reads and writes for the routing precompute (migration 0016).

Writers upsert, so a tile (or the whole job) can be re-run safely. Minutes are deci-minutes in
smallint arrays; see common/routing.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from common.cellgrid import cell_index
from common.routing import CAR_DENSITY_PER_SQ_MI, CATEGORIES


@dataclass(frozen=True)
class Cell:
    geohash: str
    lat: float
    lon: float
    iy: int
    ix: int
    mode: str  # the cell's own travel mode: walk or drive


def travel_mode(stored: str | None, density: float | None) -> str:
    """feature_store.travel_mode, else derived from density, else drive (unknown = sparse)."""
    if stored in ("walk", "drive"):
        return stored
    if density is not None:
        return "drive" if density < CAR_DENSITY_PER_SQ_MI else "walk"
    return "drive"


def read_cells(conn, box: tuple[float, float, float, float]) -> list[Cell]:
    """Cells whose centre is inside box = (south, west, north, east)."""
    south, west, north, east = box
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            select g.geohash, g.latitude, g.longitude, f.travel_mode, f.pop_density_per_sq_mi
            from geo_entities g left join feature_store f on f.geo_entity_id = g.id
            where g.latitude >= %s and g.latitude < %s and g.longitude >= %s and g.longitude < %s
            """,
            (south, north, west, east),
        )
        rows = cur.fetchall()
    cells = []
    for geohash, lat, lon, mode, density in rows:
        iy, ix = cell_index(lat, lon)
        cells.append(Cell(geohash, lat, lon, iy, ix, travel_mode(mode, density)))
    return cells


def read_places(
    conn, box: tuple[float, float, float, float]
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """category -> (lat array, lon array) of places inside box."""
    south, west, north, east = box
    out: dict[str, tuple[list[float], list[float]]] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            select category, latitude, longitude from places
            where category = any(%s) and latitude between %s and %s and longitude between %s and %s
            """,
            (list(CATEGORIES), south, north, west, east),
        )
        for category, lat, lon in cur:
            lats, lons = out.setdefault(category, ([], []))
            lats.append(lat)
            lons.append(lon)
    return {c: (np.array(a), np.array(b)) for c, (a, b) in out.items()}


def cell_bounds_of(conn) -> tuple[float, float, float, float]:
    """(south, west, north, east) of every cell."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("select min(latitude), min(longitude), max(latitude), max(longitude) from geo_entities")
        return cur.fetchone()


def write_cell_travel(conn, cells: list[Cell], minutes: np.ndarray) -> int:
    rows = [(c.geohash, c.mode, [int(v) for v in minutes[i]]) for i, c in enumerate(cells)]
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.executemany(
            """
            insert into cell_travel (geohash, mode, minutes_dm) values (%s, %s, %s::smallint[])
            on conflict (geohash) do update
                set mode = excluded.mode, minutes_dm = excluded.minutes_dm, computed_at = now()
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def write_cell_graph(conn, cells: list[Cell], mode: str, edges: np.ndarray) -> int:
    rows = [
        (c.geohash, mode, c.lat, c.lon, [int(v) for v in edges[i]]) for i, c in enumerate(cells)
    ]
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.executemany(
            """
            insert into cell_graph (geohash, mode, latitude, longitude, edges_dm)
            values (%s, %s, %s, %s, %s::smallint[])
            on conflict (geohash, mode) do update set edges_dm = excluded.edges_dm
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def write_hubs(conn, hubs: list[tuple[int, str, str, str, float, float]]) -> None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.executemany(
            """
            insert into routing_hubs (id, kind, code, name, latitude, longitude)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (id) do update set kind = excluded.kind, code = excluded.code,
                name = excluded.name, latitude = excluded.latitude, longitude = excluded.longitude
            """,
            hubs,
        )
    conn.commit()


def read_hubs(conn, kind: str) -> list[tuple[int, str, str, float, float]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "select id, code, name, latitude, longitude from routing_hubs where kind = %s order by id",
            (kind,),
        )
        return cur.fetchall()


def write_cell_hubs(conn, geohashes: list[str], kind: str, ids: np.ndarray, dm: np.ndarray) -> int:
    rows = []
    for j, g in enumerate(geohashes):
        keep = [s for s in range(ids.shape[1]) if ids[j][s] >= 0 and dm[j][s] >= 0]
        if keep:
            rows.append((g, kind, [int(ids[j][s]) for s in keep], [int(dm[j][s]) for s in keep]))
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.executemany(
            """
            insert into cell_hubs (geohash, kind, hub_ids, minutes_dm)
            values (%s, %s, %s::integer[], %s::smallint[])
            on conflict (geohash, kind) do update
                set hub_ids = excluded.hub_ids, minutes_dm = excluded.minutes_dm
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def write_rail_matrix(conn, origin_ids: list[int], matrix_dm: np.ndarray) -> None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("delete from rail_matrix")
        cur.executemany(
            "insert into rail_matrix (origin_id, minutes_dm) values (%s, %s::smallint[])",
            [(oid, [int(v) for v in matrix_dm[i]]) for i, oid in enumerate(origin_ids)],
        )
    conn.commit()


def write_meta(conn, key: str, value: dict) -> None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            insert into routing_meta (key, value) values (%s, %s)
            on conflict (key) do update set value = excluded.value, computed_at = now()
            """,
            (key, Jsonb(value)),
        )
    conn.commit()
