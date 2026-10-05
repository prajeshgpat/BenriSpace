"""Rail station-to-station ride times from the GTFS feeds (Connection Scan Algorithm).

Which feeds: subway, LIRR, Metro-North, PATH and NJ Transit rail (the rail halves of the
agencies in ingestion/gtfs_transit.py; buses are left out on purpose, their time is dominated
by traffic and they are covered by the walk/drive precompute and the transit-stop counts).

Method, per origin station and per departure time of an AM-peak weekday:
  * every GTFS stop belongs to a station (its parent station, else itself; same-name stops of one
    agency within 300 m merge). Stations within 300 m of each other (Penn Station: LIRR, NJ
    Transit, three subway complexes) are joined by walking links at 3 mph x 1.3 circuity.
  * the timetable becomes a list of "connections" (ride from station A at t to station B at t'),
    sorted by departure. One pass over that list from the departure time gives the earliest
    arrival at every station (CSA). A change of train needs TRANSFER_BUFFER_S.
  * the stored time is the median over DEPARTURES of (arrival - departure), so it includes the
    expected wait for the first train. Nothing reachable inside HORIZON_MIN is stored as -1.

An address trip is then: walk to one of the nearby stations + the stored ride + walk from one
of the stations near the destination (api/routing_data.py).
"""

from __future__ import annotations

import csv
import io
import itertools
import math
import zipfile
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, timedelta

from common.geo import haversine_m
from common.routing import CIRCUITY, WALK_M_PER_MIN

# (agency label, GTFS zip URL)
RAIL_FEEDS: tuple[tuple[str, str], ...] = (
    ("mta_subway", "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"),
    ("lirr", "https://rrgtfsfeeds.s3.amazonaws.com/gtfslirr.zip"),
    ("metro_north", "https://rrgtfsfeeds.s3.amazonaws.com/gtfsmnr.zip"),
    ("path", "https://data.trilliumtransit.com/gtfs/path-nj-us/path-nj-us.zip"),
    ("nj_transit", "https://www.njtransit.com/rail_data.zip"),
)
RAIL_ROUTE_TYPES = {0, 1, 2, 12}  # tram / light rail, subway, rail, monorail

DEPARTURES_S = (7 * 3600 + 45 * 60, 8 * 3600 + 5 * 60, 8 * 3600 + 25 * 60)
HORIZON_MIN = 150
TRANSFER_BUFFER_S = 120
LINK_RADIUS_M = 300.0
MERGE_RADIUS_M = 300.0
INF = 10**9


@dataclass
class Station:
    key: str  # "<agency>:<parent or stop id>"
    name: str
    agency: str
    lat: float
    lon: float
    stop_ids: list[str] = field(default_factory=list)


@dataclass
class Timetable:
    """Station-level connections sorted by departure, plus walking links."""

    stations: list[Station]
    dep: list[int]
    arr: list[int]
    src: list[int]
    dst: list[int]
    trip: list[int]
    n_trips: int
    links: list[list[tuple[int, int]]]  # station -> [(other station, walk seconds)]


def parse_time(value: str) -> int | None:
    """GTFS 'HH:MM:SS' (hours may exceed 23) -> seconds."""
    parts = value.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None


def _rows(zf: zipfile.ZipFile, name: str):
    member = next((n for n in zf.namelist() if n.endswith(name)), None)
    if member is None:
        return
    with zf.open(member) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def active_service_ids(zf: zipfile.ZipFile, day: date) -> set[str]:
    weekday = day.strftime("%A").lower()
    stamp = day.strftime("%Y%m%d")
    active = {
        r["service_id"]
        for r in _rows(zf, "calendar.txt")
        if r.get(weekday) == "1" and r["start_date"] <= stamp <= r["end_date"]
    }
    for r in _rows(zf, "calendar_dates.txt"):
        if r["date"] != stamp:
            continue
        if r["exception_type"] == "1":
            active.add(r["service_id"])
        elif r["exception_type"] == "2":
            active.discard(r["service_id"])
    return active


def choose_service_date(zf: zipfile.ZipFile, today: date | None = None) -> date:
    """The Tuesday nearest to today on which the feed runs a weekday timetable."""
    today = today or date.today()  # noqa: DTZ011
    for offset in range(400):
        for sign in (1, -1):
            day = today + timedelta(days=sign * offset)
            if day.weekday() == 1 and active_service_ids(zf, day):
                return day
    raise ValueError("feed has no weekday service within 400 days")


def merge_stations(stations: list[Station]) -> list[int]:
    """Union-find over same-agency, same-name stations within MERGE_RADIUS_M; returns the
    representative index of each station."""
    parent = list(range(len(stations)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_name: dict[tuple[str, str], list[int]] = {}
    for i, s in enumerate(stations):
        by_name.setdefault((s.agency, s.name.casefold()), []).append(i)
    for group in by_name.values():
        for a in range(len(group)):
            for b in range(a + 1, len(group)):
                sa, sb = stations[group[a]], stations[group[b]]
                if haversine_m(sa.lat, sa.lon, sb.lat, sb.lon) <= MERGE_RADIUS_M:
                    parent[find(group[b])] = find(group[a])
    return [find(i) for i in range(len(stations))]


def walk_seconds(meters: float) -> int:
    return round(meters * CIRCUITY / WALK_M_PER_MIN * 60.0)


def build_links(stations: list[Station]) -> list[list[tuple[int, int]]]:
    """Walking links between stations within LINK_RADIUS_M (grid-bucketed, O(n))."""
    cell = 0.004  # ~440 m
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, s in enumerate(stations):
        buckets.setdefault((math.floor(s.lat / cell), math.floor(s.lon / cell)), []).append(i)
    links: list[list[tuple[int, int]]] = [[] for _ in stations]
    for i, s in enumerate(stations):
        ky, kx = math.floor(s.lat / cell), math.floor(s.lon / cell)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for j in buckets.get((ky + dy, kx + dx), ()):
                    if j == i:
                        continue
                    d = haversine_m(s.lat, s.lon, stations[j].lat, stations[j].lon)
                    if d <= LINK_RADIUS_M:
                        links[i].append((j, walk_seconds(d)))
    return links


def parse_feed(zip_bytes: bytes, agency: str, day: date | None = None):
    """One feed -> (stops, connections) for rail routes on one weekday.

    Returns (stop_info, trips) where stop_info maps stop_id -> (name, lat, lon, parent) and trips
    is a list of [(stop_id, arr_s, dep_s), ...] in stop order."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        day = day or choose_service_date(zf)
        services = active_service_ids(zf, day)
        rail_routes = {
            r["route_id"] for r in _rows(zf, "routes.txt") if int(r["route_type"] or -1) in RAIL_ROUTE_TYPES
        }
        trip_ids = {
            r["trip_id"]
            for r in _rows(zf, "trips.txt")
            if r["route_id"] in rail_routes and r["service_id"] in services
        }
        stop_info = {}
        for r in _rows(zf, "stops.txt"):
            try:
                lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
            except (KeyError, ValueError):
                continue
            stop_info[r["stop_id"]] = (
                (r.get("stop_name") or r["stop_id"]).strip(),
                lat,
                lon,
                (r.get("parent_station") or "").strip(),
            )
        by_trip: dict[str, list[tuple[int, str, int, int]]] = {}
        for r in _rows(zf, "stop_times.txt"):
            tid = r["trip_id"]
            if tid not in trip_ids:
                continue
            arr = parse_time(r["arrival_time"] or r["departure_time"])
            dep = parse_time(r["departure_time"] or r["arrival_time"])
            if arr is None or dep is None:
                continue
            by_trip.setdefault(tid, []).append((int(r["stop_sequence"]), r["stop_id"], arr, dep))
    trips = [[(s, a, d) for _, s, a, d in sorted(v)] for v in by_trip.values()]
    return stop_info, trips


def build_timetable(feeds: list[tuple[str, dict, list]]) -> Timetable:
    """Merge parsed feeds (agency, stop_info, trips) into one station-level timetable."""
    stations: list[Station] = []
    index: dict[tuple[str, str], int] = {}
    # stations from the stops actually served by a rail trip
    for agency, stop_info, trips in feeds:
        used = {s for t in trips for s, _, _ in t}
        for stop_id in sorted(used):
            if stop_id not in stop_info:
                continue
            name, lat, lon, parent = stop_info[stop_id]
            pkey = parent if parent and parent in stop_info else stop_id
            key = f"{agency}:{pkey}"
            if key not in index:
                pname, plat, plon, _ = stop_info.get(pkey, (name, lat, lon, ""))
                index[key] = len(stations)
                stations.append(Station(key, pname, agency, plat, plon))
            stations[index[key]].stop_ids.append(stop_id)
    rep = merge_stations(stations)
    merged: dict[int, int] = {}
    final: list[Station] = []
    for i, s in enumerate(stations):
        r = rep[i]
        if r not in merged:
            merged[r] = len(final)
            final.append(Station(stations[r].key, stations[r].name, stations[r].agency, stations[r].lat, stations[r].lon))
    station_of: dict[tuple[str, str], int] = {}
    for key, i in index.items():
        agency = key.split(":", 1)[0]
        for stop_id in stations[i].stop_ids:
            station_of[(agency, stop_id)] = merged[rep[i]]
    conns = []
    trip_no = 0
    for agency, _, trips in feeds:
        for trip in trips:
            for (s0, _, d0), (s1, a1, _) in itertools.pairwise(trip):
                a, b = station_of.get((agency, s0)), station_of.get((agency, s1))
                if a is None or b is None or a == b or a1 < d0:
                    continue
                conns.append((d0, a1, a, b, trip_no))
            trip_no += 1
    conns.sort()
    return Timetable(
        final,
        [c[0] for c in conns],
        [c[1] for c in conns],
        [c[2] for c in conns],
        [c[3] for c in conns],
        [c[4] for c in conns],
        trip_no,
        build_links(final),
    )


def earliest_arrivals(tt: Timetable, origin: int, t0: int, horizon_s: int) -> list[int]:
    """Connection Scan from `origin` leaving at t0: earliest arrival (seconds) at every station."""
    n = len(tt.stations)
    arr = [INF] * n
    ready = [INF] * n
    arr[origin] = ready[origin] = t0
    for other, w in tt.links[origin]:
        if t0 + w < arr[other]:
            arr[other] = t0 + w
            ready[other] = t0 + w + TRANSFER_BUFFER_S
    boarded = bytearray(tt.n_trips)
    t_end = t0 + horizon_s
    dep, arr_t, src, dst, trip, links = tt.dep, tt.arr, tt.src, tt.dst, tt.trip, tt.links
    for i in range(bisect_left(dep, t0), len(dep)):
        d = dep[i]
        if d > t_end:
            break
        tr = trip[i]
        if boarded[tr] or ready[src[i]] <= d:
            boarded[tr] = 1
            a = arr_t[i]
            s = dst[i]
            if a < arr[s]:
                arr[s] = a
                ready[s] = min(ready[s], a + TRANSFER_BUFFER_S)
                for other, w in links[s]:
                    a2 = a + w
                    if a2 < arr[other]:
                        arr[other] = a2
                        ready[other] = min(ready[other], a2 + TRANSFER_BUFFER_S)
    return arr


def ride_minutes_from(tt: Timetable, origin: int) -> list[float | None]:
    """Median over DEPARTURES_S of (arrival - departure) in minutes; None = not reachable."""
    horizon = HORIZON_MIN * 60
    runs = [earliest_arrivals(tt, origin, t0, horizon) for t0 in DEPARTURES_S]
    out: list[float | None] = []
    for j in range(len(tt.stations)):
        vals = sorted((r[j] - t0) / 60.0 for r, t0 in zip(runs, DEPARTURES_S, strict=True) if r[j] < INF)
        if len(vals) * 2 <= len(DEPARTURES_S):  # reachable in fewer than half the samples
            out.append(None)
        else:
            out.append(vals[len(vals) // 2])
    return out


def fetch_feeds(client=None, day: date | None = None):
    """Download and parse every rail feed. Returns [(agency, stop_info, trips)]."""
    import httpx

    owns = client is None
    client = client or httpx.Client(timeout=120.0, follow_redirects=True)
    try:
        feeds = []
        for agency, url in RAIL_FEEDS:
            resp = client.get(url)
            resp.raise_for_status()
            stop_info, trips = parse_feed(resp.content, agency, day)
            feeds.append((agency, stop_info, trips))
        return feeds
    finally:
        if owns:
            client.close()
