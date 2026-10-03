"""Scoring engine: feature_store raw values -> normalized scores rows.

Kept as direct work (PROJECT.md build sequencing: "Scoring engine design:
keep as direct work, not delegated to a subagent — this is where the
product's judgment and defensibility live"). The two judgment calls made
here, beyond what contracts/normalization.md already specifies:

1. **Combining count + nearest-distance into one raw "goodness" value per
   category.** normalization.md describes normalizing a single raw metric
   per category, but feature_store stores two raw signals for most
   categories (a count and a nearest-distance). This module blends them
   70% proximity / 30% density before normalizing — "how close is the
   nearest one" dominates lived experience; count is a secondary signal
   for areas with real density beyond just having one.

   School and trail categories additionally have a `rating_column`
   (school rating / Strava segment popularity) that gets normalized
   SEPARATELY from proximity+density, not blended into the same raw value
   before normalizing — proximity is in meters, density is a raw count,
   and a rating is on its own external scale, so summing them pre-
   normalization lets whichever has the largest raw magnitude dominate
   regardless of intended weight (caught by a test: naively rescaling a
   missing rating's weight onto proximity/density amplified proximity's
   already-huge magnitude even further, the opposite of the intended
   fix). Normalizing proximity+density and rating independently to 0-100
   first, then blending the two comparable scores avoids that (trails 67/33; schools
   20/80 via CategorySpec.rating_weight).
   When a row has no rating (not yet measured, not "measured as bad"),
   CategorySpec.missing_rating decides: trails fall back to proximity+
   density alone; schools score NULL (the composite re-weights without
   them) and expose the proximity part as school_proximity_score instead.
2. **Composite weights** (DEFAULT_WEIGHTS below), with rationale inline —
   this is the "document weight rationale" requirement from PROJECT.md's
   Scoring Factors section.

Direction/sign handling matches normalization.md but is applied here
(raw-goodness computation), not at ingestion time: ingestion writes true
raw external data unmodified (so feature_store stays inspectable/
debuggable against the source), and this module is where "higher raw
goodness = better" gets established before normalization.
"""

from dataclasses import dataclass

NEAR_DISTANCE_SENTINEL_M = 5000.0  # "nothing found nearby" treated as this far


@dataclass(frozen=True)
class CategorySpec:
    score_column: str
    direction: str  # "positive" | "negative"
    count_column: str | None = None
    nearest_column: str | None = None
    rating_column: str | None = None  # 0-10-ish external scale, normalized same as others
    single_column: str | None = None  # for categories with one raw numeric signal
    dampened_by_street_orientation: bool = False
    # Share of the final score given to the normalized rating (the rest goes
    # to proximity+density). Trails keep the original 1/3; schools use 0.8
    # because "a school nearby" matters far less than "a good school nearby".
    rating_weight: float = 1 / 3
    # Underlying metrics count toward the composite but the website offers no
    # toggle for them. API semantics are unchanged: an omitted `factors`
    # parameter still means every factor, underlying ones included.
    underlying: bool = False
    # What to do when a cell has proximity data but no rating:
    #   "blend_only" -> category score is proximity+density alone (trails).
    #   "null"       -> category score is NULL so the factor drops out of the
    #                   composite (schools: never fabricate a rating-less score).
    missing_rating: str = "blend_only"
    # Fallback single column used when `single_column` is null for a row.
    fallback_single_column: str | None = None
    # If set, the engine also emits the normalized proximity+density part
    # under this scores column for every cell that has any data.
    proximity_score_column: str | None = None


CATEGORY_SPECS: list[CategorySpec] = [
    CategorySpec(
        "grocery_score",
        "positive",
        count_column="grocery_count_500m",
        nearest_column="grocery_nearest_m",
    ),
    CategorySpec(
        "gym_score", "positive", count_column="gym_count_500m", nearest_column="gym_nearest_m"
    ),
    CategorySpec(
        "cafe_score", "positive", count_column="cafe_count_500m", nearest_column="cafe_nearest_m"
    ),
    CategorySpec(
        "restaurant_score",
        "positive",
        count_column="restaurant_count_500m",
        nearest_column="restaurant_nearest_m",
    ),
    CategorySpec(
        "bar_score", "positive", count_column="bar_count_500m", nearest_column="bar_nearest_m"
    ),
    # Bonus signal built at ingestion from distance to Whole Foods/Starbucks/Target.
    CategorySpec(
        "premium_retail_score", "positive", single_column="premium_retail_raw", underlying=True
    ),
    CategorySpec(
        "gas_station_score",
        "negative",
        count_column="gas_station_count_500m",
        nearest_column="gas_station_nearest_m",
    ),
    CategorySpec(
        "convenience_store_score",
        "negative",
        count_column="convenience_store_count_500m",
        nearest_column="convenience_store_nearest_m",
    ),
    CategorySpec(
        "transit_score",
        "positive",
        count_column="transit_stop_count_800m",
        nearest_column="transit_nearest_m",
    ),
    CategorySpec(
        "school_score",
        "positive",
        count_column="school_count_1600m",
        nearest_column="school_nearest_m",
        rating_column="school_avg_rating_1600m",
        rating_weight=0.8,
        missing_rating="null",
        proximity_score_column="school_proximity_score",
    ),
    CategorySpec("road_score", "negative", single_column="congestion_proxy_raw"),
    # Prefers the real facility-based signal; falls back to the v1 proxy for
    # cells where emergency_corridor_facility_raw is null.
    CategorySpec(
        "emergency_corridor_score",
        "negative",
        single_column="emergency_corridor_facility_raw",
        fallback_single_column="emergency_corridor_proxy_raw",
        dampened_by_street_orientation=True,
    ),
    CategorySpec("airport_score", "negative", single_column="airport_drive_time_min"),
    # rating_column here is Strava segment popularity, not a star-rating —
    # same "optional external enrichment on top of an OSM base signal"
    # shape as school ratings, so it reuses the same blend/fallback logic.
    CategorySpec(
        "trail_popularity_score",
        "positive",
        count_column="running_trail_count_800m",
        nearest_column="running_trail_nearest_m",
        rating_column="strava_segment_popularity_raw",
        underlying=True,
    ),
]

# Score columns of underlying metrics (counted in the composite, no UI toggle).
UNDERLYING_SCORE_COLUMNS: frozenset[str] = frozenset(
    s.score_column for s in CATEGORY_SPECS if s.underlying
)

# Hand-tuned initially — no training data to fit against yet (PROJECT.md).
# Rationale, factor by factor:
# v2 adds restaurant/bar/premium_retail, re-weights emergency corridor and
# blends schools 20/80 (see below). The deployed default stays v1 until the
# v2 data is ingested; select v2 via SCORING_WEIGHTS_VERSION.
WEIGHTS_VERSION_V1 = "v1-handtuned"
WEIGHTS_VERSION_V2 = "v2-handtuned"

DEFAULT_WEIGHTS: dict[str, float] = {
    # "Origin insight": grocery-type retailers are the strongest proxy for
    # neighborhood desirability per PROJECT.md's founding thesis.
    "grocery_score": 1.5,
    "gym_score": 1.0,
    "cafe_score": 1.0,
    # Restaurants: a core "things to do on foot" signal, same weight as cafes
    # and gyms but the densest, most reliable OSM category, so it sits at 1.0.
    "restaurant_score": 1.0,
    # Bars/pubs: nightlife is desirable to some and noise to others; half
    # weight keeps it a tiebreaker rather than a driver.
    "bar_score": 0.5,
    # Whole Foods / Starbucks / Target proximity is a well-known gentrification
    # and desirability marker; below the base amenities since it is a brand
    # proxy, not a need.
    "premium_retail_score": 0.75,
    # Same weight as grocery in magnitude, since it's the same "amenity
    # cluster proxy" logic, just negative direction.
    "gas_station_score": 1.0,
    "convenience_store_score": 0.75,
    # Core to the walkability/drivability tradeoff PROJECT.md is built on.
    "transit_score": 1.5,
    "school_score": 1.5,
    "road_score": 1.0,
    # v1 flagged this as "proxy only" (0.5). v2 measures real fire/police/EMS
    # facility proximity (emergency_corridor_facility_raw), a better-grounded
    # signal, so it rises to 0.75; the proxy remains as a per-cell fallback.
    "emergency_corridor_score": 0.75,
    "airport_score": 0.75,
    # User-requested addition: proxy for popularity/desirability/safety —
    # an actively-used trail network signals a neighborhood people choose
    # to be outside in. Weighted between the base amenity categories (1.0)
    # and the core factors (1.5): a real signal, but resting on a weaker
    # data foundation (OSM trail presence isn't the same as measured
    # popularity) until Strava segment data is actually flowing.
    "trail_popularity_score": 1.25,
}


def _apply_street_orientation_damping(value: float, street_orientation: str | None) -> float:
    """Emergency-corridor penalty is mitigated by street orientation
    (normalization.md): a side street sees less of the noise/traffic a
    facing corridor would, so the raw penalty signal is dampened, not
    the final score — dampening happens before normalization so it stays
    comparable across the cohort."""
    if street_orientation == "side_street":
        return value * 0.5
    return value


def compute_raw_goodness(row: dict, spec: CategorySpec) -> float | None:
    """Returns a single 'higher is always better' raw value for this
    category's proximity+density (or single-column) signal, or None if
    there's no data yet for this row/category. Deliberately excludes
    spec.rating_column even when present — see compute_rating_raw() and
    the module docstring for why that's normalized separately."""
    if spec.single_column is not None:
        value = row.get(spec.single_column)
        if value is None and spec.fallback_single_column is not None:
            value = row.get(spec.fallback_single_column)
        if value is None:
            return None
        value = float(value)
        if spec.dampened_by_street_orientation:
            value = _apply_street_orientation_damping(value, row.get("street_orientation"))
        return -value if spec.direction == "negative" else value

    count = row.get(spec.count_column) if spec.count_column else None
    nearest = row.get(spec.nearest_column) if spec.nearest_column else None
    if count is None and nearest is None:
        return None

    count = float(count) if count is not None else 0.0
    nearest = float(nearest) if nearest is not None else NEAR_DISTANCE_SENTINEL_M
    proximity = -nearest  # closer = better
    density = count
    blended = 0.7 * proximity + 0.3 * density

    return -blended if spec.direction == "negative" else blended


def compute_rating_raw(row: dict, spec: CategorySpec) -> float | None:
    """Raw rating-column value (school rating / Strava popularity), or
    None if this spec has no rating_column or the row doesn't have one
    yet. Direction is always positive for rating columns today (higher
    rating/popularity = better) — no inversion needed."""
    if spec.rating_column is None:
        return None
    rating = row.get(spec.rating_column)
    return float(rating) if rating is not None else None


def min_max_normalize(raw_by_id: dict[str, float]) -> dict[str, float]:
    """0-100 within this cohort. Degenerate cohort (all equal, or a single
    row) normalizes to a neutral 50 rather than dividing by zero."""
    values = list(raw_by_id.values())
    if not values:
        return {}
    lo, hi = min(values), max(values)
    if hi == lo:
        return {k: 50.0 for k in raw_by_id}
    return {k: (v - lo) / (hi - lo) * 100.0 for k, v in raw_by_id.items()}


def all_score_columns() -> list[str]:
    """Every per-category score column the engine can emit, plus the composite."""
    cols = [spec.score_column for spec in CATEGORY_SPECS]
    cols += [spec.proximity_score_column for spec in CATEGORY_SPECS if spec.proximity_score_column]
    return [*cols, "composite_score"]


def compute_composite(
    sub_scores: dict[str, float], weights: dict[str, float] = DEFAULT_WEIGHTS
) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for category, score in sub_scores.items():
        w = weights.get(category, 0.0)
        weighted_sum += w * score
        total_weight += w
    if total_weight == 0.0:
        return 0.0
    return weighted_sum / total_weight


RATING_BLEND_WEIGHT = 1 / 3  # default CategorySpec.rating_weight (trails)


def score_metro_cohort(feature_rows: list[dict]) -> dict[str, dict]:
    """feature_rows: feature_store rows (each a dict including geo_entity_id
    and the raw columns) for ONE metro_area cohort. Returns
    {geo_entity_id: {category_score_column: value, ..., 'composite_score': value}}.
    """
    normalized_by_category: dict[str, dict[str, float]] = {}
    rating_normalized_by_category: dict[str, dict[str, float]] = {}

    for spec in CATEGORY_SPECS:
        raw_by_id = {}
        for row in feature_rows:
            raw = compute_raw_goodness(row, spec)
            if raw is not None:
                raw_by_id[row["geo_entity_id"]] = raw
        normalized_by_category[spec.score_column] = min_max_normalize(raw_by_id)

        if spec.rating_column is not None:
            rating_raw_by_id = {}
            for row in feature_rows:
                rating = compute_rating_raw(row, spec)
                if rating is not None:
                    rating_raw_by_id[row["geo_entity_id"]] = rating
            rating_normalized_by_category[spec.score_column] = min_max_normalize(rating_raw_by_id)

    results: dict[str, dict] = {}
    for row in feature_rows:
        geo_id = row["geo_entity_id"]
        sub_scores = {}
        extras = {}
        for spec in CATEGORY_SPECS:
            pd_score = normalized_by_category[spec.score_column].get(geo_id)
            if pd_score is None:
                continue
            if spec.proximity_score_column:
                extras[spec.proximity_score_column] = pd_score
            if spec.rating_column is None:
                sub_scores[spec.score_column] = pd_score
                continue
            rating_score = rating_normalized_by_category.get(spec.score_column, {}).get(geo_id)
            if rating_score is None:
                if spec.missing_rating == "null":
                    continue
                sub_scores[spec.score_column] = pd_score
            else:
                sub_scores[spec.score_column] = (
                    1 - spec.rating_weight
                ) * pd_score + spec.rating_weight * rating_score
        if not sub_scores:
            continue
        results[geo_id] = {
            **sub_scores,
            **extras,
            "composite_score": compute_composite(sub_scores),
        }
    return results
