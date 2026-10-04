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

**Noise corridor** is the user-facing name of the `emergency_corridor_score` factor (API key `emergencyCorridor`; DB columns unchanged): main roads near fire stations, hospitals and police stations, where sirens and through-traffic noise are most likely (v2.1 also counts gas stations and convenience stores right next door). It is a rough proxy, weight 0.75 in v2 and 12 in v2.1.

**v2.1 (`weights_version = 'v2.1-handtuned'`).** Every factor is a user-facing pill (13, none hidden). Same min-max engine shape, with these changes (`CATEGORY_SPECS_V2_1` in `scoring/engine.py`):

| API key | `scores` column | Raw signal (higher is better) |
| --- | --- | --- |
| `shopping` | `shopping_score` | `shopping_raw` (0.6 proximity to the 3rd-nearest shop + 0.4 variety of retail groups within 1 mi; `ingestion/osm_retail_parks.py`) + 0.08 x `premium_retail_raw` anchor bonus |
| `gasConvenience` | `gas_convenience_score` | one positive factor: the 70/30 nearest/count blend over the union of gas stations and convenience stores (existing `gas_station_*` and `convenience_store_*` columns) |
| `emergencyCorridor` | `emergency_corridor_score` | negative: the corridor/facility raw signal (damped for side streets) PLUS an adjacency penalty from the nearest gas station and nearest convenience store (full within 300 ft, linear to 0 at 800 ft; `adjacency_share`, `gas_convenience_adjacency_penalty`) |
| `traffic` | `road_score` | unchanged (renamed in the UI and API only) |
| `recreation` | `recreation_score` | 75% `recreation_raw` (parks: 2/3 proximity + 1/3 size of the largest park within half a mile) + 25% the existing trail count/closeness signal, each normalized separately |

The gas station / convenience store columns therefore feed two factors at different distances: a positive `gasConvenience` and a negative adjacency term inside the noise corridor. New feature_store columns are in imperial units (`shopping_nearest_ft`, `park_largest_sq_ft_half_mi`, ...), migration `0009_v2_1.sql`. Default weights: grocery 14, transit 14, emergencyCorridor 12, restaurant 10, school 10, gym 9, cafe 8, gasConvenience 6, bar 5, airport 5, recreation 5, shopping 4, traffic 4 (only the ratios matter). v2 rows keep working: the API reads a v2 row's Shopping from `premium_retail_score` and Recreation from `trail_popularity_score`, and its `gasConvenience` is null. Legacy API keys (`premiumRetail`, `trailPopularity`, `road`, `gasStation`, `convenienceStore`) are aliases.

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

**Current serving state.** The scorer writes `v2-handtuned` rows next to the
existing `v1-handtuned` rows. The API serves whichever version its
`SCORING_WEIGHTS_VERSION` setting names; the code default is `v1-handtuned`,
but production has been set to `v2-handtuned` since the cutover (2026-10-03,
64,320 rows). School rating is still `null` ("No data") where a district has
no rating.

**Known weakness (v3 candidate).** Min-max normalization is skewed by outlier
distances: a few very far nearest-feature distances stretch the range, which
compresses everyone else and lets remote cells with little around them score
high on restaurant and bar. A more robust scheme (percentile ranks, or
clipped/log-scaled distances) is a scoring v3 candidate.

## Cohorts and areas

Normalization is per `metro_area` cohort of geohash6 grid cells (about 0.6 x 0.4
miles each). Scores for a road-bounded area (`GET /v1/area`) are not
normalized separately: they are the area-weighted average of the overlapping
cells' latest scores, so small areas inherit similar scores until per-polygon
scoring exists.
