"""School-district boundaries, district assignment and district ratings.

Needs the optional `schools` extra (shapely + pyshp). Ingestion-only: never
imported by api/, scoring/ or common/, so it stays out of the Lambda bundle.

Pieces (all pure except the two `download_*`/`fetch_*` helpers):

- `DistrictIndex`: STRtree point-in-polygon. A point that is in no district
  polygon gets None. We NEVER fall back to the nearest district.
- Overlap policy: Census/NCES boundaries come in three layers (unified,
  elementary, secondary). Where several cover one point, prefer
  unified > elementary > secondary, then the smallest GEOID, so the result is
  deterministic. (Secondary-only overlays would otherwise shadow elementary
  districts that actually run the local schools.)
- Ratings: `parse_rating_row` / `fetch_district_ratings` read the Urban
  Institute Education Data Portal (EDFacts district assessments, ODC-By
  licensed; federal EDFacts data). The metric is the mean of math and reading
  percent proficient (midpoint). Proficiency is defined by each state's own
  test, so raw values are NOT comparable across NY/NJ/CT:
  `normalize_within_state` converts them to a 0-100 within-state percentile
  (mid-rank) BEFORE writing, which is what makes the engine's per-metro
  min-max cohort comparable. A district with no usable value stays None.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
from shapely import STRtree
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

CACHE_DIR = Path("data/cache/schools")  # data/cache/ is gitignored
USER_AGENT = "BenriSpace-ingestion/1.0 (+https://benrispace.com)"
REQUEST_TIMEOUT_S = 120

# State FIPS of the v1 metro (NY, NJ, CT).
METRO_STATE_FIPS = {"09": "CT", "34": "NJ", "36": "NY"}

# Census TIGER/Line school districts (the same layer NCES EDGE republishes),
# one zip per state and type. UNVERIFIED URL pattern: confirm before the real run.
TIGER_SD_URL = "https://www2.census.gov/geo/tiger/TIGER{year}/{layer}/tl_{year}_{fips}_{suffix}.zip"
TIGER_YEAR = 2024
LAYERS = (("UNSD", "unsd"), ("ELSD", "elsd"), ("SCSD", "scsd"))
LAYER_PRIORITY = {"unsd": 0, "elsd": 1, "scsd": 2}

URBAN_URL = (
    "https://educationdata.urban.org/api/v1/school-districts/edfacts/assessments/"
    "{year}/grade-edfacts/99/"
)
RATING_YEAR = 2019  # UNVERIFIED: confirm latest year with full coverage
RATING_SOURCE_TEMPLATE = "edfacts_proficiency_{year}_state_percentile"
# Urban Portal missing/suppressed codes are negative (-1, -2, -3).
SUBGROUP_ALL_FIELDS = (
    "race", "sex", "lep", "homeless", "disability", "econ_disadvantaged",
    "foster_care", "military_connected", "migrant",
)


@dataclass(frozen=True)
class District:
    geoid: str
    name: str
    layer: str  # "unsd" | "elsd" | "scsd"
    state_fips: str


class DistrictIndex:
    """Point-in-polygon lookup over district polygons using an STRtree."""

    def __init__(self, items: Iterable[tuple[District, BaseGeometry]]):
        pairs = list(items)
        self._districts = [d for d, _ in pairs]
        self._geoms = [g for _, g in pairs]
        self._tree = STRtree(self._geoms) if self._geoms else None

    def __len__(self) -> int:
        return len(self._districts)

    def assign(self, lat: float, lon: float) -> District | None:
        if self._tree is None:
            return None
        point = Point(lon, lat)
        hits = [
            i for i in self._tree.query(point, predicate="intersects")
        ]
        if not hits:
            return None  # no match -> NULL district, never nearest-guess
        best = min(
            hits,
            key=lambda i: (
                LAYER_PRIORITY.get(self._districts[i].layer, 9),
                self._districts[i].geoid,
            ),
        )
        return self._districts[best]


def districts_from_records(
    records: Iterable[tuple[dict, dict]], layer: str
) -> list[tuple[District, BaseGeometry]]:
    """records: (attribute dict, GeoJSON-like geometry). Attributes follow the
    TIGER schema (GEOID, NAME, STATEFP)."""
    out: list[tuple[District, BaseGeometry]] = []
    for attrs, geom in records:
        geoid = attrs.get("GEOID")
        if not geoid or geom is None:
            continue
        out.append(
            (
                District(
                    geoid=str(geoid),
                    name=str(attrs.get("NAME") or ""),
                    layer=layer,
                    state_fips=str(attrs.get("STATEFP") or str(geoid)[:2]),
                ),
                shape(geom),
            )
        )
    return out


def read_shapefile(path: Path) -> list[tuple[dict, dict]]:
    import shapefile  # pyshp

    with shapefile.Reader(str(path)) as sf:
        return [
            (rec.as_dict(), s.__geo_interface__)
            for rec, s in zip(sf.records(), sf.shapes(), strict=True)
        ]


def download_cached(url: str, cache_dir: Path = CACHE_DIR) -> Path:
    """Downloads once into the gitignored cache; reuses it afterwards."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / url.rsplit("/", 1)[-1]
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream(
        "GET", url, headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_S, follow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    tmp.rename(dest)
    return dest


def load_metro_district_index(states: Iterable[str] = METRO_STATE_FIPS) -> DistrictIndex:
    items: list[tuple[District, BaseGeometry]] = []
    for fips in states:
        for layer_dir, suffix in LAYERS:
            url = TIGER_SD_URL.format(year=TIGER_YEAR, layer=layer_dir, fips=fips, suffix=suffix)
            items.extend(districts_from_records(read_shapefile(download_cached(url)), suffix))
    return DistrictIndex(items)


# --- ratings -----------------------------------------------------------


def _valid_pct(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or v < 0 or v > 100:
        return None
    return v


def parse_rating_row(row: dict) -> tuple[str, float] | None:
    """One Urban EDFacts district-assessment row -> (leaid, raw 0-100).
    Raw = mean of the available math/reading percent-proficient midpoints.
    Rows for a sub-population (non-99 subgroup code) and rows with only
    suppressed values give None."""
    for field in SUBGROUP_ALL_FIELDS:
        if field in row and str(row[field]) not in ("99", "99.0"):
            return None
    if "grade_edfacts" in row and str(row["grade_edfacts"]) not in ("99", "99.0"):
        return None
    leaid = row.get("leaid")
    if leaid is None:
        return None
    values = [
        v for v in (
            _valid_pct(row.get("math_test_pct_prof_midpt")),
            _valid_pct(row.get("read_test_pct_prof_midpt")),
        )
        if v is not None
    ]
    if not values:
        return None
    return str(leaid).zfill(7), sum(values) / len(values)


def normalize_within_state(raw_by_geoid: dict[str, float | None]) -> dict[str, float | None]:
    """Mid-rank percentile (0-100) within each state (state = first two chars
    of the 7-digit GEOID). None stays None; a lone district scores 50."""
    by_state: dict[str, list[tuple[str, float]]] = {}
    out: dict[str, float | None] = {}
    for geoid, raw in raw_by_geoid.items():
        if raw is None:
            out[geoid] = None
        else:
            by_state.setdefault(geoid[:2], []).append((geoid, raw))
    for rows in by_state.values():
        n = len(rows)
        values = [v for _, v in rows]
        for geoid, v in rows:
            if n == 1:
                out[geoid] = 50.0
                continue
            less = sum(1 for x in values if x < v)
            equal = sum(1 for x in values if x == v)
            out[geoid] = round(100.0 * (less + (equal - 1) / 2) / (n - 1), 3)
    return out


def fetch_district_ratings(
    states: Iterable[str] = METRO_STATE_FIPS, year: int = RATING_YEAR
) -> dict[str, float | None]:
    """Raw per-district proficiency for the given states (one paginated pull
    per state; ~1.5k districts total). Real-run only."""
    raw: dict[str, float | None] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_S) as client:
        for fips in states:
            url: str | None = URBAN_URL.format(year=year)
            params: dict | None = {"fips": int(fips)}
            while url:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                body = resp.json()
                for row in body.get("results", []):
                    parsed = parse_rating_row(row)
                    if parsed is not None:
                        raw[parsed[0]] = parsed[1]
                url, params = body.get("next"), None
    return raw


def rating_source_label(year: int = RATING_YEAR) -> str:
    return RATING_SOURCE_TEMPLATE.format(year=year)

