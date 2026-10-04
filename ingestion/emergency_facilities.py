"""Facility-aware emergency-corridor signal (v2).

Populates feature_store.emergency_facility_count_1600m,
emergency_facility_nearest_m and emergency_corridor_facility_raw (higher =
worse; scoring/engine.py negates it, damps it by street_orientation, and
falls back to the legacy emergency_corridor_proxy_raw when it is NULL).

v2.1 note: the gas station / convenience store adjacency penalty (full within
300 ft, linear to 0 at 800 ft) is NOT stored here. It needs the nearest-station
columns written by ingestion.osm_poi, so scoring.engine.noise_corridor_goodness
adds it at scoring time on top of this raw signal (a pure function there).

Run order / design call: roads.run() already fetches each metro's road
network, so it calls into this module (fetch_facilities_for_bbox +
compute_emergency_features) and writes the new columns in the same upsert
as the legacy road columns -- the road network is never fetched twice.
`python -m ingestion.emergency_facilities` is a standalone entry point
(re-fetches roads too) for re-running just this signal; the weekly workflow
does NOT need a separate step because `ingestion.roads` already covers it.
If the facility fetch fails for a metro, roads.run() writes only the legacy
columns, so the new columns stay NULL (never 0) and the engine falls back.

Sources: OSM amenity=fire_station|hospital|police and
emergency=ambulance_station (uniform coverage of all six regions). Facilities
may be nodes or ways/relations (`out center`).

Weights: fire station / ambulance station / hospital with emergency=yes 1.0;
other hospitals 0.6 (emergency=no hospitals included at 0.6; unknown
treated as other); police 0.5.

Formula:
  f(segment) = 1 + min(2, SUM_fac w * max(0, 1 - d/2000))   d = midpoint->facility
  corridor   = SUM over MAJOR segments (class_weight >= 3) within 500 m of
               class_weight * f / (1 + dist/150)
  facility   = SUM over facilities within 400 m of w / (1 + d/150)
  emergency_corridor_facility_raw = corridor + facility
Count = facilities within 1600 m; nearest = true nearest (unbounded, None if
the metro has none).
"""

import math
import sys
import time

import httpx

from common.geo import haversine_m
from common.ingestion_log import ingestion_job
from common.overpass import make_client, post_overpass_query
from ingestion.grid import BOUNDING_BOXES
from ingestion.roads import (
    BUCKET_SIZE_DEG,
    EMERGENCY_RADIUS_M,
    MAJOR_CLASS_WEIGHT_THRESHOLD,
    MAX_SPLIT_DEPTH,
    OVERPASS_TIMEOUT_S,
    SEARCH_RADIUS_M,
    bucket_key,
    index_segments,
    nearby_segments_with_distance,
    road_class_weight,
)

FACILITY_INFLUENCE_RADIUS_M = 2000.0
FACILITY_FACTOR_CAP = 2.0  # f = 1 + min(2, ...) -> f in [1, 3]
FACILITY_NEAR_RADIUS_M = 400.0
FACILITY_COUNT_RADIUS_M = 1600.0
DEDUPE_RADIUS_M = 75.0

WEIGHT_FIRE = 1.0
WEIGHT_HOSPITAL_EMERGENCY = 1.0
WEIGHT_HOSPITAL_OTHER = 0.6
WEIGHT_POLICE = 0.5


# --------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_emergency_facilities.py)
# --------------------------------------------------------------------------


def facility_weight(tags: dict) -> float | None:
    """Weight for an OSM element's tags, None if it isn't an emergency facility."""
    if tags.get("amenity") == "fire_station" or tags.get("emergency") == "ambulance_station":
        return WEIGHT_FIRE
    if tags.get("amenity") == "hospital":
        return (
            WEIGHT_HOSPITAL_EMERGENCY if tags.get("emergency") == "yes" else WEIGHT_HOSPITAL_OTHER
        )
    if tags.get("amenity") == "police":
        return WEIGHT_POLICE
    return None


def parse_facilities(elements: list[dict]) -> list[dict]:
    """Overpass `out center tags` elements -> [{"lat","lon","weight"}].
    Nodes carry lat/lon; ways/relations carry a `center`."""
    out = []
    for el in elements:
        weight = facility_weight(el.get("tags") or {})
        if weight is None:
            continue
        if el.get("type") == "node" or "lat" in el:
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        if lat is None or lon is None:
            continue
        out.append({"lat": float(lat), "lon": float(lon), "weight": weight})
    return out


def dedupe_facilities(facilities: list[dict]) -> list[dict]:
    """Drops same-weight facilities within DEDUPE_RADIUS_M (a node plus its
    building way, or the same site mapped twice). Deterministic: input is
    sorted by (lat, lon, weight) first."""
    kept: list[dict] = []
    index: dict[tuple[int, int], list[dict]] = {}
    for fac in sorted(facilities, key=lambda f: (f["lat"], f["lon"], f["weight"])):
        base = bucket_key(fac["lat"], fac["lon"])
        dup = False
        for dl in (-1, 0, 1):
            for dn in (-1, 0, 1):
                for other in index.get((base[0] + dl, base[1] + dn), []):
                    if (
                        other["weight"] == fac["weight"]
                        and haversine_m(fac["lat"], fac["lon"], other["lat"], other["lon"])
                        <= DEDUPE_RADIUS_M
                    ):
                        dup = True
        if not dup:
            kept.append(fac)
            index.setdefault(base, []).append(fac)
    return kept


def index_facilities(facilities: list[dict]) -> dict[tuple[int, int], list[dict]]:
    return index_segments(facilities)


def _facilities_in_radius(lat, lon, facilities, radius_m) -> list[tuple[dict, float]]:
    """(facility, distance) pairs within radius_m. `facilities` may be a
    plain list or a bucket index (dict); radius must be <= ~2 km for the
    3x3 bucket block to be exhaustive."""
    if isinstance(facilities, dict):
        found = nearby_segments_with_distance(lat, lon, facilities, radius_m)
        return [(f, f["distance_m"]) for f in found]
    out = []
    for f in facilities:
        d = haversine_m(lat, lon, f["lat"], f["lon"])
        if d <= radius_m:
            out.append((f, d))
    return out


def segment_facility_factor(lat: float, lon: float, facilities) -> float:
    """f in [1, 3]: 1 + min(2, SUM w * max(0, 1 - d/2000))."""
    total = 0.0
    for fac, d in _facilities_in_radius(lat, lon, facilities, FACILITY_INFLUENCE_RADIUS_M):
        total += fac["weight"] * max(0.0, 1.0 - d / FACILITY_INFLUENCE_RADIUS_M)
    return 1.0 + min(FACILITY_FACTOR_CAP, total)


def annotate_segments_with_factor(segments: list[dict], facility_index) -> list[dict]:
    """Adds "facility_factor" to major segments only (minor ones never
    contribute, so skipping them saves most of the work). Returns new dicts."""
    out = []
    for seg in segments:
        if road_class_weight(seg["highway"]) < MAJOR_CLASS_WEIGHT_THRESHOLD:
            out.append(seg)
            continue
        out.append(
            {
                **seg,
                "facility_factor": segment_facility_factor(seg["lat"], seg["lon"], facility_index),
            }
        )
    return out


def nearest_facility_m(lat: float, lon: float, facility_index: dict) -> float | None:
    """True nearest distance, unbounded. Expanding bucket rings; stops once
    the best found is closer than the minimum width of the rings scanned."""
    if not facility_index:
        return None
    min_cell_m = BUCKET_SIZE_DEG * 111_320.0 * math.cos(math.radians(min(abs(lat), 80.0)))
    keys = list(facility_index)
    base = bucket_key(lat, lon)
    max_ring = max(max(abs(k[0] - base[0]), abs(k[1] - base[1])) for k in keys)
    best: float | None = None
    for r in range(max_ring + 1):
        for (bl, bn), facs in facility_index.items():
            if max(abs(bl - base[0]), abs(bn - base[1])) != r:
                continue
            for f in facs:
                d = haversine_m(lat, lon, f["lat"], f["lon"])
                if best is None or d < best:
                    best = d
        if best is not None and best <= r * min_cell_m:
            break
    return best


def compute_facility_features(cell_lat: float, cell_lon: float, facilities) -> dict:
    """Facility-only part for one cell: count within 1600 m, true nearest
    (None if no facilities), and the driveway term SUM w/(1+d/150) within
    400 m. `facilities` is a list or a bucket index (use index for speed)."""
    index = facilities if isinstance(facilities, dict) else index_facilities(facilities)
    within = _facilities_in_radius(cell_lat, cell_lon, index, FACILITY_COUNT_RADIUS_M)
    near_term = sum(
        f["weight"] / (1.0 + d / 150.0) for f, d in within if d <= FACILITY_NEAR_RADIUS_M
    )
    return {
        "emergency_facility_count_1600m": len(within),
        "emergency_facility_nearest_m": nearest_facility_m(cell_lat, cell_lon, index),
        "facility_term": round(near_term, 3),
    }


def compute_corridor_facility_term(
    nearby_segments: list[dict], radius_m: float = EMERGENCY_RADIUS_M
) -> float:
    """SUM over major segments within radius of class_weight * f / (1+d/150).
    Segments lacking facility_factor are treated as f=1."""
    total = 0.0
    for seg in nearby_segments:
        if seg["distance_m"] > radius_m:
            continue
        weight = road_class_weight(seg["highway"])
        if weight < MAJOR_CLASS_WEIGHT_THRESHOLD:
            continue
        total += weight * seg.get("facility_factor", 1.0) / (1.0 + seg["distance_m"] / 150.0)
    return total


def compute_emergency_features(
    lat: float, lon: float, road_index: dict, facility_index: dict
) -> dict:
    """The three new feature_store fields for one cell. road_index segments
    should have been passed through annotate_segments_with_factor."""
    nearby = nearby_segments_with_distance(lat, lon, road_index, SEARCH_RADIUS_M)
    fac = compute_facility_features(lat, lon, facility_index)
    raw = compute_corridor_facility_term(nearby) + fac["facility_term"]
    return {
        "emergency_facility_count_1600m": fac["emergency_facility_count_1600m"],
        "emergency_facility_nearest_m": fac["emergency_facility_nearest_m"],
        "emergency_corridor_facility_raw": round(raw, 3),
    }


# --------------------------------------------------------------------------
# Overpass fetch (network I/O, thin)
# --------------------------------------------------------------------------


def _build_query(min_lat, min_lon, max_lat, max_lon) -> str:
    bbox = f"({min_lat},{min_lon},{max_lat},{max_lon})"
    return f"""
    [out:json][timeout:{OVERPASS_TIMEOUT_S}];
    (
      nwr["amenity"~"^(fire_station|hospital|police)$"]{bbox};
      nwr["emergency"="ambulance_station"]{bbox};
    );
    out center tags;
    """


def fetch_facilities_for_bbox(
    client: httpx.Client,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    depth: int = 0,
) -> list[dict]:
    """Facilities for a bbox, quadrant-splitting on timeout like roads.py."""
    try:
        data = post_overpass_query(
            _build_query(min_lat, min_lon, max_lat, max_lon),
            timeout=OVERPASS_TIMEOUT_S + 30,
            client=client,
        )
        return parse_facilities(data.get("elements", []))
    except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
        if depth >= MAX_SPLIT_DEPTH:
            raise
        print(f"  facility query failed at depth {depth} ({exc}); splitting", file=sys.stderr)
        mid_lat, mid_lon = (min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0
        out: list[dict] = []
        for a, b, c, d in (
            (min_lat, mid_lat, min_lon, mid_lon),
            (min_lat, mid_lat, mid_lon, max_lon),
            (mid_lat, max_lat, min_lon, mid_lon),
            (mid_lat, max_lat, mid_lon, max_lon),
        ):
            time.sleep(1)
            out.extend(fetch_facilities_for_bbox(client, a, b, c, d, depth + 1))
        return out


def fetch_facility_index(client, min_lat, max_lat, min_lon, max_lon) -> dict:
    return index_facilities(
        dedupe_facilities(fetch_facilities_for_bbox(client, min_lat, max_lat, min_lon, max_lon))
    )


# --------------------------------------------------------------------------
# Standalone entry point
# --------------------------------------------------------------------------


def run() -> None:
    from common.db import get_connection, iter_geo_entities, upsert_feature_store
    from ingestion.roads import fetch_segments_for_bbox

    with (
        get_connection() as conn,
        ingestion_job("osm_emergency_facilities") as ctx,
        make_client() as client,
    ):
        for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
            print(f"Fetching facilities + roads for {metro_area}...", file=sys.stderr)
            fac_index = fetch_facility_index(client, min_lat, max_lat, min_lon, max_lon)
            time.sleep(1)
            segments = fetch_segments_for_bbox(client, min_lat, max_lat, min_lon, max_lon)
            road_index = index_segments(annotate_segments_with_factor(segments, fac_index))
            for entity in iter_geo_entities(conn, metro_area=metro_area):
                upsert_feature_store(
                    conn,
                    entity["id"],
                    compute_emergency_features(
                        entity["latitude"], entity["longitude"], road_index, fac_index
                    ),
                )
                ctx.rows_affected += 1
            conn.commit()
            time.sleep(1)
    print(f"emergency facilities complete: {ctx.rows_affected} cells.", file=sys.stderr)


if __name__ == "__main__":
    run()
