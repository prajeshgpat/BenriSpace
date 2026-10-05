"""On-demand scoring at an exact (lat, lon), with no per-cell storage.

A grid cell stores raw features computed at its centroid (ingestion/*), and the
`scores` table holds the cell's normalized scores. This module builds the SAME
raw feature dict (the keys scoring.engine reads) for an arbitrary point from live
PostGIS queries on `places`, then normalizes it with the metro's stored scales
(scoring/scales.py), so a point is scored exactly the way a cell is.

Where each raw feature comes from
---------------------------------
LIVE at the point (one SQL statement, `build_live_sql`; KNN + ST_DWithin-style
box counts on places.geom, distances by ST_DistanceSphere):
  grocery, gym, cafe, restaurant, bar   count within 500 m, nearest
  school                                count within 1600 m, nearest
  whole_foods / starbucks / target      nearest -> premium_retail_raw (Shopping anchor)
  airport_drive_time_min                computed: ingestion.airports' own straight-line
                                        fallback (30 mph), which is what production holds
                                        (checked: the stored values match to 0.005 min)

LIVE, ANCHORED on the cell (the stored feature covers more than `places` holds:
`places` keeps only NAMED OSM elements and parks as one centre point, while the
feature_store was computed from every element and from park footprints). For these
the live value is measured at the point AND at the cell centroid, and the stored
cell value is shifted by the difference:
    nearest_point = max(0, stored + clip(live_point - live_centroid, +/- offset))
    count_point   = max(0, stored + live_point - live_centroid)
where offset is the point-to-centroid distance (a nearest-distance function is
1-Lipschitz, so the shift can never exceed it). At the centroid the shift is zero,
so a cell scored at its centroid reproduces its stored value exactly. Anchored:
  grocery, gym, cafe, restaurant, bar, gas_station, convenience_store   count within 500 m,
                     nearest (unnamed OSM elements are missing live)
  transit            count within 800 m, nearest (OSM bus stops with no name are missing live)
  shopping           3rd-nearest shop distance (the stored shopping_raw is inverted back to
                     it when not saturated); retail-group variety is the cell's
  park               nearest park footprint distance (footprints are not in places)

FROM THE CELL (not queryable live; documented fallbacks):
  congestion_proxy_raw (Traffic), emergency_corridor_facility_raw / _proxy_raw and
  street_orientation (Noise Corridor base; its gas / convenience adjacency penalty IS
  live, from the point's own gas and convenience distances), running_trail_* and
  strava_segment_popularity_raw (Recreation's trail half), school_avg_rating_1600m
  (district rating, a polygon lookup), shopping variety, park_largest_sq_ft_half_mi.
  road_segments (migration 0012) is EMPTY in production, so nothing is computed from
  it yet; when it is populated, congestion and the corridor raw can move here.

Everything except `fetch_live` is pure (tests/test_point.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from common.geo import haversine_m
from scoring.scales import Scales, score_row

FT_PER_M = 3.280839895

# category -> radius (m) of the live count. 1 m = no count needed (nearest only).
LIVE_RADIUS_M: dict[str, float] = {
    "grocery": 500.0,
    "gym": 500.0,
    "cafe": 500.0,
    "restaurant": 500.0,
    "bar": 500.0,
    "gas_station": 500.0,
    "convenience_store": 500.0,
    "transit": 800.0,
    "school": 1600.0,
    "shopping": 1.0,
    "park": 1.0,
    "whole_foods": 1.0,
    "starbucks": 1.0,
    "target": 1.0,
}
# category -> (count column, nearest column) for categories used as-is from the live query.
LIVE_PLAIN: dict[str, tuple[str, str]] = {
    "grocery": ("grocery_count_500m", "grocery_nearest_m"),
    "gym": ("gym_count_500m", "gym_nearest_m"),
    "cafe": ("cafe_count_500m", "cafe_nearest_m"),
    "restaurant": ("restaurant_count_500m", "restaurant_nearest_m"),
    "bar": ("bar_count_500m", "bar_nearest_m"),
    "school": ("school_count_1600m", "school_nearest_m"),
}
# Anchored on the cell (see module docstring).
LIVE_ANCHORED: dict[str, tuple[str, str]] = {
    "transit": ("transit_stop_count_800m", "transit_nearest_m"),
    "gas_station": ("gas_station_count_500m", "gas_station_nearest_m"),
    "convenience_store": ("convenience_store_count_500m", "convenience_store_nearest_m"),
}
BRAND_COLUMNS = {
    "whole_foods": "whole_foods_nearest_m",
    "starbucks": "starbucks_nearest_m",
    "target": "target_nearest_m",
}
# Categories measured at the cell centroid too and shifted from the stored value.
# Everything except school (live reproduces it exactly, see school_nearest_in_block) and the
# brand rows (nearest only, a small bonus). The out-of-sample test in
# scripts/validate_point_scoring.py (cross) is why POI categories are anchored too: places
# omits unnamed elements, and anchoring cut grocery / gym / cafe / bar error by 40-60%.
DEFAULT_ANCHOR: frozenset[str] = frozenset(
    {"grocery", "gym", "cafe", "restaurant", "bar", *LIVE_ANCHORED, "shopping", "park"}
)
ALL_ANCHOR: frozenset[str] = frozenset(LIVE_RADIUS_M)
NO_ANCHOR: frozenset[str] = frozenset()
# Stored on the cell, used as-is.
CELL_COLUMNS = (
    "congestion_proxy_raw",
    "emergency_corridor_facility_raw",
    "emergency_corridor_proxy_raw",
    "street_orientation",
    "running_trail_count_800m",
    "running_trail_nearest_m",
    "strava_segment_count_800m",
    "strava_segment_popularity_raw",
    "school_avg_rating_1600m",
    "school_district_rating",
    "emergency_facility_nearest_m",
    "emergency_facility_count_1600m",
)
PARK_SHIFT_WEIGHT = 0.5  # share of the live centroid-to-point change applied to the park distance
KNN_K = 6  # candidates fetched by index-ordered KNN; the true nearest is among them

# --- copies of ingestion constants (ingestion/ is not in the Lambda bundle) ----------
# tests/test_point.py asserts each against its source.
PREMIUM_RETAIL_WEIGHTS = {"whole_foods": 1.0, "starbucks": 1.0, "target": 0.5}
PREMIUM_RETAIL_SCALE_M = 800.0
SHOP_KTH_NEAREST = 3
SHOP_PROX_FULL_FT = 0.5 * 5280.0
SHOP_PROX_ZERO_FT = 6.0 * 5280.0
SHOP_PROX_WEIGHT = 0.6
SHOP_VARIETY_WEIGHT = 0.4
RETAIL_GROUP_COUNT = 6
PARK_PROX_FULL_FT = 1015.0
PARK_PROX_ZERO_FT = 4062.0
PARK_SIZE_MIN_SQ_FT = 0.1 * 43_560.0
PARK_SIZE_MAX_SQ_FT = 20.0 * 43_560.0
PARK_PROX_WEIGHT = 2 / 3
PARK_SIZE_WEIGHT = 1 / 3
AIRPORTS = (
    ("JFK", 40.6413, -73.7781),
    ("LGA", 40.7769, -73.8740),
    ("EWR", 40.6895, -74.1745),
)
AIRPORT_SPEED_KMH = 48.0


@dataclass(frozen=True)
class Live:
    """A live measurement for one (point, category): places within the category
    radius, and the sorted sphere distances (m) of the nearest few."""

    count: int
    distances_m: tuple[float, ...] = ()
    # (lat, lon) of each neighbour in distances_m order (schools need them, see below)
    coords: tuple[tuple[float, float], ...] = ()

    @property
    def nearest_m(self) -> float | None:
        return self.distances_m[0] if self.distances_m else None


# --- live SQL ---------------------------------------------------------------------

PT = "pt"  # measurement at the requested point
CTR = "ctr"  # measurement at the containing cell's stored centroid (anchoring)


def build_live_sql(n_points: int, anchor: frozenset[str] = DEFAULT_ANCHOR) -> str:
    """ONE statement measuring `n_points` points. Params: per point (index, geohash,
    lon, lat); then per category (category, radius_m, anchored).

    The centroid of each point's cell (geo_entities.latitude/longitude, which is NOT
    the geohash centre: the grid is a lat/lon lattice) is looked up inside the
    statement by geohash, so the cell fetch and this query do not depend on each
    other and ride the same pipeline round trip.

    Per (point, category): a box-prefiltered count (GiST on places.geom, exact
    ST_DistanceSphere cut) and the KNN_K index-ordered nearest distances (<->)."""
    pts = ",\n            ".join(["(%s::int, %s::text, %s::float8, %s::float8)"] * n_points)
    cats = ",\n            ".join(["(%s::text, %s::float8, %s::boolean)"] * len(LIVE_RADIUS_M))
    return f"""
        with p(i, geohash, lon, lat) as (values
            {pts}
        ),
        cats(category, radius_m, anchored) as (values
            {cats}
        ),
        pts as (
            select p.i, 'pt' as kind, p.lon, p.lat, p.geohash from p
            union all
            -- one centroid measurement per distinct cell (samples often share a cell),
            -- fanned out to every point of that cell by the final select
            select min(p.i), 'ctr', ge.longitude::float8, ge.latitude::float8, p.geohash
            from p join geo_entities ge on ge.geohash = p.geohash
            where abs(ge.longitude - p.lon) > 1e-9 or abs(ge.latitude - p.lat) > 1e-9
            group by p.geohash, ge.longitude, ge.latitude
        ),
        r as (
            select j.i, j.kind, j.geohash, j.category, cnt.n, nn.ds, nn.lats, nn.lons
            from (
                select pts.i, pts.kind, pts.lon, pts.lat, pts.geohash, cats.category, cats.radius_m
                from pts join cats on pts.kind = 'pt' or cats.anchored
            ) j
            cross join lateral (select st_setsrid(st_makepoint(j.lon, j.lat), 4326) as pt) q
            cross join lateral (
                select count(*)::int as n
                from places pl
                where pl.category = j.category
                  and pl.geom && st_makeenvelope(
                        j.lon - j.radius_m / (111320.0 * cos(radians(j.lat))),
                        j.lat - j.radius_m / 111320.0,
                        j.lon + j.radius_m / (111320.0 * cos(radians(j.lat))),
                        j.lat + j.radius_m / 111320.0, 4326)
                  and st_distancesphere(pl.geom, q.pt) <= j.radius_m
            ) cnt
            cross join lateral (
                select array_agg(k.d order by k.d) as ds,
                       array_agg(k.lat order by k.d) as lats,
                       array_agg(k.lon order by k.d) as lons
                from (
                    select st_distancesphere(pl.geom, q.pt) as d,
                           pl.latitude::float8 as lat, pl.longitude::float8 as lon
                    from places pl
                    where pl.category = j.category
                    order by pl.geom <-> q.pt
                    limit {KNN_K}
                ) k
            ) nn
        )
        select r.i, r.kind, r.category, r.n, r.ds, r.lats, r.lons from r where r.kind = 'pt'
        union all
        select p.i, 'ctr', r.category, r.n, r.ds, r.lats, r.lons
        from r join p on p.geohash = r.geohash where r.kind = 'ctr'
    """


def same_spot(lat1: float, lon1: float, lat2: float, lon2: float) -> bool:
    """True when two coordinates are the same place to ~0.1 mm."""
    return abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9


def live_params(
    points: list[tuple[str, float, float]], anchor: frozenset[str] = DEFAULT_ANCHOR
) -> list:
    """Parameters for build_live_sql: `points` are (geohash, lat, lon)."""
    params: list = []
    for i, (geohash, lat, lon) in enumerate(points):
        params += [i, geohash, lon, lat]
    for category, radius in LIVE_RADIUS_M.items():
        params += [category, radius, category in anchor]
    return params


LiveMap = dict[tuple[int, str, str], Live]


def execute_live(
    cur, points: list[tuple[str, float, float]], anchor: frozenset[str] = DEFAULT_ANCHOR
) -> None:
    """Sends the live query for `points` on a cursor (read the rows with read_live)."""
    cur.execute(build_live_sql(len(points), anchor), live_params(points, anchor))


def fetch_live(
    cur, points: list[tuple[str, float, float]], anchor: frozenset[str] = DEFAULT_ANCHOR
) -> LiveMap:
    execute_live(cur, points, anchor)
    return read_live(cur)


def read_live(cur) -> LiveMap:
    """{(point index, 'pt' | 'ctr', category): Live} from the executed live query."""
    return {
        (int(r["i"]), r["kind"], r["category"]): Live(
            int(r["n"]),
            tuple(float(d) for d in (r["ds"] or [])),
            tuple(zip(r["lats"] or [], r["lons"] or [], strict=True)),
        )
        for r in cur.fetchall()
    }


# --- pure feature builders (mirror ingestion) -------------------------------------


def _f(value) -> float | None:
    return None if value is None else float(value)


def premium_retail_raw(whole_foods_m, starbucks_m, target_m) -> float | None:
    dists = {"whole_foods": whole_foods_m, "starbucks": starbucks_m, "target": target_m}
    if all(d is None for d in dists.values()):
        return None
    return sum(
        PREMIUM_RETAIL_WEIGHTS[k] / (1.0 + d / PREMIUM_RETAIL_SCALE_M)
        for k, d in dists.items()
        if d is not None
    )


def linear_curve(value: float, full: float, zero: float) -> float:
    if value <= full:
        return 1.0
    if value >= zero:
        return 0.0
    return (zero - value) / (zero - full)


def shopping_raw(kth_nearest_ft: float | None, variety_count: float) -> float | None:
    if kth_nearest_ft is None:
        return None
    proximity = linear_curve(kth_nearest_ft, SHOP_PROX_FULL_FT, SHOP_PROX_ZERO_FT)
    variety = min(1.0, variety_count / RETAIL_GROUP_COUNT)
    return SHOP_PROX_WEIGHT * proximity + SHOP_VARIETY_WEIGHT * variety


def park_size_score(area_sq_ft: float | None) -> float:
    if not area_sq_ft or area_sq_ft <= PARK_SIZE_MIN_SQ_FT:
        return 0.0
    if area_sq_ft >= PARK_SIZE_MAX_SQ_FT:
        return 1.0
    return math.log(area_sq_ft / PARK_SIZE_MIN_SQ_FT) / math.log(
        PARK_SIZE_MAX_SQ_FT / PARK_SIZE_MIN_SQ_FT
    )


def recreation_raw(nearest_ft: float | None, largest_sq_ft: float | None) -> float | None:
    if nearest_ft is None:
        return None
    proximity = linear_curve(nearest_ft, PARK_PROX_FULL_FT, PARK_PROX_ZERO_FT)
    return PARK_PROX_WEIGHT * proximity + PARK_SIZE_WEIGHT * park_size_score(largest_sq_ft)


def airport_drive_time_min(lat: float, lon: float) -> float:
    """Minutes to the nearest tier-1 airport by ingestion.airports' straight-line fallback."""
    return min(
        haversine_m(lat, lon, a_lat, a_lon) / 1000.0 / AIRPORT_SPEED_KMH * 60.0
        for _, a_lat, a_lon in AIRPORTS
    )


def anchored_nearest(
    stored: float | None,
    at_point: float | None,
    at_centroid: float | None,
    offset: float,
    weight: float = 1.0,
) -> float | None:
    """Stored nearest distance shifted by the live change from centroid to point
    (clipped to the offset, the most a nearest-distance can move). Same units in
    and out. Without a stored value the live one is used as is."""
    if stored is None:
        return at_point
    if at_point is None or at_centroid is None:
        return stored
    shift = max(-offset, min(offset, at_point - at_centroid)) * weight
    return max(0.0, stored + shift)


def anchored_count(stored, at_point: int, at_centroid: int) -> float:
    if stored is None:
        return float(at_point)
    return max(0.0, float(stored) + at_point - at_centroid)


# ingestion/schools.py searches the nearest school only in the 3x3 block of
# 0.015 x 0.02 degree buckets around the cell, so a cell with none there has
# school_nearest_m = None (the engine then uses its 5 km sentinel).
SCHOOL_LAT_BUCKET_DEG = 0.015
SCHOOL_LON_BUCKET_DEG = 0.02


def school_nearest_in_block(live: Live, lat: float, lon: float) -> float | None:
    """Nearest school distance (m) the way ingestion/schools.py records it: only schools
    in the 3x3 bucket block around (lat, lon) count; None when there is none."""
    bi, bj = math.floor(lat / SCHOOL_LAT_BUCKET_DEG), math.floor(lon / SCHOOL_LON_BUCKET_DEG)
    for d, (s_lat, s_lon) in zip(live.distances_m, live.coords, strict=False):
        if (
            abs(math.floor(s_lat / SCHOOL_LAT_BUCKET_DEG) - bi) <= 1
            and abs(math.floor(s_lon / SCHOOL_LON_BUCKET_DEG) - bj) <= 1
        ):
            return d
    return None


def kth_nearest(live: Live) -> float | None:
    if not live.distances_m:
        return None
    return live.distances_m[min(SHOP_KTH_NEAREST, len(live.distances_m)) - 1]


def _stored_kth_ft(cell: dict) -> float | None:
    """The cell's 3rd-nearest-shop distance (ft), recovered from its stored
    shopping_raw; None when the proximity part saturated (0 or 1) and cannot be inverted."""
    raw = _f(cell.get("shopping_raw"))
    if raw is None:
        return None
    variety = min(1.0, (_f(cell.get("shopping_variety_count_1mi")) or 0.0) / RETAIL_GROUP_COUNT)
    prox = (raw - SHOP_VARIETY_WEIGHT * variety) / SHOP_PROX_WEIGHT
    if prox <= 1e-6 or prox >= 1 - 1e-6:
        return None
    return SHOP_PROX_ZERO_FT - prox * (SHOP_PROX_ZERO_FT - SHOP_PROX_FULL_FT)


@dataclass
class PointFeatures:
    row: dict  # the raw feature dict the engine reads (+ *_nearest_* for explanations)
    from_cell: list[str] = field(default_factory=list)  # cell-only fallbacks used


def _ft(m: float | None) -> float | None:
    return None if m is None else m * FT_PER_M


def build_point_features(
    cell: dict,
    lat: float,
    lon: float,
    live: LiveMap,
    index: int = 0,
    anchor: frozenset[str] = DEFAULT_ANCHOR,
) -> PointFeatures:
    """The raw feature dict for (lat, lon). `cell` is the containing cell's
    feature_store row plus its centroid as 'latitude' / 'longitude'. `live` holds
    read_live results (execute_live with the same `anchor`). Categories in `anchor` are
    shifted from the cell's stored value; the rest use the live value as is
    (NO_ANCHOR = pure live, for measurement and validation)."""
    cell_lat, cell_lon = float(cell["latitude"]), float(cell["longitude"])
    offset = haversine_m(lat, lon, cell_lat, cell_lon)
    at_centroid = same_spot(lat, lon, cell_lat, cell_lon)

    def pt(category: str) -> Live:
        return live.get((index, PT, category), Live(0))

    def ctr(category: str) -> Live:
        # at the centroid (or with no centroid row) the point's own measurement serves
        if at_centroid:
            return pt(category)
        return live.get((index, CTR, category), pt(category))

    row: dict = {}
    for category, (count_col, nearest_col) in {**LIVE_PLAIN, **LIVE_ANCHORED}.items():
        p = pt(category)
        if category in anchor:
            c = ctr(category)
            row[count_col] = anchored_count(cell.get(count_col), p.count, c.count)
            row[nearest_col] = anchored_nearest(
                _f(cell.get(nearest_col)), p.nearest_m, c.nearest_m, offset
            )
        else:
            row[count_col], row[nearest_col] = p.count, p.nearest_m
    row["school_nearest_m"] = school_nearest_in_block(pt("school"), lat, lon)

    for category, column in BRAND_COLUMNS.items():
        row[column] = pt(category).nearest_m
    row["premium_retail_raw"] = premium_retail_raw(
        row["whole_foods_nearest_m"], row["starbucks_nearest_m"], row["target_nearest_m"]
    )

    # Shopping: proximity (3rd-nearest shop) from live data, variety from the cell.
    variety = _f(cell.get("shopping_variety_count_1mi")) or 0.0
    kth_ft = _ft(kth_nearest(pt("shopping")))
    shop_anchored = "shopping" in anchor
    if shop_anchored and cell.get("shopping_raw") is None:
        row["shopping_raw"] = None  # the cell has no shop data: keep "no data"
    else:
        stored_kth_ft = _stored_kth_ft(cell) if shop_anchored else None
        if stored_kth_ft is not None:  # else the proximity part saturated: pure live
            kth_ft = anchored_nearest(
                stored_kth_ft, kth_ft, _ft(kth_nearest(ctr("shopping"))), offset * FT_PER_M
            )
        row["shopping_raw"] = shopping_raw(kth_ft, variety)
    shop_p, shop_c = _ft(pt("shopping").nearest_m), _ft(ctr("shopping").nearest_m)
    row["shopping_nearest_ft"] = (
        anchored_nearest(_f(cell.get("shopping_nearest_ft")), shop_p, shop_c, offset * FT_PER_M)
        if shop_anchored
        else shop_p
    )

    # Recreation (park half): nearest footprint, largest park from the cell.
    park_p, park_c = _ft(pt("park").nearest_m), _ft(ctr("park").nearest_m)
    stored_park_ft = _f(cell.get("park_nearest_ft"))
    if "park" in anchor:
        # a cell with no park data has no park signal; do not invent one
        park_ft = (
            None
            if stored_park_ft is None
            else anchored_nearest(
                stored_park_ft, park_p, park_c, offset * FT_PER_M, PARK_SHIFT_WEIGHT
            )
        )
    else:
        park_ft = park_p
    row["park_nearest_ft"] = park_ft
    row["recreation_raw"] = recreation_raw(park_ft, _f(cell.get("park_largest_sq_ft_half_mi")))

    row["airport_drive_time_min"] = airport_drive_time_min(lat, lon)

    from_cell = []
    for column in CELL_COLUMNS:
        if column in cell:
            row[column] = cell[column]
            from_cell.append(column)
    from_cell += ["shopping_variety_count_1mi", "park_largest_sq_ft_half_mi"]
    return PointFeatures(row, from_cell)


def score_point(
    cell: dict,
    lat: float,
    lon: float,
    live: LiveMap,
    scales: Scales,
    weights_version: str,
    index: int = 0,
    anchor: frozenset[str] = DEFAULT_ANCHOR,
) -> tuple[dict[str, float], dict]:
    """(scores, feature row): scores is {score_column: 0-100, ..., 'composite_score'}
    exactly as scoring.engine would write for a cell; empty when nothing scores."""
    features = build_point_features(cell, lat, lon, live, index, anchor).row
    return score_row(features, weights_version, scales), features


# --- polygons ---------------------------------------------------------------------


def sample_points(
    geometry: dict, inside, n_extra: int = 4, grid: int = 5
) -> list[tuple[float, float]]:
    """Up to 1 + n_extra deterministic (lat, lon) samples inside a GeoJSON polygon:
    the interior point nearest the bounding-box centre, then farthest-point picks from
    a grid x grid lattice clipped to the polygon (so the samples spread out).
    `inside(lon, lat, geometry)` is api.areas.point_in_polygon."""
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords):
        if coords and isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
            return
        for c in coords:
            walk(c)

    walk(geometry.get("coordinates", []))
    if not xs:
        return []
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
    lattice = [
        (min_x + (i + 0.5) / grid * (max_x - min_x), min_y + (j + 0.5) / grid * (max_y - min_y))
        for i in range(grid)
        for j in range(grid)
    ]
    candidates = [(x, y) for x, y in lattice if inside(x, y, geometry)]
    if not candidates:
        return []
    candidates.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    chosen = [candidates.pop(0)]
    while candidates and len(chosen) < 1 + n_extra:
        best = max(
            candidates, key=lambda p: min((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for q in chosen)
        )
        candidates.remove(best)
        chosen.append(best)
    return [(y, x) for x, y in chosen]
