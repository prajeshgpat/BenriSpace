"""Scoring engine: feature_store raw values -> normalized scores rows.

Kept as direct work (docs/ROADMAP.md build sequencing: "Scoring engine design:
keep as direct work, not delegated to a subagent — this is where the
product's judgment and defensibility live"). The two judgment calls made
here, beyond what docs/SCORING.md already specifies:

1. **Combining count + nearest-distance into one raw "goodness" value per
   category.** docs/SCORING.md describes normalizing a single raw metric
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
   this is the "document weight rationale" requirement from docs/ROADMAP.md's
   Scoring Factors section.

Direction/sign handling matches docs/SCORING.md but is applied here
(raw-goodness computation), not at ingestion time: ingestion writes true
raw external data unmodified (so feature_store stays inspectable/
debuggable against the source), and this module is where "higher raw
goodness = better" gets established before normalization.
"""

from collections.abc import Callable
from dataclasses import dataclass

NEAR_DISTANCE_SENTINEL_M = 5000.0  # "nothing found nearby" treated as this far
FT_PER_M = 3.280839895


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
    # v2.1: a pure function of the whole feature row returning a "higher is
    # always better" goodness value (None = no data). Replaces the
    # count/nearest/single-column logic; it owns its own direction handling.
    raw_fn: Callable[[dict], float | None] | None = None
    # v2.1: a second signal normalized on its own and blended in with
    # `secondary_weight` (Recreation: park signal 75% + trail signal 25%).
    # A missing half falls back to the other one rather than scoring 0.
    secondary: "CategorySpec | None" = None
    secondary_weight: float = 0.25


# ---------------------------------------------------------------------------
# v2.1 pure raw-signal functions (docs/SCORING.md 3.4, 3.5, 4.3, 5.2)
# ---------------------------------------------------------------------------

# Gas stations / convenience stores right next door are a noise-corridor
# negative (loitering, fuel fumes): full penalty within 300 ft, falling
# linearly to none at 800 ft. Distances in feature_store are metres.
ADJACENCY_FULL_FT = 300.0
ADJACENCY_ZERO_FT = 800.0
ADJACENCY_FULL_M = ADJACENCY_FULL_FT / FT_PER_M
ADJACENCY_ZERO_M = ADJACENCY_ZERO_FT / FT_PER_M
# Hand-tuned, in the units of emergency_corridor_facility_raw: one adjacent
# station costs about as much as a secondary road at its closest (class
# weight 3 / (1 + 0)). Both kinds adjacent cost more, capped at 1.5x.
ADJACENCY_FULL_PENALTY = 3.0
ADJACENCY_MAX_SHARE = 1.5
# Share of the shopping score a Whole Foods / Starbucks / Target anchor can add
# (premium_retail_raw tops out at 2.5, so at most +0.2 on a 0-1 signal).
SHOPPING_ANCHOR_WEIGHT = 0.08


def adjacency_share(nearest_m: float | None) -> float:
    """1.0 within 300 ft, linear to 0.0 at 800 ft, 0.0 when unknown/farther."""
    if nearest_m is None:
        return 0.0
    d = float(nearest_m)
    if d <= ADJACENCY_FULL_M:
        return 1.0
    if d >= ADJACENCY_ZERO_M:
        return 0.0
    return (ADJACENCY_ZERO_M - d) / (ADJACENCY_ZERO_M - ADJACENCY_FULL_M)


def gas_convenience_adjacency_penalty(
    gas_nearest_m: float | None, convenience_nearest_m: float | None
) -> float:
    """Extra noise-corridor penalty (same units as the corridor raw signal,
    higher = worse) from gas stations and convenience stores right next door,
    using the nearest distance of each kind. 0.0 when neither is close."""
    share = adjacency_share(gas_nearest_m) + adjacency_share(convenience_nearest_m)
    return ADJACENCY_FULL_PENALTY * min(ADJACENCY_MAX_SHARE, share)


def noise_corridor_goodness(row: dict) -> float | None:
    """v2.1 Noise Corridor: -(corridor/facility signal, damped for side
    streets, + gas / convenience adjacency penalty). None when the cell has no
    corridor signal at all (the adjacency penalty alone never scores a cell)."""
    base = row.get("emergency_corridor_facility_raw")
    if base is None:
        base = row.get("emergency_corridor_proxy_raw")
    if base is None:
        return None
    damped = _apply_street_orientation_damping(float(base), row.get("street_orientation"))
    penalty = gas_convenience_adjacency_penalty(
        row.get("gas_station_nearest_m"), row.get("convenience_store_nearest_m")
    )
    return -(damped + penalty)


def gas_convenience_goodness(row: dict) -> float | None:
    """v2.1 Gas & Convenience (one positive factor): the generic 70% proximity
    / 30% density blend over the UNION of gas stations and convenience stores
    (nearest of either; counts within 500 m added). Approximates the
    framework's k=2 nearest: two stations close together read as more
    available than one."""
    counts = [row.get("gas_station_count_500m"), row.get("convenience_store_count_500m")]
    nearests = [
        float(v)
        for v in (row.get("gas_station_nearest_m"), row.get("convenience_store_nearest_m"))
        if v is not None
    ]
    if all(c is None for c in counts) and not nearests:
        return None
    count = sum(float(c) for c in counts if c is not None)
    nearest = min(nearests) if nearests else NEAR_DISTANCE_SENTINEL_M
    return 0.7 * -nearest + 0.3 * count


def shopping_goodness(row: dict) -> float | None:
    """v2.1 Shopping: the stored proximity + variety signal (shopping_raw, 0-1)
    plus a small anchor bonus from premium_retail_raw (Whole Foods / Starbucks /
    Target). None when neither exists."""
    base = row.get("shopping_raw")
    anchor = row.get("premium_retail_raw")
    if base is None and anchor is None:
        return None
    return (float(base) if base is not None else 0.0) + SHOPPING_ANCHOR_WEIGHT * (
        float(anchor) if anchor is not None else 0.0
    )


# Trail access is the secondary half of Recreation (existing trail features).
_TRAIL_SPEC = CategorySpec(
    "_trail",
    "positive",
    count_column="running_trail_count_800m",
    nearest_column="running_trail_nearest_m",
    rating_column="strava_segment_popularity_raw",
)


CATEGORY_SPECS_V2: list[CategorySpec] = [
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

_V2_BY_COLUMN = {s.score_column: s for s in CATEGORY_SPECS_V2}

# v2.1 (weights_version 'v2.1-handtuned'): the 13 user-facing factors, none
# hidden. Same min-max engine shape; premium_retail / gas_station /
# convenience_store / trail_popularity are folded into Shopping, Gas &
# Convenience, Noise Corridor and Recreation. `road_score` is Traffic.
CATEGORY_SPECS_V2_1: list[CategorySpec] = [
    _V2_BY_COLUMN["grocery_score"],
    _V2_BY_COLUMN["gym_score"],
    _V2_BY_COLUMN["cafe_score"],
    _V2_BY_COLUMN["restaurant_score"],
    _V2_BY_COLUMN["bar_score"],
    CategorySpec("shopping_score", "positive", raw_fn=shopping_goodness),
    CategorySpec("gas_convenience_score", "positive", raw_fn=gas_convenience_goodness),
    _V2_BY_COLUMN["transit_score"],
    _V2_BY_COLUMN["school_score"],
    _V2_BY_COLUMN["road_score"],
    CategorySpec(
        "emergency_corridor_score", "negative", raw_fn=noise_corridor_goodness
    ),
    _V2_BY_COLUMN["airport_score"],
    CategorySpec(
        "recreation_score",
        "positive",
        single_column="recreation_raw",
        secondary=_TRAIL_SPEC,
        secondary_weight=0.25,
    ),
]

# Every score column the `scores` table can hold for a category (v2 and v2.1);
# the DB column whitelist and the area aggregation use this union.
# (The v2 spec wins where both versions share a column, e.g. road_score.)
CATEGORY_SPECS: list[CategorySpec] = [
    *CATEGORY_SPECS_V2,
    *(s for s in CATEGORY_SPECS_V2_1 if s.score_column not in _V2_BY_COLUMN),
]

# v2.1 columns that older rows hold under a legacy name: a v2 row's Shopping is
# its premium_retail_score and its Recreation its trail_popularity_score. The API
# reads `coalesce(new, legacy)` so one query serves rows of either version.
LEGACY_FALLBACK_COLUMNS: dict[str, str] = {
    "shopping_score": "premium_retail_score",
    "recreation_score": "trail_popularity_score",
}

# Score columns of underlying metrics (counted in the composite, no UI toggle).
UNDERLYING_SCORE_COLUMNS: frozenset[str] = frozenset(
    s.score_column for s in CATEGORY_SPECS if s.underlying
)

# Hand-tuned initially — no training data to fit against yet (docs/ROADMAP.md).
# Rationale, factor by factor:
# v2 adds restaurant/bar/premium_retail, re-weights emergency corridor and
# blends schools 20/80 (see below). The deployed default stays v1 until the
# v2 data is ingested; select v2 via SCORING_WEIGHTS_VERSION.
WEIGHTS_VERSION_V1 = "v1-handtuned"
WEIGHTS_VERSION_V2 = "v2-handtuned"
WEIGHTS_VERSION_V2_1 = "v2.1-handtuned"

DEFAULT_WEIGHTS: dict[str, float] = {
    # "Origin insight": grocery-type retailers are the strongest proxy for
    # neighborhood desirability per docs/ROADMAP.md's founding thesis.
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
    # Core to the walkability/drivability tradeoff docs/ROADMAP.md is built on.
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


# v2.1 default relative weights (docs/SCORING.md section 2, accepted by the
# owner 2026-10-04): factors used more often weigh more. Only the ratios matter;
# the composite is normalized by the weight of the factors that have a score.
V2_1_WEIGHTS: dict[str, float] = {
    "grocery_score": 14.0,
    "transit_score": 14.0,
    "emergency_corridor_score": 12.0,  # Noise Corridor
    "restaurant_score": 10.0,
    "school_score": 10.0,
    "gym_score": 9.0,
    "cafe_score": 8.0,
    "gas_convenience_score": 6.0,
    "bar_score": 5.0,
    "airport_score": 5.0,
    "recreation_score": 5.0,
    "shopping_score": 4.0,
    "road_score": 4.0,  # Traffic
}

_SPECS_BY_VERSION: dict[str, tuple[list[CategorySpec], dict[str, float]]] = {
    WEIGHTS_VERSION_V2: (CATEGORY_SPECS_V2, DEFAULT_WEIGHTS),
    WEIGHTS_VERSION_V2_1: (CATEGORY_SPECS_V2_1, V2_1_WEIGHTS),
}


def specs_and_weights(weights_version: str) -> tuple[list[CategorySpec], dict[str, float]]:
    """(category specs, default weights) the engine uses for a weights version.
    v1 rows were computed by the same code as v2 (a subset of the columns)."""
    return _SPECS_BY_VERSION.get(weights_version, _SPECS_BY_VERSION[WEIGHTS_VERSION_V2])


def _apply_street_orientation_damping(value: float, street_orientation: str | None) -> float:
    """Emergency-corridor penalty is mitigated by street orientation
    (docs/SCORING.md): a side street sees less of the noise/traffic a
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
    if spec.raw_fn is not None:
        return spec.raw_fn(row)
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


def all_score_columns(weights_version: str = WEIGHTS_VERSION_V2) -> list[str]:
    """Every per-category score column the engine emits for a weights version,
    plus the composite."""
    specs, _ = specs_and_weights(weights_version)
    cols = [spec.score_column for spec in specs]
    cols += [spec.proximity_score_column for spec in specs if spec.proximity_score_column]
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


def _spec_scores(
    feature_rows: list[dict], spec: CategorySpec
) -> tuple[dict[str, float], dict[str, float]]:
    """({geo_entity_id: 0-100 category score}, {geo_entity_id: 0-100
    proximity+density part before any rating blend}) for one spec over a
    cohort, applying the rating blend and (v2.1) the secondary-signal blend.
    Cells without data for the spec are absent."""
    raw_by_id = {}
    for row in feature_rows:
        raw = compute_raw_goodness(row, spec)
        if raw is not None:
            raw_by_id[row["geo_entity_id"]] = raw
    primary = min_max_normalize(raw_by_id)

    rating_scores: dict[str, float] = {}
    if spec.rating_column is not None:
        rating_raw = {}
        for row in feature_rows:
            rating = compute_rating_raw(row, spec)
            if rating is not None:
                rating_raw[row["geo_entity_id"]] = rating
        rating_scores = min_max_normalize(rating_raw)

    scores: dict[str, float] = {}
    for geo_id, pd_score in primary.items():
        if spec.rating_column is None:
            scores[geo_id] = pd_score
            continue
        rating_score = rating_scores.get(geo_id)
        if rating_score is None:
            if spec.missing_rating == "null":
                continue
            scores[geo_id] = pd_score
        else:
            scores[geo_id] = (1 - spec.rating_weight) * pd_score + spec.rating_weight * rating_score

    if spec.secondary is not None:
        secondary, _ = _spec_scores(feature_rows, spec.secondary)
        w = spec.secondary_weight
        for geo_id in set(scores) | set(secondary):
            a, b = scores.get(geo_id), secondary.get(geo_id)
            scores[geo_id] = b if a is None else a if b is None else (1 - w) * a + w * b
    return scores, primary


def score_metro_cohort(
    feature_rows: list[dict], weights_version: str = WEIGHTS_VERSION_V2
) -> dict[str, dict]:
    """feature_rows: feature_store rows (each a dict including geo_entity_id
    and the raw columns) for ONE metro_area cohort. Returns
    {geo_entity_id: {category_score_column: value, ..., 'composite_score': value}}.
    `weights_version` picks the category specs and default weights (v2 or v2.1).
    """
    specs, weights = specs_and_weights(weights_version)
    scored = {spec.score_column: _spec_scores(feature_rows, spec) for spec in specs}

    results: dict[str, dict] = {}
    for row in feature_rows:
        geo_id = row["geo_entity_id"]
        sub_scores = {}
        extras = {}
        for spec in specs:
            final, primary = scored[spec.score_column]
            if spec.proximity_score_column and geo_id in primary:
                extras[spec.proximity_score_column] = primary[geo_id]
            if geo_id in final:
                sub_scores[spec.score_column] = final[geo_id]
        if not sub_scores:
            continue
        results[geo_id] = {
            **sub_scores,
            **extras,
            "composite_score": compute_composite(sub_scores, weights),
        }
    return results
