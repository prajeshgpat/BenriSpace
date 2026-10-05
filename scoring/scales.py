"""Factor scales: the per-metro normalization constants of a scoring run, kept so
a location that is not a grid cell can be scored on demand with no per-cell
storage (scoring/point.py, api/point_score.py).

The engine (scoring/engine.py) maps each raw "goodness" value to 0-100 against its
metro cohort: v2.1 clips at the cohort's p2 / p98 and scales linearly between
them (`robust_normalize`); v2 uses plain min-max. A cohort therefore reduces to
two numbers per signal, and a scale is exactly those two numbers. `compute_scales`
derives them with the engine's OWN raw functions and percentile helper, so
`score_row(row, ..., compute_scales(cohort))` equals `score_metro_cohort(cohort)[row]`
(tests/test_scales.py asserts it).

Signals (the "component" of a scale), per category spec:
  primary           raw goodness (count / nearest blend, single column or raw_fn)
  rating            the spec's rating column (school rating, Strava popularity)
  secondary         the secondary spec's goodness (Recreation's trail signal)
  secondary_rating  the secondary spec's rating column

Quirk reproduced on purpose: the engine normalizes a secondary spec with plain
min-max even in v2.1 (`_spec_scores(feature_rows, spec.secondary)` passes no
normalizer), so those two components are min-max scales, not robust ones.

Pure module: no DB access.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from scoring.engine import (
    ROBUST_CLIP_PERCENTILES,
    WEIGHTS_VERSION_V2_1,
    CategorySpec,
    _percentile,
    compute_composite,
    compute_rating_raw,
    compute_raw_goodness,
    specs_and_weights,
)

PRIMARY = "primary"
RATING = "rating"
SECONDARY = "secondary"
SECONDARY_RATING = "secondary_rating"
COMPONENTS = (PRIMARY, RATING, SECONDARY, SECONDARY_RATING)


@dataclass(frozen=True)
class Scale:
    """0-100 = clamp((value - lo) / (hi - lo)). lo == hi means a degenerate
    cohort, which the engine scores a neutral 50. `n` is the cohort size."""

    lo: float
    hi: float
    n: int = 0


# {score_column: {component: Scale}} for one (weights_version, metro_area).
Scales = dict[str, dict[str, Scale]]


def uses_robust_scale(weights_version: str) -> bool:
    return weights_version == WEIGHTS_VERSION_V2_1


def scale_from_values(values: Iterable[float], robust: bool) -> Scale | None:
    """The scale `robust_normalize` (robust) or `min_max_normalize` would apply to
    a cohort holding these values; None for an empty cohort."""
    ordered = sorted(values)
    if not ordered:
        return None
    if robust:
        lo = _percentile(ordered, ROBUST_CLIP_PERCENTILES[0])
        hi = _percentile(ordered, ROBUST_CLIP_PERCENTILES[1])
        if hi > lo:
            return Scale(lo, hi, len(ordered))
        # Degenerate spread: robust_normalize falls back to plain min-max.
    return Scale(ordered[0], ordered[-1], len(ordered))


def apply_scale(value: float, scale: Scale) -> float:
    """0-100 for one raw value; out-of-cohort values clamp to the ends."""
    if scale.hi <= scale.lo:
        return 50.0
    return min(100.0, max(0.0, (value - scale.lo) / (scale.hi - scale.lo) * 100.0))


def compute_scales(feature_rows: list[dict], weights_version: str) -> Scales:
    """Scales for ONE metro cohort of feature_store rows (same input as
    `score_metro_cohort`). Components with no data in the cohort are omitted."""
    specs, _ = specs_and_weights(weights_version)
    robust = uses_robust_scale(weights_version)
    out: Scales = {}
    for spec in specs:
        comps: dict[str, Scale] = {}

        def add(name: str, values: list[float], robust_scale: bool, comps=comps) -> None:
            scale = scale_from_values(values, robust_scale)
            if scale is not None:
                comps[name] = scale

        add(PRIMARY, _collect(feature_rows, spec, compute_raw_goodness), robust)
        if spec.rating_column is not None:
            add(RATING, _collect(feature_rows, spec, compute_rating_raw), robust)
        if spec.secondary is not None:
            add(SECONDARY, _collect(feature_rows, spec.secondary, compute_raw_goodness), False)
            if spec.secondary.rating_column is not None:
                add(
                    SECONDARY_RATING,
                    _collect(feature_rows, spec.secondary, compute_rating_raw),
                    False,
                )
        out[spec.score_column] = comps
    return out


def _collect(rows: list[dict], spec: CategorySpec, fn) -> list[float]:
    values = []
    for row in rows:
        value = fn(row, spec)
        if value is not None:
            values.append(value)
    return values


def _blend_spec(
    row: dict, spec: CategorySpec, comps: dict[str, Scale], primary_key: str, rating_key: str
):
    """(category score, proximity+density part) for one row and one spec, before
    any secondary blend; mirrors engine._spec_scores for a single row."""
    raw = compute_raw_goodness(row, spec)
    scale = comps.get(primary_key)
    if raw is None or scale is None:
        return None, None
    pd_score = apply_scale(raw, scale)
    if spec.rating_column is None:
        return pd_score, pd_score
    rating = compute_rating_raw(row, spec)
    rating_scale = comps.get(rating_key)
    rating_score = (
        None if rating is None or rating_scale is None else apply_scale(rating, rating_scale)
    )
    if rating_score is None:
        if spec.missing_rating == "null":
            return None, pd_score
        return pd_score, pd_score
    return (1 - spec.rating_weight) * pd_score + spec.rating_weight * rating_score, pd_score


def score_row(row: dict, weights_version: str, scales: Scales) -> dict[str, float]:
    """The scores dict `score_metro_cohort` would give this raw row if it were in
    the cohort the scales came from: {score_column: 0-100, ..., 'composite_score'}.
    Empty when no factor has a score."""
    specs, weights = specs_and_weights(weights_version)
    sub_scores: dict[str, float] = {}
    extras: dict[str, float] = {}
    for spec in specs:
        comps = scales.get(spec.score_column, {})
        final, primary = _blend_spec(row, spec, comps, PRIMARY, RATING)
        if spec.proximity_score_column and primary is not None:
            extras[spec.proximity_score_column] = primary
        if spec.secondary is not None:
            sec_comps = {PRIMARY: comps.get(SECONDARY), RATING: comps.get(SECONDARY_RATING)}
            sec_comps = {k: v for k, v in sec_comps.items() if v is not None}
            second, _ = _blend_spec(row, spec.secondary, sec_comps, PRIMARY, RATING)
            w = spec.secondary_weight
            if final is None:
                final = second
            elif second is not None:
                final = (1 - w) * final + w * second
        if final is not None:
            sub_scores[spec.score_column] = final
    if not sub_scores:
        return {}
    return {**sub_scores, **extras, "composite_score": compute_composite(sub_scores, weights)}


# --- (de)serialization for the `score_scales` table -------------------------


def scales_to_rows(weights_version: str, metro_area: str, scales: Scales) -> list[tuple]:
    """Flat tuples (weights_version, metro_area, factor, component, lo, hi, n)."""
    return [
        (weights_version, metro_area, factor, component, s.lo, s.hi, s.n)
        for factor, comps in scales.items()
        for component, s in comps.items()
    ]


def scales_from_rows(rows: Iterable[dict]) -> Scales:
    """Inverse of scales_to_rows; rows are dicts with factor, component, lo, hi, n."""
    out: Scales = {}
    for r in rows:
        out.setdefault(r["factor"], {})[r["component"]] = Scale(
            float(r["lo"]), float(r["hi"]), int(r.get("n") or 0)
        )
    return out


# feature_store columns the scales (and score_row) read: the spec columns plus the
# keys the v2.1 raw functions look up. tests/test_scales.py fails if this drifts.
RAW_FN_COLUMNS = (
    "gas_station_count_500m",
    "gas_station_nearest_m",
    "convenience_store_count_500m",
    "convenience_store_nearest_m",
    "shopping_raw",
    "premium_retail_raw",
    "emergency_corridor_facility_raw",
    "emergency_corridor_proxy_raw",
    "street_orientation",
)


def scale_feature_columns(weights_version: str) -> list[str]:
    """Distinct feature_store columns needed to compute scales for a version, so
    the runtime fallback can select a narrow slice instead of `feature_store.*`."""
    specs, _ = specs_and_weights(weights_version)
    cols: dict[str, None] = {}

    def visit(spec: CategorySpec) -> None:
        for c in (
            spec.count_column,
            spec.nearest_column,
            spec.rating_column,
            spec.single_column,
            spec.fallback_single_column,
        ):
            if c:
                cols[c] = None
        if spec.secondary is not None:
            visit(spec.secondary)

    for spec in specs:
        visit(spec)
    for c in RAW_FN_COLUMNS:
        cols[c] = None
    return list(cols)
