"""Populates feature_store.transit_stop_count_800m / transit_nearest_m /
transit_agencies from GTFS static feeds.

PROJECT.md's v1 scope note: "This radius spans multiple transit agencies
(MTA, LIRR, Metro-North, NJ Transit)... treat each as a separate ingestion
job, not one unified feed." PHASES.md Phase 1 breaks that into four
checklist items (MTA/LIRR/Metro-North/NJ Transit) and flags that NJ
Transit's feed needs developer credentials the other three don't.

Design calls made here (flag if wrong, easy to change):

- **One shared parser, per-agency config, not four scripts.** The
  "separate ingestion job" language is about independent reliability and
  refresh cadence per agency (one agency's feed breaking shouldn't break
  the others), not about literal code duplication. `AGENCIES` below lists
  one or more GTFS zip URLs per agency (MTA publishes subway and each
  borough's bus network as separate zips, all still "MTA" data); the same
  fetch -> parse -> aggregate pipeline runs once per agency in `run()`.
- **Per-agency failure isolation.** Each agency is fetched and logged to
  `ingestion_runs` independently (source='gtfs_mta' / 'gtfs_lirr' /
  'gtfs_metro_north' / 'gtfs_nj_transit', matching the exact source names
  schema.sql's `ingestion_runs.source` comment lists), inside a try/except
  in `run()`. A failure (e.g. NJ Transit with no API key configured yet)
  is caught, logged as that agency's own 'failed' row, and the loop moves
  on — it does not abort MTA/LIRR/Metro-North. The overall script is also
  wrapped in `ingestion_job("gtfs_transit")` per the shared
  convention every ingestion script uses (see ingestion/grid.py), so
  there's both a per-agency audit trail and a single job-level row; the
  job-level row only fails if *every* agency failed (nothing to write).
- **Download once per agency, compute every cell locally.** ~64,000
  geo_entities rows rules out per-cell network calls. Each agency's
  stops.txt is fetched once into an in-memory list of (lat, lon) tuples;
  every grid cell's count-within-radius and nearest-stop distance are
  computed against that in-memory list with common.geo.haversine_m (an
  O(cells x stops) scan — fine at this scale, no spatial index needed for
  a one-shot batch job).
- **Radius is 800m**, fixed by the feature_store column name
  (`transit_stop_count_800m`) from the Phase 0 contract, not a tunable.
- **transit_agencies is a per-cell "which agency serves the nearest
  stop(s)" list**, not "every agency with any stop in range" — computed
  as every agency whose own nearest-stop distance for that cell ties
  (within a small float epsilon) the overall minimum across agencies.
  Normally exactly one agency; a tie happens when e.g. an LIRR and
  Metro-North station sit at (near-)identical coordinates (Penn
  Station/Grand Central-adjacent cases).
- **NJ Transit is stubbed behind the same AgencyFeed interface**, not
  implemented. `common.config.NJ_TRANSIT_API_KEY` /
  `NJ_TRANSIT_API_USERNAME` are unset (PHASES.md: developer account not
  created yet). `fetch_nj_transit_stops()` raises a clear, descriptive
  RuntimeError so the per-agency try/except logs a legible failure
  instead of a stack trace from a half-guessed auth flow. NJ Transit's
  actual developer API (njtransit.com/developer-tools) is a
  username/password-gated portal, not a plain public zip URL like MTA's,
  so activating it later needs real implementation work (login/token
  exchange, current feed endpoint), not just setting an env var -- do not
  assume it degrades to "just add the key" once credentials exist.
- **OSM transit stops (pseudo-agency 'osm')** fill gaps where a GTFS feed is
  missing (NJ Transit, CT/Westchester/LI buses). See ingestion/osm_transit.py:
  OSM stops within 40 m of any GTFS stop, or same-named within 40 m of each
  other, are dropped so NYC counts are not inflated. Named ones are written
  to places under source 'osmtransit' (separate replace_places call, never
  touching 'osm' POI rows). An Overpass failure is logged and GTFS-only
  results are written.
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from dataclasses import dataclass, field

import httpx

from common.config import NJ_TRANSIT_API_KEY, NJ_TRANSIT_API_USERNAME
from common.db import get_connection, iter_geo_entities, log_ingestion_run, upsert_feature_store
from common.geo import haversine_m
from common.ingestion_log import ingestion_job
from common.places import Place, clean_name, replace_places
from ingestion import osm_transit

RADIUS_M = 800.0
_TIE_EPSILON_M = 1e-6  # float-compare tolerance when picking agencies at the min distance

HTTP_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class AgencyFeed:
    name: str  # e.g. "mta" -- key used in transit_agencies output
    ingestion_source: str  # ingestion_runs.source label, matches schema.sql's comment
    feed_urls: tuple[str, ...] = field(default_factory=tuple)
    requires_auth: bool = False


# Feed URLs verified against mta.info/developers and njtransit.com/developer-tools
# as of 2026-09; these are static-download hosts that can change -- re-verify if
# a run starts failing rather than assuming the parser broke.
AGENCIES: tuple[AgencyFeed, ...] = (
    AgencyFeed(
        name="mta",
        ingestion_source="gtfs_mta",
        feed_urls=(
            "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip",
            "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_bx.zip",
            "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_b.zip",
            "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_m.zip",
            "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_q.zip",
            "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_si.zip",
            "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_busco.zip",
        ),
    ),
    AgencyFeed(
        name="lirr",
        ingestion_source="gtfs_lirr",
        feed_urls=("https://rrgtfsfeeds.s3.amazonaws.com/gtfslirr.zip",),
    ),
    AgencyFeed(
        name="metro_north",
        ingestion_source="gtfs_metro_north",
        feed_urls=("https://rrgtfsfeeds.s3.amazonaws.com/gtfsmnr.zip",),
    ),
    # PATH: public feed hosted by Trillium; verified 2026-10-03 (HTTP 200,
    # application/zip, contains stops.txt, last modified 2025-06-06).
    AgencyFeed(
        name="path",
        ingestion_source="gtfs_path",
        feed_urls=("https://data.trilliumtransit.com/gtfs/path-nj-us/path-nj-us.zip",),
    ),
    AgencyFeed(
        name="nj_transit",
        ingestion_source="gtfs_nj_transit",
        feed_urls=(),
        requires_auth=True,
    ),
)


# ---------------------------------------------------------------------------
# Pure, DB-free parsing/aggregation logic -- unit-tested in
# tests/test_gtfs_transit.py against synthetic in-memory data, no live feed
# download or DB required.
# ---------------------------------------------------------------------------


def parse_stops_txt(csv_text: str) -> list[tuple[float, float]]:
    """Parses a GTFS stops.txt file's contents into a list of (lat, lon)
    tuples. Rows missing/malformed stop_lat or stop_lon are skipped --
    GTFS feeds occasionally have parent-station rows or blank entries."""
    reader = csv.DictReader(io.StringIO(csv_text))
    stops: list[tuple[float, float]] = []
    for row in reader:
        lat_raw, lon_raw = row.get("stop_lat"), row.get("stop_lon")
        if not lat_raw or not lon_raw:
            continue
        try:
            stops.append((float(lat_raw), float(lon_raw)))
        except ValueError:
            continue
    return stops


PLACE_DEDUPE_M = 150.0  # platforms of one station collapse to one place within this


def parse_stops_named(csv_text: str, agency_label: str) -> list[Place]:
    """Named transit stops from a stops.txt as `places` rows. Blank names and
    bad coordinates are skipped; stops with the same cleaned name within
    PLACE_DEDUPE_M collapse to the first one (one station, many platforms)."""
    places: list[Place] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        name = clean_name(row.get("stop_name"))
        stop_id = (row.get("stop_id") or "").strip()
        if name is None or not stop_id:
            continue
        try:
            lat, lon = float(row.get("stop_lat") or ""), float(row.get("stop_lon") or "")
        except ValueError:
            continue
        places.append(
            Place(f"gtfs:{agency_label}", stop_id, "transit", name, lat, lon)
        )
    return dedupe_places(places)


def dedupe_places(places: list[Place]) -> list[Place]:
    """Drops later places sharing a case-insensitive name with an already kept
    one within PLACE_DEDUPE_M."""
    kept: list[Place] = []
    by_name: dict[str, list[Place]] = {}
    for p in places:
        group = by_name.setdefault(p.name.casefold(), [])
        if any(
            haversine_m(p.latitude, p.longitude, q.latitude, q.longitude) <= PLACE_DEDUPE_M
            for q in group
        ):
            continue
        group.append(p)
        kept.append(p)
    return kept


def _stops_text(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        stops_name = next((n for n in zf.namelist() if n.endswith("stops.txt")), None)
        if stops_name is None:
            raise ValueError("stops.txt not found in GTFS feed zip")
        with zf.open(stops_name) as f:
            return f.read().decode("utf-8-sig")


def parse_gtfs_zip_named(zip_bytes: bytes, agency_label: str) -> list[Place]:
    """Like parse_gtfs_zip but returns named `Place` rows."""
    return parse_stops_named(_stops_text(zip_bytes), agency_label)


def parse_gtfs_zip(zip_bytes: bytes) -> list[tuple[float, float]]:
    """Opens a GTFS static feed zip in memory and extracts stop
    coordinates from stops.txt. stdlib zipfile/csv is enough for this --
    no GTFS library needed just to pull one column pair out of one file."""
    return parse_stops_txt(_stops_text(zip_bytes))


def count_and_nearest(
    cell_lat: float, cell_lon: float, stops: list[tuple[float, float]], radius_m: float
) -> tuple[int, float | None]:
    """Count of stops within radius_m of (cell_lat, cell_lon), and the
    nearest stop's distance in meters (None if stops is empty)."""
    count = 0
    nearest: float | None = None
    for lat, lon in stops:
        d = haversine_m(cell_lat, cell_lon, lat, lon)
        if d <= radius_m:
            count += 1
        if nearest is None or d < nearest:
            nearest = d
    return count, nearest


def aggregate_cell(
    cell_lat: float,
    cell_lon: float,
    agency_stops: dict[str, list[tuple[float, float]]],
    radius_m: float = RADIUS_M,
) -> dict:
    """Merges one or more agencies' stop lists into the feature_store
    fields for a single grid cell:
    - transit_stop_count_800m: total stops within radius_m across all agencies
    - transit_nearest_m: distance to the single nearest stop, any agency
    - transit_agencies: agencies whose own nearest stop ties that minimum
    """
    total_count = 0
    nearest_per_agency: dict[str, float] = {}

    for agency, stops in agency_stops.items():
        count, nearest = count_and_nearest(cell_lat, cell_lon, stops, radius_m)
        total_count += count
        if nearest is not None:
            nearest_per_agency[agency] = nearest

    if not nearest_per_agency:
        return {
            "transit_stop_count_800m": 0,
            "transit_nearest_m": None,
            "transit_agencies": [],
        }

    overall_nearest = min(nearest_per_agency.values())
    agencies = sorted(
        agency
        for agency, d in nearest_per_agency.items()
        if abs(d - overall_nearest) <= _TIE_EPSILON_M
    )

    return {
        "transit_stop_count_800m": total_count,
        "transit_nearest_m": round(overall_nearest, 2),
        "transit_agencies": agencies,
    }


# ---------------------------------------------------------------------------
# Network/DB-touching glue
# ---------------------------------------------------------------------------


def fetch_nj_transit_stops() -> list[tuple[float, float]]:
    """Stubbed: NJ Transit's GTFS static feed sits behind a developer
    account (username + password, not a bare API key) at
    njtransit.com/developer-tools, per PHASES.md's Phase 1 "Requirements
    from you". Raises immediately with a descriptive message rather than
    guessing at the login/token/download sequence -- a wrong guess would
    fail more confusingly than an honest "not configured" error, and
    would need to be re-verified against NJT's current docs anyway once
    the credentials actually exist."""
    if not (NJ_TRANSIT_API_KEY and NJ_TRANSIT_API_USERNAME):
        raise RuntimeError(
            "NJ_TRANSIT_API_KEY / NJ_TRANSIT_API_USERNAME not set (see PHASES.md "
            "Phase 1 'Requirements from you' -- NJ Transit developer account not "
            "created yet). NJ Transit ingestion is stubbed until those exist."
        )
    raise NotImplementedError(
        "NJ Transit credentials are set but the login/token-exchange/feed-download "
        "flow against njtransit.com/developer-tools is not implemented yet -- verify "
        "the current API shape against NJT's developer docs and implement here."
    )


def fetch_agency_stops(agency: AgencyFeed, client: httpx.Client | None = None) -> list[tuple[float, float]]:
    """Fetches and parses every feed URL for one agency, returning a
    combined list of (lat, lon) stops. Network calls happen exactly once
    per feed URL here -- never per grid cell."""
    if agency.requires_auth:
        if agency.name == "nj_transit":
            return fetch_nj_transit_stops()
        raise RuntimeError(f"Agency '{agency.name}' requires auth but has no fetch implementation")

    owns_client = client is None
    client = client or httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True)
    try:
        stops: list[tuple[float, float]] = []
        for url in agency.feed_urls:
            resp = client.get(url)
            resp.raise_for_status()
            stops.extend(parse_gtfs_zip(resp.content))
        return stops
    finally:
        if owns_client:
            client.close()


def fetch_agency_stops_and_places(
    agency: AgencyFeed, client: httpx.Client | None = None
) -> tuple[list[tuple[float, float]], list[Place]]:
    """fetch_agency_stops plus the named, deduped places, from one download of
    each feed. NJ Transit (no credentials) raises like fetch_agency_stops."""
    if agency.requires_auth:
        return fetch_agency_stops(agency, client=client), []

    owns_client = client is None
    client = client or httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True)
    try:
        stops: list[tuple[float, float]] = []
        places: list[Place] = []
        for url in agency.feed_urls:
            resp = client.get(url)
            resp.raise_for_status()
            stops.extend(parse_gtfs_zip(resp.content))
            places.extend(parse_gtfs_zip_named(resp.content, agency.name))
        return stops, dedupe_places(places)
    finally:
        if owns_client:
            client.close()


def fetch_osm_stops_isolated() -> list[osm_transit.OsmStop] | None:
    """OSM transit stops, or None (logged) if the Overpass fetch fails, so the
    run continues with GTFS only."""
    run_id = log_ingestion_run("osm_transit", status="running")
    try:
        stops = osm_transit.fetch_all_stops()
    except Exception as exc:  # noqa: BLE001 -- isolate OSM failure from GTFS
        log_ingestion_run("osm_transit", status="failed", error_message=str(exc), run_id=run_id)
        print(f"[gtfs_transit] osm_transit failed: {exc}", file=sys.stderr)
        return None
    log_ingestion_run("osm_transit", status="success", rows_affected=len(stops), run_id=run_id)
    return stops


def merge_osm_into_agency_stops(
    agency_stops: dict[str, list[tuple[float, float]]],
    osm_stops: list[osm_transit.OsmStop],
) -> list[osm_transit.OsmStop]:
    """Dedupes OSM stops against all GTFS stops and each other, adds the
    survivors' coordinates as agency 'osm', and returns the survivors."""
    gtfs_coords = [c for stops in agency_stops.values() for c in stops]
    kept = osm_transit.dedupe_osm_stops(osm_stops, gtfs_coords)
    if kept:
        agency_stops["osm"] = [(s.lat, s.lon) for s in kept]
    return kept


def run() -> None:
    with get_connection() as conn, ingestion_job("gtfs_transit") as ctx:
        agency_stops: dict[str, list[tuple[float, float]]] = {}
        all_places: list[Place] = []

        with httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True) as client:
            for agency in AGENCIES:
                run_id = log_ingestion_run(agency.ingestion_source, status="running")
                try:
                    stops, places = fetch_agency_stops_and_places(agency, client=client)
                except Exception as exc:  # noqa: BLE001 -- isolate one agency's failure
                    log_ingestion_run(
                        agency.ingestion_source,
                        status="failed",
                        error_message=str(exc),
                        run_id=run_id,
                    )
                    print(f"[gtfs_transit] {agency.name} failed: {exc}", file=sys.stderr)
                    continue

                agency_stops[agency.name] = stops
                all_places.extend(places)
                log_ingestion_run(
                    agency.ingestion_source,
                    status="success",
                    rows_affected=len(stops),
                    run_id=run_id,
                )
                print(f"[gtfs_transit] {agency.name}: {len(stops)} stops", file=sys.stderr)

        osm_stops = fetch_osm_stops_isolated()
        if not agency_stops and not osm_stops:
            raise RuntimeError(
                "All agency feeds and OSM transit failed -- nothing to write to feature_store"
            )
        osm_kept = merge_osm_into_agency_stops(agency_stops, osm_stops or [])
        print(
            f"[gtfs_transit] osm: {len(osm_kept)}/{len(osm_stops or [])} stops after dedupe",
            file=sys.stderr,
        )

        rows_updated = 0
        for cell in iter_geo_entities(conn):
            fields = aggregate_cell(cell["latitude"], cell["longitude"], agency_stops, RADIUS_M)
            upsert_feature_store(conn, cell["id"], fields)
            rows_updated += 1
        conn.commit()
        if all_places:
            replace_places(conn, "gtfs", all_places)
        osm_places = osm_transit.stops_to_places(osm_kept)
        if osm_places:
            replace_places(conn, osm_transit.PLACES_SOURCE, osm_places)
        ctx.rows_affected = rows_updated

    print(
        f"gtfs_transit: updated {rows_updated} geo_entities across "
        f"{len(agency_stops)} sources (of {len(AGENCIES)} GTFS agencies + osm) "
        f"({', '.join(sorted(agency_stops)) or 'none'})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    run()
