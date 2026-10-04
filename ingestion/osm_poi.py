"""Populates feature_store's OSM Overpass-derived POI columns: grocery,
gym, cafe, gas_station, convenience_store, plus (v2) restaurant and bar
(count + nearest), brand-specific nearest distances (Whole Foods, Starbucks,
Target) and the derived premium_retail_raw score, for every geo_entities
cell in the v1 metro.

Design calls made here (flag if wrong, easy to change):

- **Query Overpass once per metro_area, not once per grid cell.** There are
  ~64,000 geo_entities cells (common/geo.py + ingestion/grid.py). One
  Overpass call per cell would be both catastrophically slow and abusive to
  a free public API. Instead this fetches every POI of every category
  inside a metro_area's whole bounding box in a single request (one Overpass
  union query covering all 5 categories at once), then computes per-cell
  count/nearest-distance locally in Python. That's one HTTP call per entry
  in `ingestion.grid.BOUNDING_BOXES` (currently 6), not 64,000.
- **Reuses `ingestion.grid.BOUNDING_BOXES`** rather than redefining metro
  bounding boxes here, so the Overpass query area and the grid-cell
  metro_area assignment can't drift apart.
- **POI-to-category tag mapping** (see CATEGORY_TAG_RULES below): grocery
  is deliberately `shop=supermarket`/`shop=grocery` only — `shop=convenience`
  is its OWN negative-signal category per PROJECT.md ("proxy for less
  desirable clientele"), not a grocery synonym, so a single POI is never
  double-counted as both a positive and a negative signal.
- **Local nearest/count computation**: a plain brute-force haversine scan
  per (cell, category) is explicitly fine per spec at this scale (~64k
  cells x a few thousand POIs per category). A light spatial bucket index
  (`build_bucket_index`/`candidates_near`) is layered on top purely as a
  speed-up for the common case (dense categories in dense metro areas);
  it falls back to an exact full scan whenever the fast path can't
  guarantee correctness (see `nearest_and_count_indexed`), so results are
  identical to brute force either way — the index changes performance, not
  correctness.
- **`*_nearest_m` is the true nearest distance, not capped at 500m**; only
  `*_count_500m` is radius-limited. This mirrors how scoring/engine.py
  already treats these two signals (count = density, nearest = proximity,
  blended separately) and matches the "closer is more informative than
  within-radius-or-not" intuition even outside the 500m ring.

- **v2 restaurants/bars**: `restaurant` is amenity=restaurant ONLY (fast_food
  is excluded); `bar` is amenity=bar|pub|biergarten. They add ~45k elements
  per big metro, so the single fetch is wrapped in
  common.overpass.fetch_with_quadrant_split (4-way bbox split on timeout).
- **v2 brands are non-exclusive**: a Whole Foods is still a grocery, a
  Starbucks still a cafe (see categorize_poi_all). Match is on
  `brand:wikidata` first (verified against name-suggestion-index; see
  BRAND_RULES), falling back to a case-insensitive exact `brand`/`name` match
  only on shop=* / amenity=cafe elements that carry no brand:wikidata. Only
  `*_nearest_m` is stored per brand (no counts).
- **premium_retail_raw** = 1.0*g(whole_foods) + 1.0*g(starbucks) +
  0.5*g(target), g(d)=1/(1+d/800); None distances contribute 0, all None ->
  None (premium_retail_raw()).

Everything that doesn't touch the network or the DB (Overpass response
parsing, tag categorization, per-cell count/nearest math, the bucket index)
is a pure function, unit tested in tests/test_osm_poi.py without a live DB.
`run()`/`fetch_pois_for_bbox()` are the thin, untested DB/network glue.
"""

import math
import re
import sys

from common.db import get_connection, iter_geo_entities, upsert_feature_store
from common.geo import haversine_m
from common.ingestion_log import ingestion_job
from common.overpass import fetch_with_quadrant_split, post_overpass_query
from common.places import Place, clean_name, replace_places
from ingestion.grid import BOUNDING_BOXES

OVERPASS_TIMEOUT_S = 180  # server-side [timeout:] in the query itself
HTTP_TIMEOUT_S = OVERPASS_TIMEOUT_S + 30  # client-side margin for transfer

COUNT_RADIUS_M = 500.0

# OSM tag -> our category. Order/grouping matters: each rule list is one
# category, and the (key, value) pairs across categories are deliberately
# disjoint so a POI never matches more than one category (see module
# docstring re: grocery vs. convenience_store double-counting).
CATEGORY_TAG_RULES: dict[str, list[tuple[str, str]]] = {
    "grocery": [("shop", "supermarket"), ("shop", "grocery")],
    "gym": [("leisure", "fitness_centre")],
    "cafe": [("amenity", "cafe")],
    "gas_station": [("amenity", "fuel")],
    "convenience_store": [("shop", "convenience"), ("shop", "kiosk")],
    # v2. restaurant is deliberately NOT fast_food.
    "restaurant": [("amenity", "restaurant")],
    "bar": [("amenity", "bar"), ("amenity", "pub"), ("amenity", "biergarten")],
}

# v2 brand categories (non-exclusive with CATEGORY_TAG_RULES). Wikidata IDs
# verified against osmlab/name-suggestion-index data/brands/*.json
# (Starbucks Q37158 [+ Starbucks Reserve Q71150001], Whole Foods Market
# Q1809448, Target (USA) Q1046951). `names` are casefolded exact matches for
# the brand/name fallback.
BRAND_RULES: dict[str, dict[str, frozenset[str]]] = {
    "whole_foods": {
        "wikidata": frozenset({"Q1809448"}),
        "names": frozenset({"whole foods market", "whole foods"}),
    },
    "starbucks": {
        "wikidata": frozenset({"Q37158", "Q71150001"}),
        "names": frozenset({"starbucks", "starbucks coffee", "starbucks reserve"}),
    },
    "target": {
        "wikidata": frozenset({"Q1046951"}),
        "names": frozenset({"target"}),
    },
}
ALL_CATEGORIES: list[str] = [*CATEGORY_TAG_RULES, *BRAND_RULES]

# premium_retail_raw weights and distance-decay scale.
PREMIUM_RETAIL_WEIGHTS: dict[str, float] = {"whole_foods": 1.0, "starbucks": 1.0, "target": 0.5}
PREMIUM_RETAIL_SCALE_M = 800.0

# category -> (count_column, nearest_column) in feature_store.
FEATURE_COLUMN_MAP: dict[str, tuple[str, str]] = {
    "grocery": ("grocery_count_500m", "grocery_nearest_m"),
    "gym": ("gym_count_500m", "gym_nearest_m"),
    "cafe": ("cafe_count_500m", "cafe_nearest_m"),
    "gas_station": ("gas_station_count_500m", "gas_station_nearest_m"),
    "convenience_store": (
        "convenience_store_count_500m",
        "convenience_store_nearest_m",
    ),
    "restaurant": ("restaurant_count_500m", "restaurant_nearest_m"),
    "bar": ("bar_count_500m", "bar_nearest_m"),
}

# brand category -> nearest-only feature_store column.
BRAND_NEAREST_COLUMN: dict[str, str] = {
    "whole_foods": "whole_foods_nearest_m",
    "starbucks": "starbucks_nearest_m",
    "target": "target_nearest_m",
}

# ~1.1km (lat) x ~0.85km (lon at ~41N) per bucket. See candidates_near()
# for why this comfortably covers COUNT_RADIUS_M.
BUCKET_DEG = 0.01


# --------------------------------------------------------------------------
# Pure logic — unit tested, no network/DB.
# --------------------------------------------------------------------------


def build_overpass_query(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> str:
    """One Overpass QL query fetching every POI of every category in
    CATEGORY_TAG_RULES within the given bbox, in a single union. Overpass
    bbox order is (south, west, north, east) i.e. (min_lat, min_lon,
    max_lat, max_lon)."""
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    statements = []
    for rules in CATEGORY_TAG_RULES.values():
        for key, value in rules:
            statements.append(f'node["{key}"="{value}"]({bbox});')
            statements.append(f'way["{key}"="{value}"]({bbox});')
    # v2 brands: by wikidata (any element type/tag, e.g. Target tagged
    # shop=department_store), plus name/brand fallback on shop=* elements.
    # amenity=cafe is already fetched above, covering Starbucks-by-name.
    ids = "|".join(sorted(i for r in BRAND_RULES.values() for i in r["wikidata"]))
    names = "|".join(sorted(re.escape(n) for r in BRAND_RULES.values() for n in r["names"]))
    statements.append(f'nwr["brand:wikidata"~"^({ids})$"]({bbox});')
    statements.append(f'nwr["shop"]["brand"~"^({names})$",i]({bbox});')
    statements.append(f'nwr["shop"]["name"~"^({names})$",i]({bbox});')
    body = "\n  ".join(statements)
    return f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n(\n  {body}\n);\nout center;"


def parse_overpass_response(data: dict) -> list[tuple[float, float, dict]]:
    """Extracts (lat, lon, tags) for every element in an Overpass JSON
    response. Nodes carry lat/lon directly; ways/relations only have a
    lat/lon if the query used `out center` (which build_overpass_query
    does) — elements without one are skipped rather than fabricating a
    location."""
    pois: list[tuple[float, float, dict]] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        if lat is None or lon is None:
            continue
        pois.append((float(lat), float(lon), tags))
    return pois


def categorize_poi(tags: dict) -> str | None:
    """Maps a POI's OSM tags to one of our categories, or None if it
    matched nothing we care about (shouldn't happen given Overpass was
    queried with exactly these tag filters, but a response could in theory
    include a way's tags that don't match the value we filtered on, e.g. a
    relation member)."""
    for category, rules in CATEGORY_TAG_RULES.items():
        for key, value in rules:
            if tags.get(key) == value:
                return category
    return None


def _brand_matches(tags: dict, rule: dict[str, frozenset[str]]) -> bool:
    wikidata = tags.get("brand:wikidata")
    if wikidata:
        # An explicit wikidata id is authoritative; a different brand's id
        # must not be overridden by a coincidental name.
        return wikidata in rule["wikidata"]
    if "shop" not in tags and tags.get("amenity") != "cafe":
        return False
    for key in ("brand", "name"):
        value = tags.get(key)
        if value and value.strip().casefold() in rule["names"]:
            return True
    return False


def categorize_poi_all(tags: dict) -> list[str]:
    """All categories a POI belongs to: its (single) tag-rule category plus
    any brand categories. Non-exclusive: a Whole Foods is ['grocery',
    'whole_foods'], a Starbucks ['cafe', 'starbucks']."""
    cats: list[str] = []
    base = categorize_poi(tags)
    if base is not None:
        cats.append(base)
    for brand, rule in BRAND_RULES.items():
        if _brand_matches(tags, rule):
            cats.append(brand)
    return cats


def extract_places(data: dict) -> list[Place]:
    """Named places from a raw Overpass response: one Place per (element,
    category). Unnamed/blank-named elements and elements without a location
    are skipped. source_id is "<type>/<id>"."""
    places: list[Place] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = clean_name(tags.get("name"))
        if name is None or el.get("id") is None:
            continue
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        if lat is None or lon is None:
            continue
        for category in categorize_poi_all(tags):
            places.append(
                Place(
                    source="osm",
                    source_id=f"{el.get('type')}/{el['id']}",
                    category=category,
                    name=name,
                    latitude=float(lat),
                    longitude=float(lon),
                    brand=tags.get("brand"),
                )
            )
    return places


def premium_retail_raw(
    whole_foods_m: float | None, starbucks_m: float | None, target_m: float | None
) -> float | None:
    """1.0*g(whole_foods) + 1.0*g(starbucks) + 0.5*g(target), g(d) =
    1/(1+d/800). None contributes 0; all three None -> None."""
    dists = {"whole_foods": whole_foods_m, "starbucks": starbucks_m, "target": target_m}
    if all(d is None for d in dists.values()):
        return None
    return sum(
        PREMIUM_RETAIL_WEIGHTS[k] / (1.0 + d / PREMIUM_RETAIL_SCALE_M)
        for k, d in dists.items()
        if d is not None
    )


def group_pois_by_category(
    pois: list[tuple[float, float, dict]],
) -> dict[str, list[tuple[float, float]]]:
    """(lat, lon, tags) triples -> {category: [(lat, lon), ...]}. Every
    category key is always present (possibly empty) so downstream code
    never has to guard with .get(category, [])."""
    grouped: dict[str, list[tuple[float, float]]] = {cat: [] for cat in ALL_CATEGORIES}
    for lat, lon, tags in pois:
        for category in categorize_poi_all(tags):
            grouped[category].append((lat, lon))
    return grouped


def nearest_and_count(
    cell_lat: float,
    cell_lon: float,
    poi_coords: list[tuple[float, float]],
    radius_m: float = COUNT_RADIUS_M,
) -> tuple[int, float | None]:
    """Brute-force ground truth: count of POIs within radius_m, and the
    true nearest distance (unbounded, None if poi_coords is empty)."""
    if not poi_coords:
        return 0, None
    count = 0
    nearest: float | None = None
    for lat, lon in poi_coords:
        d = haversine_m(cell_lat, cell_lon, lat, lon)
        if nearest is None or d < nearest:
            nearest = d
        if d <= radius_m:
            count += 1
    return count, nearest


def build_bucket_index(
    poi_coords: list[tuple[float, float]], bucket_deg: float = BUCKET_DEG
) -> dict[tuple[int, int], list[tuple[float, float]]]:
    """Spatial hash of POI coords into bucket_deg x bucket_deg degree
    cells, keyed by (floor(lat/bucket_deg), floor(lon/bucket_deg))."""
    index: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for lat, lon in poi_coords:
        key = (math.floor(lat / bucket_deg), math.floor(lon / bucket_deg))
        index.setdefault(key, []).append((lat, lon))
    return index


def candidates_near(
    index: dict[tuple[int, int], list[tuple[float, float]]],
    cell_lat: float,
    cell_lon: float,
    bucket_deg: float = BUCKET_DEG,
    ring: int = 1,
) -> list[tuple[float, float]]:
    """Points from the cell's own bucket plus `ring` rings of neighbors.

    ring=1 (a 3x3 block of buckets) guarantees at least 1*bucket_deg of
    margin between the cell center and the block's outer edge, in every
    direction (the cell sits somewhere inside its own bucket; the block
    extends one full extra bucket beyond that on every side). At
    bucket_deg=0.01 that margin is ~1113m in latitude and ~840m in
    longitude at NYC-metro latitudes (1 degree longitude shrinks by
    cos(latitude)) — the tighter of the two, ~840m, still comfortably
    exceeds COUNT_RADIUS_M (500m). So any POI within 500m of the cell is
    guaranteed to be among these candidates.
    """
    cx = math.floor(cell_lat / bucket_deg)
    cy = math.floor(cell_lon / bucket_deg)
    out: list[tuple[float, float]] = []
    for dx in range(-ring, ring + 1):
        for dy in range(-ring, ring + 1):
            out.extend(index.get((cx + dx, cy + dy), []))
    return out


def nearest_and_count_indexed(
    cell_lat: float,
    cell_lon: float,
    poi_coords: list[tuple[float, float]],
    index: dict[tuple[int, int], list[tuple[float, float]]],
    bucket_deg: float = BUCKET_DEG,
    radius_m: float = COUNT_RADIUS_M,
) -> tuple[int, float | None]:
    """Same (count, nearest) contract as nearest_and_count(), but scans the
    bucket index's nearby candidates first, expanding the search ring
    until it finds ANY candidate rather than falling back to a full scan
    of poi_coords. ring=1 finding something is already guaranteed correct
    per candidates_near's margin argument (anything within radius_m is
    captured); once found, further-out candidates can't be closer, so
    returning immediately is safe at every ring, not just ring=1.

    Previously fell back to a full brute-force scan whenever ring=1's
    nearest exceeded radius_m at all -- including the common case of a
    sparse category (few groceries in a rural cell) where ring=1 still
    found a real candidate, just past 500m. Fixed live 2026-09-29 after
    the identical pattern in ingestion/trails.py stalled 30+ minutes
    against a sparser dataset (trails vs. groceries) and got the DB
    connection killed as idle before a row was written -- this file has
    the same latent risk, just hadn't been unlucky enough to hit it yet."""
    for ring in (1, 2, 4, 8, 16, 32):
        candidates = candidates_near(index, cell_lat, cell_lon, bucket_deg, ring=ring)
        if candidates:
            return nearest_and_count(cell_lat, cell_lon, candidates, radius_m)
    return nearest_and_count(cell_lat, cell_lon, poi_coords, radius_m)


def compute_cell_features(
    cell_lat: float,
    cell_lon: float,
    pois_by_category: dict[str, list[tuple[float, float]]],
    indexes: dict[str, dict[tuple[int, int], list[tuple[float, float]]]] | None = None,
    radius_m: float = COUNT_RADIUS_M,
) -> dict[str, int | float | None]:
    """One geo_entities cell's worth of feature_store columns: all
    count+nearest values, brand nearest values and premium_retail_raw.

    Pass `indexes` (category -> build_bucket_index(...) output) to use the
    fast indexed path; omit it to always brute-force (what the tests below
    use to establish ground truth, and what run() falls back to isn't
    needed since it always builds indexes — this default just keeps the
    function usable/testable standalone).
    """
    features: dict[str, int | float | None] = {}
    for category, (count_col, nearest_col) in FEATURE_COLUMN_MAP.items():
        coords = pois_by_category.get(category, [])
        if indexes is not None and category in indexes:
            count, nearest = nearest_and_count_indexed(
                cell_lat, cell_lon, coords, indexes[category], radius_m=radius_m
            )
        else:
            count, nearest = nearest_and_count(cell_lat, cell_lon, coords, radius_m)
        features[count_col] = count
        features[nearest_col] = nearest
    for brand, col in BRAND_NEAREST_COLUMN.items():
        coords = pois_by_category.get(brand, [])
        if indexes is not None and brand in indexes:
            _, nearest = nearest_and_count_indexed(
                cell_lat, cell_lon, coords, indexes[brand], radius_m=radius_m
            )
        else:
            _, nearest = nearest_and_count(cell_lat, cell_lon, coords, radius_m)
        features[col] = nearest
    features["premium_retail_raw"] = premium_retail_raw(
        features["whole_foods_nearest_m"],
        features["starbucks_nearest_m"],
        features["target_nearest_m"],
    )
    return features


# --------------------------------------------------------------------------
# Thin DB/network glue — not unit tested (no live DB/Overpass in this
# sandbox); kept minimal on purpose so the logic above carries the risk.
# --------------------------------------------------------------------------


def fetch_overpass_data(min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> dict:
    def fetch(lat0: float, lat1: float, lon0: float, lon1: float) -> dict:
        query = build_overpass_query(lat0, lat1, lon0, lon1)
        return post_overpass_query(query, timeout=HTTP_TIMEOUT_S)

    return fetch_with_quadrant_split(fetch, min_lat, max_lat, min_lon, max_lon)


def fetch_pois_for_bbox(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[tuple[float, float, dict]]:
    return parse_overpass_response(fetch_overpass_data(min_lat, max_lat, min_lon, max_lon))


def run() -> None:
    with get_connection() as conn, ingestion_job("osm_poi") as ctx:
        cells_by_metro: dict[str, list[dict]] = {}
        for cell in iter_geo_entities(conn):
            cells_by_metro.setdefault(cell["metro_area"], []).append(cell)

        rows_written = 0
        places_by_key: dict[tuple[str, str], Place] = {}
        for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
            cells = cells_by_metro.get(metro_area, [])
            if not cells:
                continue

            print(
                f"osm_poi: fetching Overpass POIs for {metro_area} ({len(cells)} cells)...",
                file=sys.stderr,
            )
            data = fetch_overpass_data(min_lat, max_lat, min_lon, max_lon)
            pois = parse_overpass_response(data)
            for place in extract_places(data):
                places_by_key.setdefault((place.source_id, place.category), place)
            pois_by_category = group_pois_by_category(pois)
            indexes = {
                category: build_bucket_index(coords)
                for category, coords in pois_by_category.items()
            }

            for cell in cells:
                features = compute_cell_features(
                    cell["latitude"], cell["longitude"], pois_by_category, indexes
                )
                upsert_feature_store(conn, cell["id"], features)
                rows_written += 1
            conn.commit()
            ctx.rows_affected = rows_written

        if places_by_key:
            n_places = replace_places(conn, "osm", list(places_by_key.values()))
            print(f"osm_poi: wrote {n_places} named places.", file=sys.stderr)

    print(f"osm_poi: wrote feature_store rows for {rows_written} geo_entities.", file=sys.stderr)


if __name__ == "__main__":
    run()
