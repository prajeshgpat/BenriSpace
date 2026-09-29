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
| airport drive time                  | Positive  | invert (lower drive time = better) |
| gas station/convenience store count | Negative  | invert before normalizing          |
| congestion proxy                    | Negative  | invert before normalizing          |
| emergency corridor proxy            | Negative  | invert before normalizing, then reduced by `street_orientation` (side_street dampens the penalty; facing_corridor does not) |

This matches the Scoring Factors table in `PROJECT.md`.

## Composite score

Weighted average of normalized sub-scores:

```
composite_score = Σ(weight_i * subscore_i) / Σ(weight_i)
```

Weights are hand-tuned for `weights_version = 'v1-handtuned'` — there's no
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
