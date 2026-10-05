"""Reads of the precomputed routing tables (migration 0022) for the API.

Every function tolerates the tables being absent or empty (migration not applied, region not
yet computed) by returning "nothing" so callers fall back to straight-line estimates.
"""

from __future__ import annotations

import logging
import math
import time

from api.isochrone import Graph
from common.cellgrid import cell_index
from common.geo import haversine_m
from common.routing import CIRCUITY, WALK_M_PER_MIN, category_slot, from_dm

log = logging.getLogger(__name__)

# Straight-line miles per minute the box fetch assumes at most, so the loaded graph always
# contains everything the Dijkstra could reach.
MAX_MI_PER_MIN = {"walk": 0.05, "drive": 0.7}
WALK_ACCESS_MAX_MIN = 20.0  # longest walk to or from a station
STATION_CANDIDATES = 6  # stations tried at each end of a rail trip
STATION_SEARCH_MI = 1.5

_hubs_cache: dict[str, tuple[float, list[tuple]]] = {}
HUBS_TTL_S = 3600.0


def graph_box(lat: float, lon: float, minutes: float, mode: str) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lon, max_lon) around the origin that the search can reach."""
    miles = minutes * MAX_MI_PER_MIN[mode]
    d_lat = miles / 69.0
    d_lon = d_lat / max(0.05, math.cos(math.radians(lat)))
    return lat - d_lat, lat + d_lat, lon - d_lon, lon + d_lon


def load_graph(conn, mode: str, box: tuple[float, float, float, float]) -> Graph:
    min_lat, max_lat, min_lon, max_lon = box
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select latitude, longitude, edges_dm from cell_graph where mode = %s"
                " and latitude between %s and %s and longitude between %s and %s",
                (mode, min_lat, max_lat, min_lon, max_lon),
            )
            rows = cur.fetchall()
    except Exception:
        log.warning("cell_graph unavailable", exc_info=True)
        _rollback(conn)
        return {}
    graph: Graph = {}
    for row in rows:
        lat, lon, edges = (row["latitude"], row["longitude"], row["edges_dm"]) if isinstance(
            row, dict
        ) else row
        graph[cell_index(lat, lon)] = list(edges)
    return graph


def _rollback(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        log.debug("rollback failed", exc_info=True)


def rail_stations(conn) -> list[tuple[int, str, float, float]]:
    """(id, name, lat, lon) of every rail station, id order (matrix column order). Cached."""
    cached = _hubs_cache.get("rail")
    if cached and time.monotonic() - cached[0] < HUBS_TTL_S:
        return cached[1]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select id, name, latitude, longitude from routing_hubs"
                " where kind = 'rail' order by id"
            )
            rows = [
                (r["id"], r["name"], r["latitude"], r["longitude"]) if isinstance(r, dict) else tuple(r)
                for r in cur.fetchall()
            ]
    except Exception:
        log.warning("routing_hubs unavailable", exc_info=True)
        _rollback(conn)
        return []
    _hubs_cache["rail"] = (time.monotonic(), rows)
    return rows


def clear_cache() -> None:
    _hubs_cache.clear()


def nearby_stations(
    stations: list[tuple[int, str, float, float]], lat: float, lon: float
) -> list[tuple[int, int, float]]:
    """[(column index, station id, walk minutes)] for the closest stations within
    STATION_SEARCH_MI, walk = straight line x 1.3 at 3 mph."""
    out = []
    for col, (sid, _name, slat, slon) in enumerate(stations):
        if abs(slat - lat) > 0.03 or abs(slon - lon) > 0.04:
            continue
        d = haversine_m(lat, lon, slat, slon)
        if d <= STATION_SEARCH_MI * 1609.344:
            out.append((col, sid, d * CIRCUITY / WALK_M_PER_MIN))
    out.sort(key=lambda t: t[2])
    return out[:STATION_CANDIDATES]


def rail_rows(conn, origin_ids: list[int]) -> dict[int, list[int]]:
    """origin station id -> deci-minute ride row (aligned with rail_stations order)."""
    if not origin_ids:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select origin_id, minutes_dm from rail_matrix where origin_id = any(%s)",
                (origin_ids,),
            )
            return {
                (r["origin_id"] if isinstance(r, dict) else r[0]): list(
                    r["minutes_dm"] if isinstance(r, dict) else r[1]
                )
                for r in cur.fetchall()
            }
    except Exception:
        log.warning("rail_matrix unavailable", exc_info=True)
        _rollback(conn)
        return {}


def rail_trip_minutes(
    conn, origin: tuple[float, float], dest: tuple[float, float]
) -> tuple[float, str] | None:
    """Door-to-door train trip: walk to a nearby station + precomputed ride + walk from a station
    near the destination. Returns (minutes, "Station A to Station B") or None when no rail
    option exists within STATION_SEARCH_MI of both ends."""
    stations = rail_stations(conn)
    if not stations:
        return None
    near_a = nearby_stations(stations, *origin)
    near_b = nearby_stations(stations, *dest)
    if not near_a or not near_b:
        return None
    rows = rail_rows(conn, [sid for _, sid, _ in near_a])
    best: tuple[float, str] | None = None
    for col_a, sid_a, walk_a in near_a:
        row = rows.get(sid_a)
        if row is None:
            continue
        for col_b, _sid_b, walk_b in near_b:
            ride = from_dm(row[col_b]) if col_b < len(row) else None
            if ride is None or col_a == col_b:
                continue
            total = walk_a + ride + walk_b
            if best is None or total < best[0]:
                best = (total, f"{stations[col_a][1]} to {stations[col_b][1]}")
    return best


def travel_slots(conn, geohashes: list[str], category: str, k: int = 1) -> dict[str, tuple[str, float]]:
    """geohash -> (mode, minutes to the k-th nearest place of `category`) from cell_travel."""
    if not geohashes:
        return {}
    slot = category_slot(category, k) + 1  # SQL arrays are 1-based
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select geohash, mode, minutes_dm[%s] as dm from cell_travel"
                " where geohash = any(%s)",
                (slot, geohashes),
            )
            rows = cur.fetchall()
    except Exception:
        log.warning("cell_travel unavailable", exc_info=True)
        _rollback(conn)
        return {}
    out = {}
    for r in rows:
        g, mode, dm = (r["geohash"], r["mode"], r["dm"]) if isinstance(r, dict) else r
        minutes = from_dm(dm)
        if minutes is not None:
            out[g] = (mode, minutes)
    return out


def hub_minutes(conn, geohashes: list[str], kind: str) -> dict[str, tuple[int, float]]:
    """geohash -> (nearest hub id, drive minutes) from cell_hubs."""
    if not geohashes:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select geohash, hub_ids[1] as hub, minutes_dm[1] as dm from cell_hubs"
                " where kind = %s and geohash = any(%s)",
                (kind, geohashes),
            )
            rows = cur.fetchall()
    except Exception:
        log.warning("cell_hubs unavailable", exc_info=True)
        _rollback(conn)
        return {}
    out = {}
    for r in rows:
        g, hub, dm = (r["geohash"], r["hub"], r["dm"]) if isinstance(r, dict) else r
        minutes = from_dm(dm)
        if minutes is not None and hub is not None:
            out[g] = (hub, minutes)
    return out


def rail_trips(
    conn, origins: list[tuple[float, float]], dest: tuple[float, float]
) -> list[float | None]:
    """rail_trip_minutes for many origins to one destination with one matrix query."""
    stations = rail_stations(conn)
    if not stations:
        return [None] * len(origins)
    near_b = nearby_stations(stations, *dest)
    near_a = [nearby_stations(stations, *o) for o in origins]
    ids = sorted({sid for group in near_a for _, sid, _ in group})
    rows = rail_rows(conn, ids) if near_b else {}
    out: list[float | None] = []
    for group in near_a:
        best = None
        for col_a, sid_a, walk_a in group:
            row = rows.get(sid_a)
            if row is None:
                continue
            for col_b, _sid_b, walk_b in near_b:
                ride = from_dm(row[col_b]) if col_b < len(row) else None
                if ride is None or col_a == col_b:
                    continue
                total = walk_a + ride + walk_b
                if best is None or total < best:
                    best = total
        out.append(best)
    return out


def airport_targets(conn) -> list[tuple[str, float, float]]:
    try:
        with conn.cursor() as cur:
            cur.execute("select code, name, latitude, longitude from routing_hubs where kind = 'airport'")
            rows = cur.fetchall()
    except Exception:
        log.warning("routing_hubs unavailable", exc_info=True)
        _rollback(conn)
        return []
    return [
        (f"{r['name']} ({r['code']})", r["latitude"], r["longitude"])
        if isinstance(r, dict)
        else (f"{r[1]} ({r[0]})", r[2], r[3])
        for r in rows
    ]
