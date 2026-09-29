"""Populates feature_store's school_count_1600m / school_nearest_m /
school_avg_rating_1600m columns.

PROJECT.md's v1 scope spans multiple counties' school data sources, and
PHASES.md is explicit that each county is "a separate source, not a unified
feed" — so this module is built around a small `SchoolDataSource` plugin
interface (`fetch() -> list[SchoolRecord]`) rather than one big scraper.
Each source is responsible for its own API shape; this module only knows
how to merge already-parsed `SchoolRecord`s and aggregate them per grid
cell. Dropping in a new county later means writing one more
`SchoolDataSource` subclass, not touching the aggregation code.

Design calls made here (flag if wrong, easy to change):

- **Verified data sources, not guessed ones.** NYC Open Data dataset IDs
  drift over time (old blog posts/answers reference dead ids). Both URLs
  below were hit directly against the live Socrata API during development
  (2026-09-28) and confirmed to return the expected fields — see the
  comments on each source for what was checked.
- **School locations**: "2019 - 2020 School Locations"
  (data.cityofnewyork.us/resource/wg9x-4ke6) rather than "School Point
  Locations" (jfju-ynrr), which looks like the canonical name but is
  actually a zipped ESRI shapefile blob, not a queryable tabular resource
  (confirmed: it 403s/"no row or column access to non-tabular tables" on
  the Socrata JSON endpoint). wg9x-4ke6 is a real tabular resource with
  lat/lon + DBN + open/closed status, and is DOE's most recent dataset in
  that per-year series that's actually queryable this way.
- **Rating metric: DOE "Average Student Attendance"**, 0.0-1.0 fraction of
  possible instructional days attended, from the "School Quality Reports
  Data" resource (dnpx-dfnc), most recent report_year available (2025).
  Chosen over Regents/graduation-rate metrics in the same dataset because
  those are high-school-only (hundreds of `mean_score_*`/`grad_pct_*`
  variables); attendance is the one metric reported uniformly across
  elementary/middle/high schools under three variable names
  (`attendance_k3_all`, `attendance_k8_all`, `attendance_hs_all`) that all
  share the same "Average Student Attendance" display name and 0-1 scale.
  It's an imperfect proxy for "school quality" (a school can have high
  attendance and mediocre academics) but it's the only metric this source
  reports consistently across all grade bands without picking a single
  school type to favor.
- **`school_avg_rating_1600m` scale: 0-10.** Computed as
  `attendance_fraction * 10`, so a school with 90% attendance contributes
  9.0. This is NOT the same scale as GreatSchools' 1-10 rating or DOE's old
  1-4 "Framework for Great Schools" — it's a locally-defined transform of
  a locally-chosen metric. Per contracts/normalization.md and
  scoring/engine.py, the scoring engine min-max normalizes this column
  per-metro-cohort regardless of what scale it arrives in, so the absolute
  scale only matters for this docstring/comment, not for correctness
  downstream.
- **Bulk-fetch once, aggregate locally.** Both NYC Open Data sources are
  fetched in full (paginated, ~1-2k rows each) exactly once per run, then
  merged into an in-memory list of `SchoolRecord`. Per-cell aggregation
  against ~64k geo_entities never makes a network call — it walks a
  coarse in-memory spatial index (`build_spatial_index`) instead of
  scanning every school for every cell.
- **Spatial index bucket size (`LAT_BUCKET_DEG`/`LON_BUCKET_DEG`)** is
  chosen so a cell only needs to check its own bucket + the 8 neighbors
  (a 3x3 block) to find every school within `SCHOOL_RADIUS_M` (1600m) —
  each bucket's meter span is >= the radius in both dimensions (using
  40.49-42.00N, the v1 latitude range, for the longitude conversion), so a
  school within range can never land more than one bucket away. Nearest-
  school distance is also drawn only from that 3x3 block: a true nearest
  school more than ~1 bucket away (~3km+) could be missed. That's an
  accepted simplification — dense-school NYC/inner-suburb cells (where
  this data actually exists yet) are never affected, and sparser cells
  with no county source wired in yet correctly report no data rather than
  a fabricated distance.
- **Only NYC Open Data is fully wired up.** Nassau/Suffolk (Long Island)
  and Westchester are stubbed behind the same `SchoolDataSource` interface
  with `# TODO: verify current dataset URL` — see the class docstrings for
  what was found but not verified/integrated. Northern NJ and Fairfield
  County CT have no source at all yet. Cells outside NYC will report
  school_count_1600m=0 / nulls until those sources are filled in, which is
  an accurate "no data yet" signal, not a bug.
"""

import math
import sys
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from common.db import get_connection, iter_geo_entities, upsert_feature_store
from common.geo import haversine_m
from common.ingestion_log import ingestion_job

REQUEST_TIMEOUT_S = 30
PAGE_SIZE = 1000
USER_AGENT = "BenriSpace-ingestion/1.0 (+https://benrispace.com)"

# See module docstring: attendance_fraction * RATING_SCALE_MAX -> 0-10.
RATING_SCALE_MAX = 10.0

SCHOOL_RADIUS_M = 1600.0

# Bucket sizes for the spatial index — see module docstring for why these
# are safe for a 1600m radius across the v1 metro's latitude range.
LAT_BUCKET_DEG = 0.015
LON_BUCKET_DEG = 0.02


@dataclass(frozen=True)
class SchoolRecord:
    """One school, already parsed out of a source's native format."""

    lat: float
    lon: float
    rating: float | None  # 0-10, see module docstring; None if unknown
    name: str
    source: str


class SchoolDataSource(ABC):
    """One school data source, treated as its own ingestion input per
    PHASES.md ("treat each county as a separate source, not a unified
    feed"). `fetch()` must do exactly one bulk pull (however many HTTP
    requests that takes) and return every school it knows about — never
    called per grid cell."""

    name: str

    @abstractmethod
    def fetch(self) -> list[SchoolRecord]:
        raise NotImplementedError


def _paginate(client: httpx.Client, url: str, params: dict) -> list[dict]:
    """Walks a Socrata (SODA) resource with $limit/$offset until a short
    page signals the end. Used by both NYC Open Data queries below."""
    rows: list[dict] = []
    offset = 0
    while True:
        page_params = {**params, "$limit": PAGE_SIZE, "$offset": offset}
        resp = client.get(url, params=page_params, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def parse_location_row(row: dict) -> tuple[str, float, float, str] | None:
    """Parses one row of NYC Open Data's "2019 - 2020 School Locations"
    (wg9x-4ke6). Returns (dbn, lat, lon, name), or None to skip a closed
    school or a row with unusable coordinates."""
    if row.get("status_descriptions") != "Open":
        return None
    dbn = row.get("system_code")
    lat, lon = row.get("latitude"), row.get("longitude")
    if not dbn or lat is None or lon is None:
        return None
    try:
        return str(dbn), float(lat), float(lon), row.get("location_name") or ""
    except (TypeError, ValueError):
        return None


def parse_rating_row(row: dict) -> tuple[str, float] | None:
    """Parses one row of NYC Open Data's "School Quality Reports Data"
    (dnpx-dfnc), already filtered by the caller to the attendance metrics
    and a single report_year. Returns (dbn, rating_0_10), or None if the
    row has no usable dbn/metric_value."""
    dbn = row.get("dbn")
    value = row.get("metric_value")
    if not dbn or value is None:
        return None
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return None
    return str(dbn), fraction * RATING_SCALE_MAX


def merge_school_records(
    location_rows: Iterable[dict], rating_rows: Iterable[dict], source: str
) -> list[SchoolRecord]:
    """Joins parsed location rows to parsed rating rows by DBN. A school
    with no matching rating row still gets a SchoolRecord (rating=None) —
    missing quality data shouldn't drop a school from the count/nearest
    calculation, only from the rating average."""
    ratings_by_dbn: dict[str, float] = {}
    for row in rating_rows:
        parsed = parse_rating_row(row)
        if parsed is not None:
            ratings_by_dbn[parsed[0]] = parsed[1]

    records: list[SchoolRecord] = []
    for row in location_rows:
        parsed = parse_location_row(row)
        if parsed is None:
            continue
        dbn, lat, lon, name = parsed
        records.append(
            SchoolRecord(
                lat=lat, lon=lon, rating=ratings_by_dbn.get(dbn), name=name, source=source
            )
        )
    return records


class NYCOpenDataSchoolSource(SchoolDataSource):
    """The fully-working source. Fetches every open NYC public school's
    location plus its most recent "Average Student Attendance" rating.
    Both dataset ids were confirmed live against the Socrata JSON API on
    2026-09-28 — see the module docstring for what was checked."""

    name = "nyc_open_data"

    LOCATIONS_URL = "https://data.cityofnewyork.us/resource/wg9x-4ke6.json"
    QUALITY_URL = "https://data.cityofnewyork.us/resource/dnpx-dfnc.json"

    # "Average Student Attendance" under its three grade-band variable
    # names (K-3/K-8/high school) — confirmed via $group query to share the
    # same display name and 0-1 scale across all school_type values.
    ATTENDANCE_METRICS = ("attendance_k3_all", "attendance_k8_all", "attendance_hs_all")
    # Most recent report_year with attendance data as of 2026-09-28
    # (confirmed via $group on report_year; 1841 matching rows for 2025).
    REPORT_YEAR = "2025"

    def fetch(self) -> list[SchoolRecord]:
        with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
            location_rows = _paginate(
                client,
                self.LOCATIONS_URL,
                {
                    "$select": "system_code,location_name,latitude,longitude,status_descriptions",
                },
            )
            metric_filter = " or ".join(
                f"metric_variable_name='{m}'" for m in self.ATTENDANCE_METRICS
            )
            rating_rows = _paginate(
                client,
                self.QUALITY_URL,
                {
                    "$select": "dbn,metric_value,metric_variable_name",
                    "$where": f"report_year='{self.REPORT_YEAR}' and ({metric_filter})",
                },
            )
        return merge_school_records(location_rows, rating_rows, source=self.name)


class NassauSuffolkSchoolSource(SchoolDataSource):
    """Long Island (Nassau + Suffolk counties) — stubbed, not wired up.

    Found during research but not verified end-to-end:
    - Suffolk County Open Data (ArcGIS Hub, opendata.suffolkcountyny.gov)
      publishes a "School Polygon" layer queryable via the standard Esri
      FeatureServer/query REST API (returns GeoJSON, not Socrata SODA) —
      polygons, not points, would need a centroid computed per school, and
      it's a location-only layer with no quality/rating attribute.
    - Nassau County's GIS portal exists but a school-specific layer wasn't
      confirmed.
    Neither dataset was fetched live to confirm current field names or
    that the endpoints are actually queryable the way NYC's are.
    # TODO: verify current dataset URL and field names before wiring up.
    """

    name = "nassau_suffolk"

    def fetch(self) -> list[SchoolRecord]:
        raise NotImplementedError(
            "NassauSuffolkSchoolSource is a stub — see class docstring for "
            "what was found but not verified."
        )


class WestchesterSchoolSource(SchoolDataSource):
    """Westchester County — stubbed, not wired up.

    Found during research but not verified end-to-end: Westchester
    GeoHub (gis.westchestergov.com / gis.westchestercountyny.gov)
    publishes a "Public Schools" layer (~253 records) via the standard
    Esri FeatureServer/query REST API — location-only, no quality/rating
    attribute, and the endpoint wasn't fetched live to confirm field names.
    # TODO: verify current dataset URL and field names before wiring up.
    """

    name = "westchester"

    def fetch(self) -> list[SchoolRecord]:
        raise NotImplementedError(
            "WestchesterSchoolSource is a stub — see class docstring for "
            "what was found but not verified."
        )


# Sources tried in order; a source that raises NotImplementedError (stubs
# above) is logged and skipped rather than failing the whole run — a
# partially-covered metro is the expected state until every county source
# is wired up, not an error condition.
SOURCES: list[SchoolDataSource] = [
    NYCOpenDataSchoolSource(),
    NassauSuffolkSchoolSource(),
    WestchesterSchoolSource(),
]


def fetch_all_schools(sources: list[SchoolDataSource] = SOURCES) -> list[SchoolRecord]:
    all_schools: list[SchoolRecord] = []
    for source in sources:
        try:
            records = source.fetch()
        except NotImplementedError as exc:
            print(f"[schools] skipping source '{source.name}': {exc}", file=sys.stderr)
            continue
        print(f"[schools] {source.name}: fetched {len(records)} schools", file=sys.stderr)
        all_schools.extend(records)
    return all_schools


def _bucket_key(lat: float, lon: float) -> tuple[int, int]:
    return (math.floor(lat / LAT_BUCKET_DEG), math.floor(lon / LON_BUCKET_DEG))


def build_spatial_index(
    schools: Iterable[SchoolRecord],
) -> dict[tuple[int, int], list[SchoolRecord]]:
    """Buckets schools into a coarse lat/lon grid so per-cell aggregation
    doesn't have to scan every school for every one of ~64k geo_entities.
    See module docstring for why a 3x3 block of these buckets is enough to
    find everything within SCHOOL_RADIUS_M."""
    index: dict[tuple[int, int], list[SchoolRecord]] = defaultdict(list)
    for school in schools:
        index[_bucket_key(school.lat, school.lon)].append(school)
    return index


def _candidate_schools(
    index: dict[tuple[int, int], list[SchoolRecord]], lat: float, lon: float
) -> list[SchoolRecord]:
    bi, bj = _bucket_key(lat, lon)
    candidates: list[SchoolRecord] = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            candidates.extend(index.get((bi + di, bj + dj), ()))
    return candidates


def compute_cell_aggregate(
    lat: float,
    lon: float,
    index: dict[tuple[int, int], list[SchoolRecord]],
    radius_m: float = SCHOOL_RADIUS_M,
) -> dict:
    """Pure, DB-free aggregation for one grid cell: count of schools within
    radius_m, distance to the nearest school (see module docstring for the
    3x3-bucket bound on this), and the average rating among in-radius
    schools that have one. Returns None for nearest/avg_rating when there's
    no candidate data at all, rather than fabricating a value."""
    nearest_m: float | None = None
    count = 0
    ratings: list[float] = []

    for school in _candidate_schools(index, lat, lon):
        distance = haversine_m(lat, lon, school.lat, school.lon)
        if nearest_m is None or distance < nearest_m:
            nearest_m = distance
        if distance <= radius_m:
            count += 1
            if school.rating is not None:
                ratings.append(school.rating)

    return {
        "school_count_1600m": count,
        "school_nearest_m": round(nearest_m, 1) if nearest_m is not None else None,
        "school_avg_rating_1600m": round(sum(ratings) / len(ratings), 3) if ratings else None,
    }


def run() -> None:
    all_schools = fetch_all_schools()
    index = build_spatial_index(all_schools)

    with get_connection() as conn, ingestion_job("schools") as ctx:
        rows_updated = 0
        for entity in iter_geo_entities(conn):
            aggregate = compute_cell_aggregate(
                entity["latitude"], entity["longitude"], index
            )
            upsert_feature_store(conn, entity["id"], aggregate)
            rows_updated += 1
        conn.commit()
        ctx.rows_affected = rows_updated

    print(
        f"[schools] updated feature_store for {rows_updated} geo_entities "
        f"from {len(all_schools)} school records.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    run()
