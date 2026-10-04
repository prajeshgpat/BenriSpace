"""Populates feature_store's running/walking trail columns:
running_trail_count_800m / running_trail_nearest_m (OSM, required baseline)
and strava_segment_count_800m / strava_segment_popularity_raw (Strava
Segments API, optional enhancement).

PROJECT.md's Scoring Factors table: "Popular running/walking trails (proxy
for popularity, desirable neighborhood, safety)". OSM alone only tells us a
trail *exists* -- Strava's segment data (athlete/effort counts) is the
actual popularity signal; OSM presence is the fallback baseline when Strava
isn't configured. Garmin was considered and dropped (no public API exposing
aggregate route-popularity data) -- not revisited here, see PROJECT.md.

Design calls made here (flag if wrong, easy to change):

- **OSM tag selection** (TRAIL_HIGHWAY_TAGS / leisure=track below):
  `highway=path`, `highway=footway`, `highway=track` cover the vast
  majority of runnable/walkable trail surfaces OSM actually tags in this
  metro (unpaved trails, sidewalked paths, and unpaved utility/farm tracks
  that locals run on) -- explicitly excluding any way tagged `foot=no`
  (e.g. a `highway=track` that's fenced off / no pedestrian access) since
  that's a trail we shouldn't be counting as runnable. `leisure=track`
  (running-track ovals, school/park tracks) is included per the task spec
  as an explicit "running track" signal, without filtering on `sport=*`
  (a leisure=track without an explicit sport tag is still usually a
  running-usable track; filtering it out on a missing tag would drop real
  tracks for no benefit). **OSM route relations** (`route=running`/
  `route=foot`) are deliberately NOT included: Overpass's `out center` for
  a relation gives one point at the bounding-box centroid of the whole
  route, which is a poor stand-in for a trail that might span many km
  (e.g. a regional greenway) -- one fabricated point would misrepresent
  "nearby" for every cell along the route except the one near that
  centroid. Pulling full relation-member geometry to do this properly is
  more Overpass load and complexity than an MVP proxy needs; raw
  path/footway/track ways already capture the physical trail surface these
  named routes run along, just without the "this is a named trail" label.
  Easy to revisit if named-trail identity turns out to matter later.

- **Query Overpass once per metro_area bbox, not once per cell** --same
  constraint and reasoning as every other OSM-based job in this codebase
  (ingestion/osm_poi.py, ingestion/roads.py): ~64k geo_entities cells makes
  per-cell Overpass calls a non-starter. `ingestion.grid.BOUNDING_BOXES` is
  reused as the single source of truth for those boxes.

- **Segment granularity, not whole-way** -- mirrors ingestion/roads.py:
  a trail `way` can run for kilometers, so each way's `out geom` node list
  is broken into consecutive (node[i], node[i+1]) midpoint "segments" for
  per-cell distance math, rather than using one point per way.

- **Bucket-indexed nearest/count** -- mirrors ingestion/osm_poi.py's
  approach: a coarse lat/lon bucket index lets each cell only scan its own
  bucket + 8 neighbors (a 3x3 block) instead of every trail segment in the
  metro. `TRAIL_BUCKET_DEG = 0.015` gives a margin of ~1665m (lat) /
  ~1257m (lon, at ~41N) between a cell and its 3x3 block's outer edge --
  comfortably more than `TRAIL_RADIUS_M` (800m, fixed by the
  `running_trail_count_800m` column name), so any segment within 800m of a
  cell is guaranteed to be in its candidate set. When the fast path finds
  nothing within 800m, `nearest_and_count_indexed` falls back to a full
  scan (same fallback shape as osm_poi.py) so `running_trail_nearest_m`
  stays the TRUE unbounded nearest distance, never an approximation capped
  by bucket size.

- **Strava Segments API tiling + rate-limit arithmetic** -- Strava's API is
  tightly rate-limited (~100 requests/15min, ~1000/day on a default app).
  With ~64,000 grid cells, per-cell or even per-small-tile queries are
  impossible. Instead:
    1. `generate_explore_tiles()` tiles `ingestion.grid.BOUNDING_BOXES` at
       `TILE_STEP_DEG = 0.15` degrees (~16.7km lat x ~12.6km lon at NYC
       latitude -- a "several-km bounding box" per the task spec). Run
       against the actual v1 metro bounding boxes, this produces **227
       tiles** (verified by running `generate_explore_tiles()` directly --
       see tests/test_trails.py). One `GET /segments/explore` call per
       tile = 227 calls, well under the ~1000/day budget.
    2. `GET /segments/explore` does NOT return athlete_count/effort_count/
       star_count -- confirmed against Strava's published Swagger schema
       (developers.strava.com/swagger/swagger.json) on 2026-09-28: the
       explore response's segment objects carry only
       id/name/climb_category/avg_grade/start_latlng/end_latlng/
       elev_difference/distance/points/starred. Those three popularity
       fields live only on the DetailedSegment shape returned by a
       per-segment `GET /segments/{id}` follow-up call. This resolves the
       uncertainty flagged in the task: **a second, per-segment call is
       required**, it is not available in bulk from explore.
    3. Because a per-segment detail call is needed, the 227 explore calls
       leave a budget of `STRAVA_DAILY_CALL_BUDGET (900) - 227 = 673`
       remaining detail calls for that day (900 chosen as a safety margin
       under the documented ~1000/day, not 1000 itself).
       `select_detail_call_budget()` computes this at run time.
       `select_segments_for_detail()` dedupes segment ids across tiles and
       picks them breadth-first (rank 0 from every tile, then rank 1, ...)
       up to that budget, so the capped budget spreads coverage across the
       whole metro instead of exhausting itself detailing every segment in
       the first few dense tiles.
    4. `StravaRateLimiter` throttles to 90 calls/15min (a safety margin
       under the documented ~100/15min) via a sliding window, sleeping
       only when necessary. With ~227 explore + up to ~673 detail calls
       (~900 total) at 90/15min, a full run takes on the order of
       900 / 90 * 15min ~= 150 minutes -- acceptable for the weekly cron
       cadence PHASES.md's ingestion orchestration already uses, not
       something a live user request ever waits on.
    5. This is explicitly a coarse enhancement layer, not exhaustive
       coverage: dense/popular areas get real popularity data, sparser
       areas may get none. That's fine -- contracts/normalization.md is
       explicit that Strava data is optional, never backfilled with 0.
  `strava_segment_popularity_raw` combines the two popularity signals as
  `athlete_count + 0.05 * effort_count + star_count`: athlete_count
  (distinct people who've run the segment) is the most direct "how many
  people use this trail" proxy and dominates; effort_count (total
  run-throughs, including repeats by the same person) is added at low
  weight as a secondary "how often" signal without letting a handful of
  repeat users dominate; star_count (explicit bookmarks) is a rarer but
  genuine "this is notable" signal, weighted like one extra athlete per
  star. This raw value only needs to be internally consistent and
  monotonic in "more popular" -- scoring/engine.py min-max normalizes it
  per-metro-cohort independently of the proximity/density signal (see its
  module docstring, design call #1), so the exact formula/scale doesn't
  need to match any external standard.

- **Strava OAuth**: `common.config.STRAVA_CLIENT_ID/SECRET/REFRESH_TOKEN`
  unset -> Strava is skipped entirely (`strava_configured()` returns
  False) and only the OSM baseline is written, same
  configured-optional-source pattern as `ingestion/gtfs_transit.py`'s NJ
  Transit and `ingestion/schools.py`'s stubbed county sources. If
  configured but the token refresh or explore/detail calls fail (bad
  creds, Strava outage, rate-limit exhaustion), the failure is caught,
  logged to its own `ingestion_runs` row (source='trails_strava', mirrors
  gtfs_transit.py's per-agency isolation), and the job degrades to
  OSM-only rather than failing the whole `trails` ingestion run.

Everything that doesn't touch the network or the DB (Overpass response
parsing, OSM tag classification, per-cell trail count/nearest math, tile
generation, Strava response parsing, the OAuth refresh call shape, rate
limiter, and detail-call selection) is a pure/mockable function, unit
tested in tests/test_trails.py without a live DB or live Strava call.
`run()` and its `_run_osm_trails`/`_run_strava_enhancement` helpers are the
thin, untested DB/network glue (same convention as every sibling ingestion
module).
"""

import itertools
import math
import sys
import time

import httpx

from common import config
from common.db import get_connection, iter_geo_entities, log_ingestion_run, upsert_feature_store
from common.geo import haversine_m
from common.ingestion_log import ingestion_job
from common.overpass import post_overpass_query
from ingestion.grid import BOUNDING_BOXES

OVERPASS_TIMEOUT_S = 180
HTTP_TIMEOUT_S = OVERPASS_TIMEOUT_S + 30
MAX_SPLIT_DEPTH = (
    3  # 4^3 = up to 64 sub-tiles per metro in the worst case, matches ingestion/roads.py
)

TRAIL_RADIUS_M = 800.0  # fixed by the running_trail_count_800m column name

# See module docstring for the tag-selection rationale.
TRAIL_HIGHWAY_TAGS = ("path", "footway", "track")
# OSM tags an ordinary sidewalk as highway=footway + footway=sidewalk (and
# a pedestrian crossing as footway=crossing) -- neither is a "trail" in
# any sense relevant to "popular running/walking trails, proxy for
# desirable/safe neighborhood." Excluding them matters for two reasons,
# discovered together live 2026-09-29: (1) a signal present on nearly
# every block of a dense city doesn't discriminate between neighborhoods
# at all, defeating the point of the factor: (2) it was *why* NYC alone
# returned 1,173,871 "trail" segments -- overwhelmingly ordinary sidewalks,
# not the sparse dedicated-trail dataset the per-cell bucket search was
# designed around, which made even the fast/indexed path do a linear scan
# over ~1,300 points per bucket on real data (benchmarked: 4029 cells took
# 921s / ~15min for this reason alone, unrelated to the separate ring-
# expansion fix above).
EXCLUDED_FOOTWAY_SUBTAGS = ("sidewalk", "crossing")

# ~1.67km (lat) x ~1.26km (lon at ~41N) per bucket -- see module docstring
# for the margin-vs-TRAIL_RADIUS_M argument. Shared by the OSM trail index
# and the Strava segment-point index (both use an 800m radius).
BUCKET_DEG = 0.015

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_EXPLORE_URL = f"{STRAVA_API_BASE}/segments/explore"
STRAVA_SEGMENT_DETAIL_URL_TMPL = STRAVA_API_BASE + "/segments/{segment_id}"

# Tile size for segments/explore tiling -- see module docstring's rate-limit
# arithmetic (227 tiles over the v1 metro bounding boxes at this step).
TILE_STEP_DEG = 0.15

# Safety margins under Strava's documented ~100/15min and ~1000/day caps.
STRAVA_SHORT_WINDOW_LIMIT = 90
STRAVA_SHORT_WINDOW_S = 15 * 60.0
STRAVA_DAILY_CALL_BUDGET = 900
# Belt-and-suspenders hard cap on detail calls in a single run, independent
# of the daily-budget arithmetic above.
STRAVA_MAX_DETAIL_CALLS = 700


# ==========================================================================
# OSM trail ingestion -- pure logic (unit tested, no network/DB)
# ==========================================================================


def build_overpass_trail_query(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> str:
    """One Overpass QL query for every trail/path/track way in the bbox,
    excluding foot=no and ordinary sidewalks/crossings (see
    EXCLUDED_FOOTWAY_SUBTAGS) -- filtered server-side so the excluded data
    (the overwhelming majority of highway=footway ways in a dense city)
    never has to be downloaded and parsed at all, not just discarded
    client-side. Overpass bbox order is (south, west, north, east)."""
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    footway_exclusions = "".join(f'["footway"!="{tag}"]' for tag in EXCLUDED_FOOTWAY_SUBTAGS)
    return f"""[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  way["highway"~"^(path|track)$"]["foot"!="no"]({bbox});
  way["highway"="footway"]{footway_exclusions}["foot"!="no"]({bbox});
  way["leisure"="track"]({bbox});
);
out geom;"""


def is_trail_way(tags: dict) -> bool:
    """True if this way's tags qualify it as a running/walking trail
    surface per TRAIL_HIGHWAY_TAGS / leisure=track, isn't explicitly
    closed to pedestrians (foot=no), and isn't an ordinary sidewalk or
    crossing (see EXCLUDED_FOOTWAY_SUBTAGS) -- defense in depth alongside
    the server-side Overpass query filter, and what this function's own
    unit tests exercise directly."""
    if tags.get("foot") == "no":
        return False
    highway = tags.get("highway")
    if highway == "footway" and tags.get("footway") in EXCLUDED_FOOTWAY_SUBTAGS:
        return False
    if highway in TRAIL_HIGHWAY_TAGS:
        return True
    return tags.get("leisure") == "track"


def parse_trail_elements(elements: list[dict]) -> list[dict]:
    """Overpass JSON `elements` list -> flat list of
    {"lat", "lon", "tag"} trail segments (consecutive-node-pair midpoints
    of each qualifying way's `out geom` geometry -- see module docstring on
    segment granularity vs. whole-way)."""
    segments: list[dict] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        if not is_trail_way(tags):
            continue
        tag_value = tags.get("highway") or tags.get("leisure")
        geometry = el.get("geometry") or []
        for a, b in itertools.pairwise(geometry):
            if a is None or b is None:
                continue
            mid_lat = (a["lat"] + b["lat"]) / 2.0
            mid_lon = (a["lon"] + b["lon"]) / 2.0
            segments.append({"lat": mid_lat, "lon": mid_lon, "tag": tag_value})
    return segments


def build_bucket_index(
    points: list[dict], bucket_deg: float = BUCKET_DEG
) -> dict[tuple[int, int], list[dict]]:
    """Buckets any {"lat", "lon", ...} points into a coarse lat/lon grid.
    Shared by the OSM trail-segment index and the Strava segment-point
    index -- both only need lat/lon keys."""
    index: dict[tuple[int, int], list[dict]] = {}
    for point in points:
        key = (math.floor(point["lat"] / bucket_deg), math.floor(point["lon"] / bucket_deg))
        index.setdefault(key, []).append(point)
    return index


def candidates_near(
    index: dict[tuple[int, int], list[dict]],
    lat: float,
    lon: float,
    bucket_deg: float = BUCKET_DEG,
    ring: int = 1,
) -> list[dict]:
    """Points from the query point's own bucket plus `ring` rings of
    neighbors (ring=1 -> a 3x3 block). See module docstring for why this
    comfortably covers TRAIL_RADIUS_M at BUCKET_DEG's size."""
    cx = math.floor(lat / bucket_deg)
    cy = math.floor(lon / bucket_deg)
    out: list[dict] = []
    for dx in range(-ring, ring + 1):
        for dy in range(-ring, ring + 1):
            out.extend(index.get((cx + dx, cy + dy), []))
    return out


def nearest_and_count(
    cell_lat: float,
    cell_lon: float,
    points: list[dict],
    radius_m: float = TRAIL_RADIUS_M,
) -> tuple[int, float | None]:
    """Brute-force ground truth: count of points within radius_m, and the
    true nearest distance (unbounded, None if points is empty)."""
    if not points:
        return 0, None
    count = 0
    nearest: float | None = None
    for point in points:
        d = haversine_m(cell_lat, cell_lon, point["lat"], point["lon"])
        if nearest is None or d < nearest:
            nearest = d
        if d <= radius_m:
            count += 1
    return count, nearest


def nearest_and_count_indexed(
    cell_lat: float,
    cell_lon: float,
    all_points: list[dict],
    index: dict[tuple[int, int], list[dict]],
    bucket_deg: float = BUCKET_DEG,
    radius_m: float = TRAIL_RADIUS_M,
) -> tuple[int, float | None]:
    """Same (count, nearest) contract as nearest_and_count(), but scans the
    bucket index's nearby candidates first -- exact whenever ring=1 (the
    cell's own bucket + 8 neighbors) finds ANY candidate, since that
    block's margin already exceeds radius_m (see module docstring), so a
    found candidate is guaranteed to include anything within radius_m and
    is the true nearest for anything reasonably close.

    ring=1 finding NOTHING is the real question, and for a sparse feature
    like trails (unlike roads, which are ubiquitous) that's the COMMON
    case, not rare -- confirmed live 2026-09-29: the original version
    fell back to a full brute-force scan of every segment in the metro
    whenever that happened, which for ~20k long_island cells against
    700k+ segments stalled for 30+ minutes and the DB connection was
    killed as idle by Supabase's pooler before a single row was written.
    Expanding the search ring is nearly as cheap as ring=1 and stays
    correct for the same reason ring=1 is: once ANY candidate is found,
    it's within that ring's guaranteed-covered area, so nothing closer
    was missed. Only escalates to a true full scan if even a ~50km+ box
    (ring=32) is empty -- should essentially never happen for a populated
    metro area."""
    for ring in (1, 2, 4, 8, 16, 32):
        candidates = candidates_near(index, cell_lat, cell_lon, bucket_deg, ring=ring)
        if candidates:
            return nearest_and_count(cell_lat, cell_lon, candidates, radius_m)
    return nearest_and_count(cell_lat, cell_lon, all_points, radius_m)


def compute_cell_osm_trail_features(
    cell_lat: float,
    cell_lon: float,
    segments: list[dict],
    index: dict[tuple[int, int], list[dict]] | None = None,
    radius_m: float = TRAIL_RADIUS_M,
) -> dict[str, int | float | None]:
    """One geo_entities cell's running_trail_count_800m / _nearest_m."""
    if index is not None:
        count, nearest = nearest_and_count_indexed(
            cell_lat, cell_lon, segments, index, radius_m=radius_m
        )
    else:
        count, nearest = nearest_and_count(cell_lat, cell_lon, segments, radius_m)
    return {
        "running_trail_count_800m": count,
        "running_trail_nearest_m": round(nearest, 1) if nearest is not None else None,
    }


# ==========================================================================
# OSM trail ingestion -- network/DB glue (not unit tested)
# ==========================================================================


def _fetch_trail_segments_single(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[dict]:
    query = build_overpass_trail_query(min_lat, max_lat, min_lon, max_lon)
    data = post_overpass_query(query, timeout=HTTP_TIMEOUT_S)
    return parse_trail_elements(data.get("elements", []))


def fetch_trail_segments_for_bbox(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float, depth: int = 0
) -> list[dict]:
    """Fetch trail segments for a bbox, adaptively splitting into 4
    quadrants and retrying on a server-side timeout/error rather than
    failing the whole run -- mirrors ingestion/roads.py's
    fetch_segments_for_bbox (same MAX_SPLIT_DEPTH constant). Added after a
    live 504 Gateway Timeout from Overpass on the nyc query (2026-09-29,
    transient server load, not a bug in the query itself) killed the
    entire job with no fallback -- roads.py already had this resilience
    for the identical failure mode, trails.py hadn't needed it until now.
    post_overpass_query already retries 429s internally, so what reaches
    this except block is a genuine timeout/size/server problem."""
    try:
        return _fetch_trail_segments_single(min_lat, max_lat, min_lon, max_lon)
    except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
        if depth >= MAX_SPLIT_DEPTH:
            raise
        print(
            f"[trails] Overpass query failed for bbox "
            f"({min_lat},{min_lon},{max_lat},{max_lon}) at depth {depth} ({exc}); "
            f"splitting into quadrants and retrying",
            file=sys.stderr,
        )
        mid_lat = (min_lat + max_lat) / 2.0
        mid_lon = (min_lon + max_lon) / 2.0
        segments: list[dict] = []
        for sub_min_lat, sub_max_lat, sub_min_lon, sub_max_lon in (
            (min_lat, mid_lat, min_lon, mid_lon),
            (min_lat, mid_lat, mid_lon, max_lon),
            (mid_lat, max_lat, min_lon, mid_lon),
            (mid_lat, max_lat, mid_lon, max_lon),
        ):
            time.sleep(1)  # be polite to the free shared Overpass instance
            segments.extend(
                fetch_trail_segments_for_bbox(
                    sub_min_lat, sub_max_lat, sub_min_lon, sub_max_lon, depth + 1
                )
            )
        return segments


def _run_osm_trails(conn) -> int:
    rows_updated = 0
    for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
        print(f"[trails] fetching OSM trail data for {metro_area}...", file=sys.stderr)
        segments = fetch_trail_segments_for_bbox(min_lat, max_lat, min_lon, max_lon)
        index = build_bucket_index(segments)
        print(f"[trails] {metro_area}: {len(segments)} trail segments", file=sys.stderr)

        for cell in iter_geo_entities(conn, metro_area=metro_area):
            features = compute_cell_osm_trail_features(
                cell["latitude"], cell["longitude"], segments, index
            )
            upsert_feature_store(conn, cell["id"], features)
            rows_updated += 1
        conn.commit()
    return rows_updated


# ==========================================================================
# Strava Segments enhancement -- pure logic (unit tested, no network/DB)
# ==========================================================================


def strava_configured() -> bool:
    return bool(
        config.STRAVA_CLIENT_ID and config.STRAVA_CLIENT_SECRET and config.STRAVA_REFRESH_TOKEN
    )


class StravaRateLimiter:
    """Sliding-window limiter for Strava's ~100 req/15min short-term cap.
    Call `.wait()` before every Strava HTTP request; it blocks
    (`sleep_fn`) only when the short window is already full. `sleep_fn`/
    `time_fn` are injectable so tests can verify throttling behavior
    without a live clock or real sleeps."""

    def __init__(
        self,
        limit: int = STRAVA_SHORT_WINDOW_LIMIT,
        window_s: float = STRAVA_SHORT_WINDOW_S,
        sleep_fn=time.sleep,
        time_fn=time.monotonic,
    ):
        self.limit = limit
        self.window_s = window_s
        self._sleep = sleep_fn
        self._time = time_fn
        self._calls: list[float] = []

    def wait(self) -> None:
        now = self._time()
        self._calls = [t for t in self._calls if now - t < self.window_s]
        if len(self._calls) >= self.limit:
            sleep_for = self.window_s - (now - self._calls[0])
            if sleep_for > 0:
                self._sleep(sleep_for)
            now = self._time()
            self._calls = [t for t in self._calls if now - t < self.window_s]
        self._calls.append(self._time())


def generate_explore_tiles(
    bounding_boxes=BOUNDING_BOXES, step_deg: float = TILE_STEP_DEG
) -> list[tuple[str, float, float, float, float]]:
    """Tiles each metro_area's bounding box into `step_deg` x `step_deg`
    sub-boxes for segments/explore calls. Returns
    [(metro_area, min_lat, max_lat, min_lon, max_lon), ...]. See module
    docstring for the resulting tile count (227) and why it's safely under
    the daily call budget."""
    tiles: list[tuple[str, float, float, float, float]] = []
    for metro_area, min_lat, max_lat, min_lon, max_lon in bounding_boxes:
        lat = min_lat
        while lat < max_lat:
            tile_max_lat = min(lat + step_deg, max_lat)
            lon = min_lon
            while lon < max_lon:
                tile_max_lon = min(lon + step_deg, max_lon)
                tiles.append((metro_area, lat, tile_max_lat, lon, tile_max_lon))
                lon += step_deg
            lat += step_deg
    return tiles


def build_explore_bounds_param(
    min_lat: float, min_lon: float, max_lat: float, max_lon: float
) -> str:
    """Strava's `bounds` query param: "sw_lat,sw_lng,ne_lat,ne_lng"."""
    return f"{min_lat},{min_lon},{max_lat},{max_lon}"


def parse_explore_response(data: dict) -> list[dict]:
    """Extracts segment stubs from a GET /segments/explore response. Only
    lightweight fields are present on this endpoint (confirmed against
    Strava's published Swagger schema, 2026-09-28) --
    athlete_count/effort_count/star_count are NOT included here; see
    parse_segment_detail_response for the per-segment follow-up call that
    provides them."""
    out: list[dict] = []
    for seg in data.get("segments", []):
        seg_id = seg.get("id")
        start = seg.get("start_latlng")
        end = seg.get("end_latlng")
        if seg_id is None or not start or not end:
            continue
        out.append(
            {"id": seg_id, "name": seg.get("name"), "start_latlng": start, "end_latlng": end}
        )
    return out


def parse_segment_detail_response(data: dict) -> dict:
    """Extracts the popularity-relevant fields from a GET /segments/{id}
    (DetailedSegment) response. Missing counts default to 0 rather than
    None -- a segment Strava returns details for genuinely has these
    counters, even if occasionally absent/zero in the payload."""
    return {
        "id": data.get("id"),
        "athlete_count": data.get("athlete_count") or 0,
        "effort_count": data.get("effort_count") or 0,
        "star_count": data.get("star_count") or 0,
    }


def compute_segment_popularity_raw(athlete_count: int, effort_count: int, star_count: int) -> float:
    """See module docstring for the formula rationale. Monotonic in "more
    popular"; the exact scale doesn't matter since scoring/engine.py
    min-max normalizes this per-metro-cohort independently."""
    return round(athlete_count + 0.05 * effort_count + star_count, 2)


def select_detail_call_budget(
    explore_calls_made: int,
    daily_budget: int = STRAVA_DAILY_CALL_BUDGET,
    max_detail_calls: int = STRAVA_MAX_DETAIL_CALLS,
) -> int:
    """How many segment-detail calls this run may still make, given how
    many explore calls it already made -- min() of a hard per-run cap and
    whatever's left of the documented daily budget."""
    remaining = max(daily_budget - explore_calls_made, 0)
    return min(max_detail_calls, remaining)


def select_segments_for_detail(
    explore_results_by_tile: list[list[dict]], max_calls: int
) -> list[int]:
    """Picks unique segment ids across all tiles' explore results,
    breadth-first (rank 0 from every tile, then rank 1, ...) so a capped
    detail-call budget spreads coverage across the whole metro instead of
    exhausting itself detailing every segment found in the first few dense
    tiles. Returns up to max_calls ids, in selection order."""
    if max_calls <= 0:
        return []
    seen: set = set()
    ordered: list[int] = []
    max_rank = max((len(tile) for tile in explore_results_by_tile), default=0)
    for rank in range(max_rank):
        for tile in explore_results_by_tile:
            if rank >= len(tile):
                continue
            seg_id = tile[rank]["id"]
            if seg_id in seen:
                continue
            seen.add(seg_id)
            ordered.append(seg_id)
            if len(ordered) >= max_calls:
                return ordered
    return ordered


def build_strava_segment_points(segments: list[dict]) -> list[dict]:
    """segments: [{"start_latlng": [lat, lon], "end_latlng": [lat, lon],
    "popularity_raw": float}, ...]. Returns [{"lat", "lon",
    "popularity_raw"}] using each segment's start/end midpoint as its
    representative location -- good enough for an 800m-radius aggregate,
    not meant to reflect a segment's full multi-km extent precisely."""
    points: list[dict] = []
    for seg in segments:
        start, end = seg.get("start_latlng"), seg.get("end_latlng")
        if not start or not end:
            continue
        points.append(
            {
                "lat": (start[0] + end[0]) / 2.0,
                "lon": (start[1] + end[1]) / 2.0,
                "popularity_raw": seg["popularity_raw"],
            }
        )
    return points


def compute_cell_strava_features(
    cell_lat: float,
    cell_lon: float,
    points: list[dict],
    index: dict[tuple[int, int], list[dict]] | None = None,
    radius_m: float = TRAIL_RADIUS_M,
) -> dict[str, int | float] | None:
    """Returns {"strava_segment_count_800m", "strava_segment_popularity_raw"}
    for one cell, or None if no segment is within radius_m -- callers must
    skip the upsert entirely in that case (leave the columns null; see
    contracts/normalization.md -- never backfill with 0)."""
    candidates = candidates_near(index, cell_lat, cell_lon) if index is not None else points
    within = [
        p for p in candidates if haversine_m(cell_lat, cell_lon, p["lat"], p["lon"]) <= radius_m
    ]
    if not within:
        return None
    return {
        "strava_segment_count_800m": len(within),
        "strava_segment_popularity_raw": round(sum(p["popularity_raw"] for p in within), 2),
    }


# ==========================================================================
# Strava Segments enhancement -- network/DB glue (not unit tested)
# ==========================================================================


def refresh_access_token(
    client: httpx.Client, client_id: str, client_secret: str, refresh_token: str
) -> str:
    """POST https://www.strava.com/oauth/token, grant_type=refresh_token.
    Returns a short-lived access token."""
    resp = client.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError(f"Strava OAuth refresh response missing access_token: {data}")
    return access_token


def fetch_explore_segments(
    client: httpx.Client,
    access_token: str,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    activity_type: str = "running",
) -> list[dict]:
    resp = client.get(
        STRAVA_EXPLORE_URL,
        params={
            "bounds": build_explore_bounds_param(min_lat, min_lon, max_lat, max_lon),
            "activity_type": activity_type,
        },
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    return parse_explore_response(resp.json())


def fetch_segment_detail(client: httpx.Client, access_token: str, segment_id: int) -> dict:
    resp = client.get(
        STRAVA_SEGMENT_DETAIL_URL_TMPL.format(segment_id=segment_id),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    return parse_segment_detail_response(resp.json())


def _fetch_and_apply_strava(conn) -> int:
    with httpx.Client() as client:
        access_token = refresh_access_token(
            client,
            config.STRAVA_CLIENT_ID,
            config.STRAVA_CLIENT_SECRET,
            config.STRAVA_REFRESH_TOKEN,
        )
        limiter = StravaRateLimiter()

        tiles = generate_explore_tiles()
        explore_results_by_tile: list[list[dict]] = []
        for metro_area, min_lat, max_lat, min_lon, max_lon in tiles:
            limiter.wait()
            stubs = fetch_explore_segments(client, access_token, min_lat, min_lon, max_lat, max_lon)
            explore_results_by_tile.append(stubs)
        print(f"[trails] Strava explore: {len(tiles)} tiles queried", file=sys.stderr)

        detail_budget = select_detail_call_budget(explore_calls_made=len(tiles))
        segment_ids = select_segments_for_detail(explore_results_by_tile, detail_budget)
        stub_by_id = {s["id"]: s for tile in explore_results_by_tile for s in tile}

        detailed_segments: list[dict] = []
        for seg_id in segment_ids:
            limiter.wait()
            detail = fetch_segment_detail(client, access_token, seg_id)
            stub = stub_by_id.get(seg_id, {})
            detailed_segments.append(
                {
                    "start_latlng": stub.get("start_latlng"),
                    "end_latlng": stub.get("end_latlng"),
                    "popularity_raw": compute_segment_popularity_raw(
                        detail["athlete_count"], detail["effort_count"], detail["star_count"]
                    ),
                }
            )
        print(
            f"[trails] Strava detail calls: {len(segment_ids)} unique segments "
            f"(budget was {detail_budget})",
            file=sys.stderr,
        )

    points = build_strava_segment_points(detailed_segments)
    index = build_bucket_index(points)

    rows = 0
    for cell in iter_geo_entities(conn):
        features = compute_cell_strava_features(cell["latitude"], cell["longitude"], points, index)
        if features is None:
            continue
        upsert_feature_store(conn, cell["id"], features)
        rows += 1
    conn.commit()
    return rows


def _run_strava_enhancement(conn) -> int:
    if not strava_configured():
        print(
            "[trails] Strava not configured (STRAVA_CLIENT_ID/SECRET/REFRESH_TOKEN "
            "unset) -- skipping enhancement, OSM-only baseline stands.",
            file=sys.stderr,
        )
        return 0

    run_id = log_ingestion_run("trails_strava", status="running")
    try:
        rows = _fetch_and_apply_strava(conn)
    except Exception as exc:  # noqa: BLE001 -- isolate Strava's failure from the OSM baseline
        log_ingestion_run("trails_strava", status="failed", error_message=str(exc), run_id=run_id)
        print(f"[trails] Strava enhancement failed, degrading to OSM-only: {exc}", file=sys.stderr)
        return 0

    log_ingestion_run("trails_strava", status="success", rows_affected=rows, run_id=run_id)
    return rows


# ==========================================================================
# Entry point
# ==========================================================================


def run() -> None:
    with get_connection() as conn, ingestion_job("trails") as ctx:
        rows_updated = _run_osm_trails(conn)
        ctx.rows_affected = rows_updated
        strava_rows = _run_strava_enhancement(conn)

    print(
        f"trails: OSM baseline updated {rows_updated} geo_entities; "
        f"Strava enhancement updated {strava_rows} cells.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    run()
