"""Populates feature_store's road columns (road_classification,
congestion_proxy_raw, emergency_corridor_proxy_raw, street_orientation) from
OSM Overpass `highway=*` classification tags.

Design calls made here (flag if wrong, easy to change):

- **Query Overpass once per metro_area bbox, not once per cell.** ~64k
  geo_entities rows makes per-cell Overpass calls a non-starter (rate limits,
  wall-clock time). Instead we fetch all vehicle-road geometry inside each
  metro_area's bounding box (reusing `ingestion.grid.BOUNDING_BOXES` as the
  single source of truth for those boxes) in one query, then do all
  per-cell classification locally. If a bbox query times out (some of these
  boxes are large — e.g. northern_nj spans most of the state), we adaptively
  split it into 4 quadrants and retry each, recursing up to `MAX_SPLIT_DEPTH`
  — cheaper than guessing a fixed tile size up front.

- **Segment granularity, not whole-way.** An OSM `way` can be many km long
  (a residential street winding for 3km); using one midpoint per way would
  make cells near one end of a long way get matched against a midpoint far
  away. Instead each way's `out geom` node list is broken into consecutive
  (node[i], node[i+1]) pairs, each treated as its own short "segment" with
  its own midpoint — still just haversine-to-a-point math (per the
  instructions: no full line-to-point geometry needed for an MVP proxy),
  but at a granularity that tracks the road's actual shape.

- **Bucket-indexed nearest lookup, not brute force.** Comparing every cell
  against every segment (tens of thousands of cells x hundreds of thousands
  of segments) doesn't finish in reasonable time in pure Python. Segments
  are bucketed into a coarse (~0.02 degree, ~1.7-2.2km) lat/lon grid; a
  cell's candidate segments are its own bucket plus the 8 neighbors, which
  comfortably covers the true nearest segment for a ~1.22km x 0.61km
  geohash6 cell without brute-forcing the whole metro.

- **congestion_proxy_raw formula**: sum, over vehicle-road segments within
  CONGESTION_RADIUS_M of the cell, of
  `(class_weight + narrow_bottleneck_bonus) / (1 + distance_m / 200)`.
  `class_weight` (see ROAD_CLASS_WEIGHTS) encodes the OSM highway hierarchy
  (motorway=6 down to service=0.5) — more/closer/higher-classification
  roads nearby = more traffic passing near this cell = worse. The
  `narrow_bottleneck_bonus` (+0.5) fires when a segment has an explicit
  `lanes<=1` tag on an already-non-trivial road (weight>=2) — a single-lane
  stretch of an otherwise-through road is exactly the "single-lane roads
  causing congestion" example PROJECT.md calls out, distinct from a
  low-traffic single-lane residential street (which never gets the bonus
  since its base weight is already low). Distance decay (`1/(1+d/200)`) is
  a simple, monotonic, easy-to-reason-about falloff — not fit to any real
  traffic model, this is explicitly a hand-tuned MVP proxy per PROJECT.md.
  Direction is negative (scoring/engine.py inverts it) so higher = worse,
  which this formula produces.

- **emergency_corridor_proxy_raw formula**: same shape
  (`class_weight / (1 + distance_m / 150)`, summed over nearby segments)
  but restricted to "major corridor" segments only (class_weight >= 3, i.e.
  secondary/primary/trunk/motorway) within EMERGENCY_RADIUS_M — these are
  the roads an ambulance/fire truck would actually use as a through-route,
  per PROJECT.md's "emergency vehicle route noise" factor. A cell three
  doors down from a quiet residential street scores ~0 here even if its
  congestion_proxy_raw is nonzero from local residential density. This is
  explicitly flagged in PROJECT.md as "proxy only — phase 2 refinement, not
  precise" and weighted low (0.5x) in scoring/engine.py's DEFAULT_WEIGHTS
  accordingly — not trying to be more precise than that here.

- **street_orientation**: derived from the single nearest road segment to
  the cell (any vehicle class, not just major ones) — if that nearest
  segment is itself major-classification (class_weight >= 3), the cell
  faces a corridor directly (`facing_corridor`); if the nearest segment is
  minor (residential/tertiary/service/etc), the cell is merely near one,
  i.e. on a side street (`side_street`). No vehicle-road segment found
  within NEAREST_SEARCH_RADIUS_M -> `unknown` (matches the schema's three
  allowed literal values; scoring/engine.py applies no damping for
  `unknown`, same as `facing_corridor` — the conservative default when we
  can't tell).

- **No-data cells** (e.g. the ocean/reservoir cells `ingestion/grid.py`
  notes as an accepted side effect of rectangular bounding boxes) get
  `congestion_proxy_raw = 0.0` / `emergency_corridor_proxy_raw = 0.0`
  (no roads nearby genuinely means no road-proximity signal, which is a
  real, meaningful value here, not missing data) and
  `road_classification = None` / `street_orientation = 'unknown'`.
"""

import itertools
import math
import sys
import time

import httpx

from common.db import get_connection, iter_geo_entities, upsert_feature_store
from common.geo import haversine_m
from common.ingestion_log import ingestion_job
from common.overpass import make_client, post_overpass_query
from ingestion.grid import BOUNDING_BOXES

OVERPASS_TIMEOUT_S = 180
MAX_SPLIT_DEPTH = 3  # 4^3 = up to 64 sub-tiles per metro in the worst case

# OSM highway=* hierarchy, motorway (busiest through-traffic) to service
# (driveways/parking aisles). Values are otherwise-arbitrary but internally
# consistent — what matters is the ordering, not the absolute numbers.
ROAD_CLASS_WEIGHTS: dict[str, float] = {
    "motorway": 6.0,
    "motorway_link": 6.0,
    "trunk": 5.0,
    "trunk_link": 5.0,
    "primary": 4.0,
    "primary_link": 4.0,
    "secondary": 3.0,
    "secondary_link": 3.0,
    "tertiary": 2.0,
    "tertiary_link": 2.0,
    "unclassified": 1.0,
    "residential": 1.0,
    "living_street": 0.5,
    "service": 0.5,
}
VEHICLE_HIGHWAY_TAGS = set(ROAD_CLASS_WEIGHTS)

MAJOR_CLASS_WEIGHT_THRESHOLD = 3.0  # secondary and above = "corridor" grade

CONGESTION_RADIUS_M = 600.0
EMERGENCY_RADIUS_M = 500.0
NEAREST_SEARCH_RADIUS_M = 1000.0
SEARCH_RADIUS_M = max(CONGESTION_RADIUS_M, EMERGENCY_RADIUS_M, NEAREST_SEARCH_RADIUS_M)

BUCKET_SIZE_DEG = 0.02  # ~2.2km lat / ~1.7km lon at NYC latitude


# --------------------------------------------------------------------------
# Pure, DB-free logic (unit-tested in tests/test_roads.py)
# --------------------------------------------------------------------------


def road_class_weight(highway_tag: str | None) -> float:
    """Hierarchy weight for a highway=* tag. Unknown/missing tags default
    to 1.0 (residential-equivalent) — Overpass is only queried for tags in
    VEHICLE_HIGHWAY_TAGS, so an unrecognized tag here would be a genuinely
    unexpected value, not an absent one, and treating it as average-weight
    residential is a safer default than treating it as zero-impact."""
    if highway_tag is None:
        return 1.0
    return ROAD_CLASS_WEIGHTS.get(highway_tag, 1.0)


def is_major_corridor(highway_tag: str | None) -> bool:
    return road_class_weight(highway_tag) >= MAJOR_CLASS_WEIGHT_THRESHOLD


def derive_street_orientation(nearest_highway_tag: str | None) -> str:
    """'facing_corridor' | 'side_street' | 'unknown' — the three literal
    values scoring/engine.py's _apply_street_orientation_damping expects."""
    if nearest_highway_tag is None:
        return "unknown"
    return "facing_corridor" if is_major_corridor(nearest_highway_tag) else "side_street"


def _parse_lanes(raw) -> int | None:
    """OSM `lanes` tag is free-text-ish ('2', '1;2', etc); best-effort parse
    of the first integer, None if it's missing or unparseable."""
    if raw is None:
        return None
    try:
        return int(str(raw).split(";")[0].strip())
    except (ValueError, TypeError):
        return None


def segment_congestion_contribution(
    highway_tag: str | None, distance_m: float, lanes: int | None = None
) -> float:
    weight = road_class_weight(highway_tag)
    narrow_bottleneck_bonus = 0.5 if (lanes is not None and lanes <= 1 and weight >= 2.0) else 0.0
    decay = 1.0 / (1.0 + distance_m / 200.0)
    return (weight + narrow_bottleneck_bonus) * decay


def compute_congestion_proxy_raw(
    nearby_segments: list[dict], radius_m: float = CONGESTION_RADIUS_M
) -> float:
    """nearby_segments: [{"highway": str, "distance_m": float, "lanes": int|None}, ...].
    Higher = worse/more congested (negative-direction raw signal per
    contracts/normalization.md; scoring/engine.py inverts it)."""
    total = 0.0
    for seg in nearby_segments:
        if seg["distance_m"] > radius_m:
            continue
        total += segment_congestion_contribution(seg["highway"], seg["distance_m"], seg.get("lanes"))
    return round(total, 3)


def compute_emergency_corridor_proxy_raw(
    nearby_segments: list[dict], radius_m: float = EMERGENCY_RADIUS_M
) -> float:
    """Same shape as congestion but restricted to major-corridor segments
    only — proxy for "how close is this cell to a road an emergency vehicle
    would use as a through-route." Higher = worse (negative direction)."""
    total = 0.0
    for seg in nearby_segments:
        if seg["distance_m"] > radius_m:
            continue
        highway = seg["highway"]
        if not is_major_corridor(highway):
            continue
        weight = road_class_weight(highway)
        decay = 1.0 / (1.0 + seg["distance_m"] / 150.0)
        total += weight * decay
    return round(total, 3)


def nearest_segment(nearby_segments: list[dict]) -> dict | None:
    if not nearby_segments:
        return None
    return min(nearby_segments, key=lambda s: s["distance_m"])


def bucket_key(lat: float, lon: float, bucket_size_deg: float = BUCKET_SIZE_DEG) -> tuple[int, int]:
    return (math.floor(lat / bucket_size_deg), math.floor(lon / bucket_size_deg))


def index_segments(segments: list[dict]) -> dict[tuple[int, int], list[dict]]:
    """segments: [{"highway": str, "lanes": int|None, "lat": float, "lon": float}, ...]
    (midpoint lat/lon). Buckets by midpoint for fast neighbor lookup."""
    index: dict[tuple[int, int], list[dict]] = {}
    for seg in segments:
        key = bucket_key(seg["lat"], seg["lon"])
        index.setdefault(key, []).append(seg)
    return index


def nearby_segments_with_distance(
    lat: float, lon: float, index: dict[tuple[int, int], list[dict]], max_radius_m: float
) -> list[dict]:
    """Segments from the cell's bucket + 8 neighbors (a 3x3 block, ~5-6km
    across at NYC latitude — comfortably wider than the ~1.22km x 0.61km
    geohash6 cell this is called for), with distance_m computed and
    anything beyond max_radius_m dropped. This is an approximation: a
    segment could in principle be the true nearest one from just outside
    the 3x3 block, but at this bucket size relative to cell size and
    max_radius_m, that's a negligible-edge-case miss for an MVP proxy."""
    base = bucket_key(lat, lon)
    candidates: list[dict] = []
    for d_lat in (-1, 0, 1):
        for d_lon in (-1, 0, 1):
            candidates.extend(index.get((base[0] + d_lat, base[1] + d_lon), []))

    results = []
    for seg in candidates:
        distance_m = haversine_m(lat, lon, seg["lat"], seg["lon"])
        if distance_m <= max_radius_m:
            results.append({**seg, "distance_m": distance_m})
    return results


# --------------------------------------------------------------------------
# Overpass fetch (network I/O — not unit tested, kept thin)
# --------------------------------------------------------------------------


def _build_query(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> str:
    highway_filter = "|".join(sorted(VEHICLE_HIGHWAY_TAGS))
    return f"""
    [out:json][timeout:{OVERPASS_TIMEOUT_S}];
    way["highway"~"^({highway_filter})$"]({min_lat},{min_lon},{max_lat},{max_lon});
    out geom;
    """


def _fetch_bbox(client: httpx.Client, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list[dict]:
    query = _build_query(min_lat, min_lon, max_lat, max_lon)
    # post_overpass_query already retries 429s with backoff internally, so
    # by the time an exception reaches fetch_segments_for_bbox's quadrant-
    # split fallback below, it's a genuine timeout/size problem, never a
    # rate limit misread as "query too big, split and fire 4 more."
    data = post_overpass_query(query, timeout=OVERPASS_TIMEOUT_S + 30, client=client)

    segments: list[dict] = []
    for element in data.get("elements", []):
        if element.get("type") != "way":
            continue
        tags = element.get("tags", {}) or {}
        highway = tags.get("highway")
        if highway not in VEHICLE_HIGHWAY_TAGS:
            continue
        lanes = _parse_lanes(tags.get("lanes"))
        geometry = element.get("geometry") or []
        for a, b in itertools.pairwise(geometry):
            if a is None or b is None:
                continue
            mid_lat = (a["lat"] + b["lat"]) / 2.0
            mid_lon = (a["lon"] + b["lon"]) / 2.0
            segments.append({"highway": highway, "lanes": lanes, "lat": mid_lat, "lon": mid_lon})
    return segments


def fetch_segments_for_bbox(
    client: httpx.Client,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    depth: int = 0,
) -> list[dict]:
    """Fetch road segments for a bbox, adaptively splitting into 4
    quadrants and retrying on timeout/error rather than guessing a fixed
    tile size up front."""
    try:
        return _fetch_bbox(client, min_lat, min_lon, max_lat, max_lon)
    except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
        if depth >= MAX_SPLIT_DEPTH:
            raise
        print(
            f"  Overpass query failed for bbox "
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
                fetch_segments_for_bbox(client, sub_min_lat, sub_max_lat, sub_min_lon, sub_max_lon, depth + 1)
            )
        return segments


# --------------------------------------------------------------------------
# Per-cell classification, using the fetched/indexed segments
# --------------------------------------------------------------------------


def classify_cell(lat: float, lon: float, index: dict[tuple[int, int], list[dict]]) -> dict:
    """Returns the four feature_store fields for one geo_entity."""
    nearby = nearby_segments_with_distance(lat, lon, index, SEARCH_RADIUS_M)
    nearest = nearest_segment([s for s in nearby if s["distance_m"] <= NEAREST_SEARCH_RADIUS_M])
    nearest_highway = nearest["highway"] if nearest else None

    return {
        "road_classification": nearest_highway,
        "congestion_proxy_raw": compute_congestion_proxy_raw(nearby, CONGESTION_RADIUS_M),
        "emergency_corridor_proxy_raw": compute_emergency_corridor_proxy_raw(nearby, EMERGENCY_RADIUS_M),
        "street_orientation": derive_street_orientation(nearest_highway),
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def run() -> None:
    with get_connection() as conn, ingestion_job("osm_roads") as ctx, make_client() as client:
        for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
            print(f"Fetching road segments for {metro_area}...", file=sys.stderr)
            segments = fetch_segments_for_bbox(client, min_lat, max_lat, min_lon, max_lon)
            print(f"  {metro_area}: {len(segments)} road segments", file=sys.stderr)
            index = index_segments(segments)

            metro_rows = 0
            for entity in iter_geo_entities(conn, metro_area=metro_area):
                fields = classify_cell(entity["latitude"], entity["longitude"], index)
                upsert_feature_store(conn, entity["id"], fields)
                metro_rows += 1
                ctx.rows_affected += 1

            conn.commit()
            print(f"  {metro_area}: classified {metro_rows} cells", file=sys.stderr)
            time.sleep(1)  # be polite between metro-area queries

    print(f"osm_roads ingestion complete: {ctx.rows_affected} cells classified.", file=sys.stderr)


if __name__ == "__main__":
    run()
