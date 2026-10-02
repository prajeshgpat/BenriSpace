# Normalization & Weighting Approach

How raw `feature_store` values become the normalized `scores` sub-scores
and composite score. Referenced by `schema.sql` and `openapi.yaml` — keep
in sync with both if this changes.

## Normalization

Each raw metric (count/distance) is min-max normalized to a 0-100 range
**within its metro_area cohort**, not globally. Rationale: v1 spans both
dense urban areas (five boroughs) and suburban/exurban areas (Hudson
Valley, Fairfield County). A global normalization would flatten every
suburban address to near-zero on walkability-shaped factors, which isn't
the signal we want — the product scores convenience relative to the kind
of area the address is in, not absolute density.

For each raw metric `x` in cohort with observed `min`/`max`:

```
normalized = (x - min) / (max - min) * 100
```

Distance-based metrics (e.g. `grocery_nearest_m`) are inverted before this
step, since closer = better:

```
x_for_normalization = -distance
```

## Direction

Sign is applied **before** normalization, at ingestion time, so every
value flowing into `scores` already means "higher is better":

| Raw signal                         | Direction | Handling                          |
| ----------------------------------- | --------- | ---------------------------------- |
| grocery/gym/cafe count, closeness   | Positive  | normalize as-is                    |
| transit stop count/closeness        | Positive  | normalize as-is                    |
| school count/rating/closeness       | Positive  | normalize as-is                    |
| running trail count/closeness, Strava segment popularity (`trailPopularity`, an underlying metric) | Positive | normalize as-is; see note below on Strava's optional data |
| airport drive time                  | Positive  | invert (lower drive time = better) |
| restaurant (amenity=restaurant) / bar (amenity=bar, pub, biergarten) count and closeness | Positive | normalize as-is (70% proximity / 30% density, like other POIs) |
| premium retail (Whole Foods / Starbucks / Target) (`premiumRetail`, an underlying metric) | Positive | single `premium_retail_raw` bonus signal built at ingestion from the three `*_nearest_m` columns; normalize as-is |
| gas station/convenience store count | Negative  | invert before normalizing          |
| congestion proxy                    | Negative  | invert before normalizing          |
| noise corridor (API key `emergencyCorridor`) | Negative  | invert before normalizing, then reduced by `street_orientation` (side_street dampens the penalty; facing_corridor does not). Uses `emergency_corridor_facility_raw` (fire/police/EMS facility count and closeness, `emergency_facility_*` columns); where that is null it falls back per cell to the v1 `emergency_corridor_proxy_raw`. |

This matches the Scoring Factors table in `PROJECT.md`.

**Noise corridor** is the user-facing name of the `emergency_corridor_score` factor (API key `emergencyCorridor`; DB columns unchanged): main roads near fire stations, hospitals and police stations, where sirens and through-traffic noise are most likely. It is a rough proxy, weight 0.75.

**Underlying metrics.** `premium_retail_score` and `trail_popularity_score` (API keys `premiumRetail`, `trailPopularity`) count toward the composite exactly like the others, but the website does not expose them as toggles (`CategorySpec.underlying`, `UNDERLYING_SCORE_COLUMNS` in `scoring/engine.py`; `UNDERLYING_FACTOR_KEYS` in `api/mapdata.py`). Scores, weights and API behaviour are unchanged: an omitted `factors` parameter means all 14 factors; an explicit list means exactly those.

**Strava segment popularity is optional data, not optional-with-a-zero-
penalty.** `strava_segment_popularity_raw` is `null` (not `0`) whenever
Strava credentials aren't configured or no segments exist nearby — trail
popularity for a cohort with no Strava data at all still normalizes
correctly off the OSM trail count/distance signal alone (see
`scoring/engine.py`'s blend for `trail_popularity_score`), it just can't
distinguish "trail exists" from "trail is actually popular" until Strava
data lands. Never backfill a missing Strava value with `0` — that would
read as "definitely unpopular," which isn't what "not measured yet" means.

## Schools (v2)

School proximity+density and school rating are each min-max normalized
separately, then blended **20% proximity+density / 80% rating** (trails keep
their 67/33 blend). When a cell has **no rating**, `school_score` is **NULL**
— never a proximity-only substitute — so the factor drops out of the
composite (which re-weights over the non-null factors). The engine still
writes `school_proximity_score` (the normalized proximity+density part) for
every cell with any school data, so clients can say "proximity 72, rating
unavailable". It is informational and is not a composite factor.
`school_district_*` and `school_rating_source` record where a rating came from.

## Composite score

Weighted average of normalized sub-scores:

```
composite_score = Σ(weight_i * subscore_i) / Σ(weight_i)
```

Weights are hand-tuned for `weights_version = 'v1-handtuned'` (11 factors)
and `'v2-handtuned'` (14 factors: adds restaurant 1.0, bar 0.5,
premiumRetail 0.75; noise corridor 0.5 -> 0.75) — there's no
training data to fit against yet. **Weight rationale must be documented
alongside the weights themselves** (e.g. in the ingestion/scoring job, not
just in code) since this is the defensibility story for both users
("why did this weight matter") and future ML refinement (a baseline to
compare a learned model against).

## Versioning

`scores.weights_version` lets weight changes ship without losing score
history — a new version gets new rows rather than overwriting. The API
(`ScoreResponse.weightsVersion`) always reports which version produced a
given response.
