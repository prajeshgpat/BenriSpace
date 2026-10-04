"""Pure, DB-free geo-lookup and response-shape-building helpers for
GET /score. Kept separate from api/main.py's route handler so the parts
worth unit testing without a live Postgres connection (bbox math,
nearest-neighbor fallback, mapping a `scores` row onto the SubScores
response shape) are plain functions over dicts -- see tests/test_api.py.
"""

from api.factors import FACTOR_COLUMNS, to_snake
from api.schemas import SchoolInfo, ScoreResponse, SubScores
from common.db import get_neighborhoods_by_geohash
from common.geo import haversine_m
from scoring.engine import LEGACY_FALLBACK_COLUMNS

# Fallback bounding-box half-width in degrees, used when the exact
# geohash6 cell (encoded the same way ingestion/grid.py builds the grid)
# has no geo_entities row. geohash6 cells are ~1.22km x 0.61km
# (ingestion/grid.py), so ~0.03 deg comfortably covers the cell's
# immediate neighbors in every direction. Cheap to scan: the whole metro
# is only ~64k geo_entities rows total (docs/ROADMAP.md/docs/ROADMAP.md), so even an
# unindexed-feeling bbox scan plus a Python nearest-neighbor pass is fine
# without reaching for PostGIS.
FALLBACK_BBOX_MARGIN_DEG = 0.03


def neighborhood_map(conn, geohashes) -> dict[str, str]:
    """{geohash: neighborhood} for the labelled cells among `geohashes`
    (empty before migration 0008, or when none is given)."""
    wanted = [g for g in geohashes if g]
    return get_neighborhoods_by_geohash(conn, wanted) if wanted else {}


def with_neighborhood(conn, geo_entity: dict | None) -> dict | None:
    """The geo_entity row plus its `neighborhood` (None when unlabelled)."""
    if geo_entity is None:
        return None
    if "neighborhood" in geo_entity:
        return geo_entity
    names = neighborhood_map(conn, [geo_entity.get("geohash")])
    return {**geo_entity, "neighborhood": names.get(geo_entity.get("geohash"))}


def bbox_around(
    lat: float, lon: float, margin_deg: float = FALLBACK_BBOX_MARGIN_DEG
) -> tuple[float, float, float, float]:
    """Returns (min_lat, max_lat, min_lon, max_lon) for the fallback bbox
    query when the exact geohash6 cell misses."""
    return (lat - margin_deg, lat + margin_deg, lon - margin_deg, lon + margin_deg)


def nearest_geo_entity(lat: float, lon: float, candidates: list[dict]) -> dict | None:
    """Picks the closest candidate (each dict needs 'latitude'/'longitude')
    by haversine distance. `candidates` is expected to be the bbox result
    set -- ~a handful to a few hundred rows, cheap to scan in Python."""
    if not candidates:
        return None
    return min(candidates, key=lambda c: haversine_m(lat, lon, c["latitude"], c["longitude"]))


def factor_value(score_row: dict, column: str):
    """A factor's score from a `scores`-shaped row: the column itself, else its
    legacy column (v2 rows keep Shopping in premium_retail_score and Recreation
    in trail_popularity_score), else None."""
    value = score_row.get(column)
    if value is None and column in LEGACY_FALLBACK_COLUMNS:
        value = score_row.get(LEGACY_FALLBACK_COLUMNS[column])
    return value


def sub_scores_from_score_row(score_row: dict) -> SubScores:
    """Maps `scores` table columns onto the 13-factor SubScores response shape
    (grocery_score -> grocery, gas_convenience_score -> gasConvenience on the
    wire via CamelModel's alias_generator, road_score -> traffic). v2 rows are
    read through their legacy columns where one exists (shopping <-
    premium_retail_score, recreation <- trail_popularity_score) and have
    gasConvenience null."""
    fields = {}
    for key, column in FACTOR_COLUMNS.items():
        fields[to_snake(key)] = factor_value(score_row, column)
    return SubScores(**fields)


def get_feature_row(conn, geo_entity_id: str) -> dict | None:
    """The feature_store row for one geo_entity (nearest distances in
    metres, school district fields), or None."""
    with conn.cursor() as cur:
        cur.execute("select * from feature_store where geo_entity_id = %s", (geo_entity_id,))
        return cur.fetchone()


def school_info_from_rows(score_row: dict, feature_row: dict | None) -> SchoolInfo | None:
    """SchoolInfo when any school data exists (v2 rows), else None so v1
    rows serialize `school: null`."""
    feature_row = feature_row or {}
    proximity = score_row.get("school_proximity_score")
    district = feature_row.get("school_district_name")
    source = feature_row.get("school_rating_source")
    if proximity is None and district is None and source is None:
        return None
    return SchoolInfo(
        proximity=None if proximity is None else float(proximity),
        rating_available=score_row.get("school_score") is not None,
        district_name=district,
        source=source,
    )


def build_score_response(
    geo_entity: dict, score_row: dict, feature_row: dict | None = None
) -> ScoreResponse:
    """Pure response builder from plain dict rows (psycopg's dict_row
    cursor output, or a hand-built dict in tests) -- no DB access here.
    `geo_entity` needs id/latitude/longitude/formatted_address;
    `score_row` needs composite_score/weights_version/computed_at plus the
    *_score columns SubScores reads."""
    address = geo_entity.get("formatted_address") or (
        f"{geo_entity['latitude']:.5f},{geo_entity['longitude']:.5f}"
    )
    return ScoreResponse(
        geo_entity_id=geo_entity["id"],
        address=address,
        latitude=geo_entity["latitude"],
        longitude=geo_entity["longitude"],
        composite_score=score_row["composite_score"],
        sub_scores=sub_scores_from_score_row(score_row),
        weights_version=score_row["weights_version"],
        computed_at=score_row["computed_at"],
        school=school_info_from_rows(score_row, feature_row),
        neighborhood=geo_entity.get("neighborhood"),
    )
