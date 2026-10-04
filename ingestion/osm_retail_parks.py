"""Shopping and parks/recreation features (v2.1, weights_version
'v2.1-handtuned'; docs/SCORING.md 3.4 and 3.5).

Populates the imperial feature_store columns of migration 0009 for every
geo_entities cell, and the named shops / parks of the `places` table.

Design calls (flag if wrong, easy to change):

- **One Overpass fetch per metro** (quadrant-split on timeout, like
  osm_poi.py) holding every shop of the retail classes below plus every park,
  playground, nature reserve, garden and recreation ground, requested with
  `out center bb tags` so ways and relations carry a centre point AND their
  bounding box. Per-cell values are computed locally with a bucket index.
- **Shopping** = general retail destinations (department stores, malls,
  clothing, home goods, electronics, pharmacies, ...). Groceries and
  convenience stores are scored by their own factors and are excluded.
  - shopping_count_1mi: shops within 1 mile of the cell centre.
  - shopping_nearest_ft: true nearest shop (unbounded).
  - shopping_variety_count_1mi: distinct retail groups (RETAIL_GROUPS) within 1 mile.
  - shopping_raw (0-1) = 0.6 * proximity + 0.4 * variety, where proximity is a
    linear curve on the distance to the THIRD nearest shop (so one outlier
    does not define the score): 1 within 0.5 mi, 0 at 6 mi.
    The Whole Foods / Starbucks / Target anchor bonus is added at scoring time
    from the existing premium_retail_raw (scoring.engine.shopping_goodness).
- **Parks**: OSM leisure=park|playground|nature_reserve|garden and
  landuse=recreation_ground, skipping access=private|no. A way or relation is
  treated as a rectangle: its bounding box shrunk around the centre by
  sqrt(PARK_FILL_FACTOR) per side, so its area is bbox area * 0.65 and distance
  to a big park is distance to its (shrunk) edge, not to its centre. Nodes
  (mostly playgrounds) have no area. Approximate by design.
  - park_nearest_ft: distance to the nearest park footprint (0 inside one).
  - park_count_1mi: parks within 1 mile.
  - park_largest_sq_ft_half_mi: area of the largest park within half a mile.
  - recreation_raw (0-1) = 2/3 * proximity + 1/3 * size. Proximity: 1 within
    1,015 ft (about a 5-minute walk allowing 1.3x street circuity), 0 at
    4,062 ft (20 minutes). Size: log scale from a pocket park (0.1 acre = 0)
    to 20 acres or more (= 1). This is the PARK half of the Recreation factor;
    scoring.engine blends in the existing trail features 75 / 25.
- **Places**: named shops (category 'shopping') and named parks (category
  'park') under their own sources ('osm_retail', 'osm_parks'), so
  replace_places never wipes the 'osm' rows owned by ingestion.osm_poi.

Everything that does not touch the network or the DB is a pure function,
unit tested in tests/test_osm_retail_parks.py.
"""

import math
import sys

from common.db import get_connection, iter_geo_entities, upsert_feature_store
from common.geo import haversine_m
from common.ingestion_log import ingestion_job
from common.overpass import fetch_with_quadrant_split, post_overpass_query
from common.places import Place, clean_name, replace_places
from ingestion.grid import BOUNDING_BOXES

OVERPASS_TIMEOUT_S = 180
HTTP_TIMEOUT_S = OVERPASS_TIMEOUT_S + 30

FT_PER_M = 3.280839895
FT_PER_MI = 5280.0
SQ_FT_PER_ACRE = 43_560.0

SHOPPING_SOURCE = "osm_retail"
PARKS_SOURCE = "osm_parks"

# OSM shop=* value -> retail group. Variety counts distinct groups.
RETAIL_GROUPS: dict[str, str] = {
    "department_store": "department",
    "mall": "department",
    "clothes": "apparel",
    "shoes": "apparel",
    "boutique": "apparel",
    "fashion_accessories": "apparel",
    "bag": "apparel",
    "jewelry": "apparel",
    "watches": "apparel",
    "doityourself": "home",
    "hardware": "home",
    "furniture": "home",
    "interior_decoration": "home",
    "houseware": "home",
    "bed": "home",
    "kitchen": "home",
    "garden_centre": "home",
    "electronics": "electronics",
    "computer": "electronics",
    "mobile_phone": "electronics",
    "chemist": "personal_care",
    "beauty": "personal_care",
    "cosmetics": "personal_care",
    "perfumery": "personal_care",
    "variety_store": "general",
    "general": "general",
    "gift": "general",
    "books": "general",
    "sports": "general",
    "toys": "general",
    "stationery": "general",
    "art": "general",
    "music": "general",
    "outdoor": "general",
}
RETAIL_GROUP_COUNT = len(set(RETAIL_GROUPS.values()))

PARK_LEISURE_VALUES = ("park", "playground", "nature_reserve", "garden")
PARK_LANDUSE_VALUES = ("recreation_ground",)
PRIVATE_ACCESS = frozenset({"private", "no"})

COUNT_RADIUS_FT = FT_PER_MI  # 1 mile
LARGEST_PARK_RADIUS_FT = FT_PER_MI / 2  # half a mile
SHOP_KTH_NEAREST = 3

# shopping_raw
SHOP_PROX_FULL_FT = 0.5 * FT_PER_MI
SHOP_PROX_ZERO_FT = 6.0 * FT_PER_MI
SHOP_PROX_WEIGHT = 0.6
SHOP_VARIETY_WEIGHT = 0.4

# recreation_raw (park half)
PARK_PROX_FULL_FT = 1015.0  # 5 min walk at 3 mph (264 ft/min) with 1.3x circuity
PARK_PROX_ZERO_FT = 4062.0  # 20 min
PARK_SIZE_MIN_SQ_FT = 0.1 * SQ_FT_PER_ACRE
PARK_SIZE_MAX_SQ_FT = 20.0 * SQ_FT_PER_ACRE
PARK_PROX_WEIGHT = 2 / 3
PARK_SIZE_WEIGHT = 1 / 3
PARK_FILL_FACTOR = 0.65  # footprint area as a share of the bounding box

BUCKET_DEG = 0.01
MAX_INDEXED_BUCKETS = 900  # footprints spanning more buckets go in a linear list
RINGS = (2, 4, 8, 16, 32)  # ring 2 (5x5 buckets) already covers a 1 mile radius


# --------------------------------------------------------------------------
# Pure logic
# --------------------------------------------------------------------------


def build_overpass_query(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> str:
    """Shops of the retail classes plus parks, one union, `out center bb tags`."""
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    shops = "|".join(sorted(RETAIL_GROUPS))
    leisure = "|".join(PARK_LEISURE_VALUES)
    landuse = "|".join(PARK_LANDUSE_VALUES)
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n(\n"
        f'  nwr["shop"~"^({shops})$"]({bbox});\n'
        f'  nwr["leisure"~"^({leisure})$"]({bbox});\n'
        f'  nwr["landuse"~"^({landuse})$"]({bbox});\n'
        ");\nout center bb tags;"
    )


def is_park(tags: dict) -> bool:
    if tags.get("access") in PRIVATE_ACCESS:
        return False
    return tags.get("leisure") in PARK_LEISURE_VALUES or tags.get("landuse") in PARK_LANDUSE_VALUES


def retail_group(tags: dict) -> str | None:
    return RETAIL_GROUPS.get(tags.get("shop") or "")


def _element_center(el: dict) -> tuple[float, float] | None:
    if el.get("type") == "node" or ("lat" in el and "lon" in el):
        lat, lon = el.get("lat"), el.get("lon")
    else:
        center = el.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
        bounds = el.get("bounds") or {}
        if (lat is None or lon is None) and all(
            bounds.get(k) is not None for k in ("minlat", "minlon", "maxlat", "maxlon")
        ):
            # `out center bb` returns only the bounds for ways and relations.
            lat = (float(bounds["minlat"]) + float(bounds["maxlat"])) / 2
            lon = (float(bounds["minlon"]) + float(bounds["maxlon"])) / 2
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def footprint_rect(
    center: tuple[float, float], bounds: dict | None
) -> tuple[float, float, float, float, float]:
    """(min_lat, min_lon, max_lat, max_lon, area_sq_ft) of a park footprint:
    the bounding box shrunk around its centre by sqrt(PARK_FILL_FACTOR) per
    side (area = bbox area * PARK_FILL_FACTOR). A point (no bounds) has zero area."""
    lat, lon = center
    if not bounds or any(bounds.get(k) is None for k in ("minlat", "minlon", "maxlat", "maxlon")):
        return lat, lon, lat, lon, 0.0
    min_lat, max_lat = float(bounds["minlat"]), float(bounds["maxlat"])
    min_lon, max_lon = float(bounds["minlon"]), float(bounds["maxlon"])
    mid_lat, mid_lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
    shrink = math.sqrt(PARK_FILL_FACTOR)
    half_lat = (max_lat - min_lat) / 2 * shrink
    half_lon = (max_lon - min_lon) / 2 * shrink
    height_ft = (max_lat - min_lat) * 111_320.0 * FT_PER_M
    width_ft = (max_lon - min_lon) * 111_320.0 * math.cos(math.radians(mid_lat)) * FT_PER_M
    area = max(0.0, height_ft * width_ft * PARK_FILL_FACTOR)
    return mid_lat - half_lat, mid_lon - half_lon, mid_lat + half_lat, mid_lon + half_lon, area


def parse_elements(data: dict) -> tuple[list[tuple], list[tuple], list[Place], list[Place]]:
    """Raw Overpass JSON -> (shops, parks, shop places, park places).

    shops: (lat, lon, group). parks: (min_lat, min_lon, max_lat, max_lon, area_sq_ft).
    Places: one per named element (unnamed ones still count for scoring)."""
    shops: list[tuple] = []
    parks: list[tuple] = []
    shop_places: list[Place] = []
    park_places: list[Place] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        center = _element_center(el)
        if center is None:
            continue
        name = clean_name(tags.get("name"))
        source_id = f"{el.get('type')}/{el.get('id')}"
        group = retail_group(tags)
        if group is not None:
            shops.append((center[0], center[1], group))
            if name and el.get("id") is not None:
                shop_places.append(
                    Place(SHOPPING_SOURCE, source_id, "shopping", name, center[0], center[1],
                          tags.get("brand"))
                )  # fmt: skip
        if is_park(tags):
            rect = footprint_rect(center, el.get("bounds"))
            parks.append(rect)
            if name and el.get("id") is not None:
                lat, lon = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
                park_places.append(Place(PARKS_SOURCE, source_id, "park", name, lat, lon))
    return shops, parks, shop_places, park_places


def linear_curve(value: float, full: float, zero: float) -> float:
    """1.0 at or below `full`, 0.0 at or above `zero`, linear between."""
    if value <= full:
        return 1.0
    if value >= zero:
        return 0.0
    return (zero - value) / (zero - full)


def shopping_raw(kth_nearest_ft: float | None, variety_count: int) -> float | None:
    """0-1: 60% proximity (curve on the k-th nearest shop) + 40% variety
    (distinct retail groups within a mile over RETAIL_GROUP_COUNT). None when
    there are no shops at all."""
    if kth_nearest_ft is None:
        return None
    proximity = linear_curve(kth_nearest_ft, SHOP_PROX_FULL_FT, SHOP_PROX_ZERO_FT)
    variety = min(1.0, variety_count / RETAIL_GROUP_COUNT)
    return SHOP_PROX_WEIGHT * proximity + SHOP_VARIETY_WEIGHT * variety


def park_size_score(area_sq_ft: float | None) -> float:
    """0-1 log scale: 0 at a pocket park (0.1 acre), 1 at 20 acres or more."""
    if not area_sq_ft or area_sq_ft <= PARK_SIZE_MIN_SQ_FT:
        return 0.0
    if area_sq_ft >= PARK_SIZE_MAX_SQ_FT:
        return 1.0
    return math.log(area_sq_ft / PARK_SIZE_MIN_SQ_FT) / math.log(
        PARK_SIZE_MAX_SQ_FT / PARK_SIZE_MIN_SQ_FT
    )


def recreation_raw(nearest_ft: float | None, largest_sq_ft: float | None) -> float | None:
    """0-1 park half of Recreation: 2/3 proximity + 1/3 size of the largest
    park within half a mile. None when there are no parks at all."""
    if nearest_ft is None:
        return None
    proximity = linear_curve(nearest_ft, PARK_PROX_FULL_FT, PARK_PROX_ZERO_FT)
    return PARK_PROX_WEIGHT * proximity + PARK_SIZE_WEIGHT * park_size_score(largest_sq_ft)


def distance_to_rect_ft(
    lat: float, lon: float, rect: tuple[float, float, float, float, float]
) -> float:
    """Feet from a point to a footprint rectangle (0 when inside)."""
    min_lat, min_lon, max_lat, max_lon, _ = rect
    clamped_lat = min(max(lat, min_lat), max_lat)
    clamped_lon = min(max(lon, min_lon), max_lon)
    return haversine_m(lat, lon, clamped_lat, clamped_lon) * FT_PER_M


class GridIndex:
    """Bucket index of items with a bounding rectangle (a point is a
    zero-size rectangle). Each item is stored in every bucket its rectangle
    overlaps, so any item within a block of buckets is found from that block;
    rectangles spanning more than MAX_INDEXED_BUCKETS go in `big`, scanned
    linearly (a few dozen huge reserves)."""

    def __init__(self, bucket_deg: float = BUCKET_DEG):
        self.bucket_deg = bucket_deg
        self.buckets: dict[tuple[int, int], list] = {}
        self.big: list = []
        self.count = 0

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return math.floor(lat / self.bucket_deg), math.floor(lon / self.bucket_deg)

    def add(self, item, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> None:
        self.count += 1
        k0, k1 = self._key(min_lat, min_lon), self._key(max_lat, max_lon)
        if (k1[0] - k0[0] + 1) * (k1[1] - k0[1] + 1) > MAX_INDEXED_BUCKETS:
            self.big.append(item)
            return
        for i in range(k0[0], k1[0] + 1):
            for j in range(k0[1], k1[1] + 1):
                self.buckets.setdefault((i, j), []).append(item)

    def near(self, lat: float, lon: float, ring: int) -> list:
        """Distinct items in the (2*ring+1)^2 bucket block around the point,
        plus every `big` item."""
        cx, cy = self._key(lat, lon)
        seen: set[int] = set()
        out = []
        for i in range(cx - ring, cx + ring + 1):
            for j in range(cy - ring, cy + ring + 1):
                for item in self.buckets.get((i, j), ()):
                    if id(item) not in seen:
                        seen.add(id(item))
                        out.append(item)
        for item in self.big:
            if id(item) not in seen:
                out.append(item)
        return out


def _margin_ft(lat: float, ring: int, bucket_deg: float = BUCKET_DEG) -> float:
    """Feet from a point to the edge of its (2*ring+1)^2 block, worst case."""
    lon_ft = bucket_deg * 111_320.0 * math.cos(math.radians(min(abs(lat), 80.0))) * FT_PER_M
    return ring * min(lon_ft, bucket_deg * 111_320.0 * FT_PER_M)


def build_shop_index(shops: list[tuple]) -> GridIndex:
    index = GridIndex()
    for shop in shops:
        index.add(shop, shop[0], shop[1], shop[0], shop[1])
    return index


def build_park_index(parks: list[tuple]) -> GridIndex:
    index = GridIndex()
    for rect in parks:
        index.add(rect, rect[0], rect[1], rect[2], rect[3])
    return index


def shop_features(cell_lat: float, cell_lon: float, index: GridIndex) -> dict:
    """shopping_* columns for one cell. All None/0 when the metro has no shops."""
    if index.count == 0:
        return {
            "shopping_count_1mi": 0, "shopping_nearest_ft": None,
            "shopping_variety_count_1mi": 0, "shopping_raw": None,
        }  # fmt: skip
    dists: list[tuple[float, str]] = []
    for ring in RINGS:
        dists = sorted(
            (haversine_m(cell_lat, cell_lon, s[0], s[1]) * FT_PER_M, s[2])
            for s in index.near(cell_lat, cell_lon, ring)
        )
        k = min(SHOP_KTH_NEAREST, index.count)
        if len(dists) >= k and dists[k - 1][0] <= _margin_ft(cell_lat, ring):
            break
    within = [(d, g) for d, g in dists if d <= COUNT_RADIUS_FT]
    kth = dists[min(SHOP_KTH_NEAREST, len(dists)) - 1][0] if dists else None
    variety = len({g for _, g in within})
    return {
        "shopping_count_1mi": len(within),
        "shopping_nearest_ft": dists[0][0] if dists else None,
        "shopping_variety_count_1mi": variety,
        "shopping_raw": shopping_raw(kth, variety),
    }


def park_features(cell_lat: float, cell_lon: float, index: GridIndex) -> dict:
    """park_* columns and recreation_raw for one cell."""
    if index.count == 0:
        return {
            "park_count_1mi": 0, "park_nearest_ft": None,
            "park_largest_sq_ft_half_mi": None, "recreation_raw": None,
        }  # fmt: skip
    found: list[tuple[float, tuple]] = []
    for ring in RINGS:
        found = sorted(
            (
                (distance_to_rect_ft(cell_lat, cell_lon, p), p)
                for p in index.near(cell_lat, cell_lon, ring)
            ),
            key=lambda item: item[0],
        )
        if found and found[0][0] <= _margin_ft(cell_lat, ring):
            break
    nearest = found[0][0] if found else None
    count = sum(1 for d, _ in found if d <= COUNT_RADIUS_FT)
    sizes = [p[4] for d, p in found if d <= LARGEST_PARK_RADIUS_FT]
    largest = max(sizes) if sizes else None
    return {
        "park_count_1mi": count,
        "park_nearest_ft": nearest,
        "park_largest_sq_ft_half_mi": largest,
        "recreation_raw": recreation_raw(nearest, largest),
    }


def compute_cell_features(
    cell_lat: float, cell_lon: float, shop_index: GridIndex, park_index: GridIndex
) -> dict:
    return {
        **shop_features(cell_lat, cell_lon, shop_index),
        **park_features(cell_lat, cell_lon, park_index),
    }


# --------------------------------------------------------------------------
# Thin DB / network glue (not unit tested)
# --------------------------------------------------------------------------


def fetch_overpass_data(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> dict:
    def fetch(lat0: float, lat1: float, lon0: float, lon1: float) -> dict:
        return post_overpass_query(
            build_overpass_query(lat0, lat1, lon0, lon1), timeout=HTTP_TIMEOUT_S
        )

    return fetch_with_quadrant_split(fetch, min_lat, max_lat, min_lon, max_lon)


def run() -> None:
    with get_connection() as conn, ingestion_job("osm_retail_parks") as ctx:
        cells_by_metro: dict[str, list[dict]] = {}
        for cell in iter_geo_entities(conn):
            cells_by_metro.setdefault(cell["metro_area"], []).append(cell)

        rows_written = 0
        shop_places: dict[tuple[str, str], Place] = {}
        park_places: dict[tuple[str, str], Place] = {}
        for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
            cells = cells_by_metro.get(metro_area, [])
            if not cells:
                continue
            print(
                f"osm_retail_parks: fetching {metro_area} ({len(cells)} cells)...", file=sys.stderr
            )
            data = fetch_overpass_data(min_lat, max_lat, min_lon, max_lon)
            shops, parks, s_places, p_places = parse_elements(data)
            for place in s_places:
                shop_places.setdefault((place.source_id, place.category), place)
            for place in p_places:
                park_places.setdefault((place.source_id, place.category), place)
            shop_index, park_index = build_shop_index(shops), build_park_index(parks)
            for cell in cells:
                upsert_feature_store(
                    conn,
                    cell["id"],
                    compute_cell_features(
                        cell["latitude"], cell["longitude"], shop_index, park_index
                    ),
                )
                rows_written += 1
            conn.commit()
            ctx.rows_affected = rows_written

        for source, places in ((SHOPPING_SOURCE, shop_places), (PARKS_SOURCE, park_places)):
            if places:
                n = replace_places(conn, source, list(places.values()))
                print(f"osm_retail_parks: wrote {n} {source} places.", file=sys.stderr)

    print(
        f"osm_retail_parks: wrote feature_store rows for {rows_written} geo_entities.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    run()
