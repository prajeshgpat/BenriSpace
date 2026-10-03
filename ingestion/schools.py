"""Populates feature_store's school columns for the whole NY/NJ/CT metro.

v2 sources (see docs/data-sources.md for licences and the decision record):

- Locations: NCES EDGE public school locations (federal, public domain),
  filtered to NY/NJ/CT and the metro bounding box. Gives
  school_count_1600m / school_nearest_m for every cell in the metro.
- Rating: NOT per school. Each cell centre is assigned to its school district
  (NCES/Census boundaries, point-in-polygon; no match -> NULL, never nearest)
  and gets that district's rating: mean math/reading percent proficient from
  EDFacts (via the Urban Institute Education Data Portal), converted to a
  0-100 percentile WITHIN ITS STATE so NY/NJ/CT are comparable (each state
  uses its own test). Written to school_district_rating, mirrored into
  school_avg_rating_1600m (the column scoring.engine reads as the rating),
  with school_district_geoid/name and school_rating_source.
- A cell with no district or an unrated district gets a NULL rating, so the
  engine yields a NULL school score (never 0, never fabricated).

We link to GreatSchools; we do not ingest or scrape it.
"""

import math
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from common.db import get_connection, iter_geo_entities, upsert_feature_store
from common.geo import haversine_m
from common.ingestion_log import ingestion_job

NCES_LOCATIONS_URL = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICSCH_2425.zip"
METRO_STATES = {"NY": "36", "NJ": "34", "CT": "09"}
# lat_min, lat_max, lon_min, lon_max around the v1 metro.
METRO_BBOX = (40.3, 42.2, -75.6, -71.6)

SCHOOL_RADIUS_M = 1600.0

# Bucket sizes for the spatial index: a 3x3 block of buckets always contains
# every school within SCHOOL_RADIUS_M across the v1 latitude range.
LAT_BUCKET_DEG = 0.015
LON_BUCKET_DEG = 0.02


@dataclass(frozen=True)
class SchoolRecord:
    lat: float
    lon: float
    name: str
    source: str


def parse_nces_row(attrs: dict, source: str = "nces_edge") -> SchoolRecord | None:
    """One EDGE public-school record (fields LAT, LON, NAME, STATE) -> record,
    or None when it is outside NY/NJ/CT, outside the metro bbox, or lacks
    usable coordinates."""
    state = str(attrs.get("STATE") or "").strip().upper()
    if state not in METRO_STATES and state not in METRO_STATES.values():
        return None
    try:
        lat, lon = float(attrs["LAT"]), float(attrs["LON"])
    except (KeyError, TypeError, ValueError):
        return None
    lat_min, lat_max, lon_min, lon_max = METRO_BBOX
    if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
        return None
    return SchoolRecord(lat=lat, lon=lon, name=str(attrs.get("NAME") or ""), source=source)


def _unwrap_shapefile_zip(path: Path) -> Path:
    """The EDGE download is a zip holding Shapefile_SCH.zip (plus xlsx/txt);
    extracts the inner shapefile zip next to it once and returns its path."""
    import zipfile

    with zipfile.ZipFile(path) as zf:
        inner = [
            n for n in zf.namelist() if n.lower().startswith("shapefile") and n.endswith(".zip")
        ]
        if not inner:
            return path
        dest = path.with_name(Path(inner[0]).name)
        if not dest.exists():
            dest.write_bytes(zf.read(inner[0]))
        return dest


def load_nces_schools(path: Path) -> list[SchoolRecord]:
    from ingestion.school_districts import read_shapefile

    path = _unwrap_shapefile_zip(path)
    records = (parse_nces_row(attrs) for attrs, _ in read_shapefile(path))
    return [r for r in records if r is not None]


def fetch_all_schools() -> list[SchoolRecord]:
    from ingestion.school_districts import download_cached

    schools = load_nces_schools(download_cached(NCES_LOCATIONS_URL))
    print(f"[schools] nces_edge: {len(schools)} metro schools", file=sys.stderr)
    return schools


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
    """Pure, DB-free proximity part for one grid cell: schools within radius_m
    and distance to the nearest one (searched in the 3x3 bucket block only, so
    None means none within ~3 km, not a fabricated distance)."""
    nearest_m: float | None = None
    count = 0
    for school in _candidate_schools(index, lat, lon):
        distance = haversine_m(lat, lon, school.lat, school.lon)
        if nearest_m is None or distance < nearest_m:
            nearest_m = distance
        if distance <= radius_m:
            count += 1
    return {
        "school_count_1600m": count,
        "school_nearest_m": round(nearest_m, 1) if nearest_m is not None else None,
    }


def district_fields(district, ratings: dict[str, float | None], source: str) -> dict:
    """Rating columns for a cell given its (possibly None) district and the
    already state-normalised ratings. Always returns every column so a rerun
    clears stale values. An unrated or missing district yields NULL ratings."""
    rating = ratings.get(district.geoid) if district is not None else None
    return {
        "school_district_geoid": district.geoid if district is not None else None,
        "school_district_name": district.name if district is not None else None,
        "school_district_rating": rating,
        # The column scoring.engine reads as the school rating.
        "school_avg_rating_1600m": rating,
        "school_rating_source": source if rating is not None else None,
    }


def run() -> None:
    from ingestion import school_districts as sd

    all_schools = fetch_all_schools()
    index = build_spatial_index(all_schools)
    districts = sd.load_metro_district_index()
    ratings = sd.normalize_within_state(sd.fetch_district_ratings())
    source = sd.rating_source_label()

    with get_connection() as conn, ingestion_job("schools") as ctx:
        rows_updated = 0
        for entity in iter_geo_entities(conn):
            lat, lon = entity["latitude"], entity["longitude"]
            fields = compute_cell_aggregate(lat, lon, index)
            fields.update(district_fields(districts.assign(lat, lon), ratings, source))
            upsert_feature_store(conn, entity["id"], fields)
            rows_updated += 1
        conn.commit()
        ctx.rows_affected = rows_updated

    print(
        f"[schools] updated feature_store for {rows_updated} geo_entities "
        f"from {len(all_schools)} schools and {len(districts)} district polygons.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    run()
