"""**Phase 1 placeholder** for Phase 3's real RAG/LLM score explanation
generation (PHASES.md Phase 3: "Score explanation generation -- retrieve an
address's stored factor breakdown, generate the human-readable 'why this
scored 8.4' explanation"). No LLM API key exists yet -- common/config.py's
ANTHROPIC_API_KEY/OPENAI_API_KEY are unset until Phase 3's provider
decision lands (PHASES.md Phase 3 Requirements) -- so this module builds
the explanation with plain string formatting/rules over the stored
SubScores instead of a generation call.

**Swap point for Phase 3**: replace `build_explanation()` below with a real
RAG call (retrieve feature_store/scores row -> prompt -> LLM, constrained
to only discuss retrieved data per PROJECT.md's RAG rationale). Nothing
outside this file should need to change -- api/main.py's explanation route
only calls build_explanation(sub_scores) and wraps the string result in
ExplanationResponse, so this is a one-file replacement, not a route
rewrite.
"""

import re

from api.schemas import SubScores
from common.units import format_distance, m_to_mi

# Wire FactorKey -> feature_store column(s) holding the nearest-feature
# distance in metres; several columns mean "nearest of these".
NEAREST_COLUMNS: dict[str, tuple[str, ...]] = {
    "grocery": ("grocery_nearest_m",),
    "gym": ("gym_nearest_m",),
    "cafe": ("cafe_nearest_m",),
    "restaurant": ("restaurant_nearest_m",),
    "bar": ("bar_nearest_m",),
    "gasStation": ("gas_station_nearest_m",),
    "convenienceStore": ("convenience_store_nearest_m",),
    "transit": ("transit_nearest_m",),
    "school": ("school_nearest_m",),
    "trailPopularity": ("running_trail_nearest_m",),
    "premiumRetail": ("whole_foods_nearest_m", "starbucks_nearest_m", "target_nearest_m"),
    "emergencyCorridor": ("emergency_facility_nearest_m",),
}
FEATURE_STORE_NEAREST_COLUMNS = tuple(c for cols in NEAREST_COLUMNS.values() for c in cols)


def _snake_to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def nearest_m_by_factor(feature_row: dict | None) -> dict[str, float | None]:
    """FactorKey -> nearest-feature distance in metres (None when unknown),
    for the factors that have one. Internals stay metric."""
    row = feature_row or {}
    out: dict[str, float | None] = {}
    for factor, columns in NEAREST_COLUMNS.items():
        values = [float(row[c]) for c in columns if row.get(c) is not None]
        out[factor] = min(values) if values else None
    return out


def nearest_mi_by_factor(feature_row: dict | None) -> dict[str, float | None]:
    """Same as nearest_m_by_factor but in miles, for ExplanationResponse.nearestMi."""
    return {
        factor: None if meters is None else round(m_to_mi(meters), 3)
        for factor, meters in nearest_m_by_factor(feature_row).items()
    }

# Human-facing names for each SubScores field (snake_case, matching the
# Pydantic field names -- CamelModel handles the wire-format camelCase
# separately).
FACTOR_LABELS: dict[str, str] = {
    "grocery": "grocery access",
    "gym": "gym access",
    "cafe": "cafe access",
    "restaurant": "restaurant access",
    "bar": "bar and pub access",
    "premium_retail": "access to premium retail (Whole Foods, Starbucks, Target)",
    "gas_station": "distance from gas stations",
    "convenience_store": "distance from convenience stores",
    "transit": "transit access",
    "school": "school quality and proximity",
    "road": "road and traffic conditions",
    "emergency_corridor": "distance from the noise corridor",
    "airport": "airport drive time",
    "trail_popularity": "access to popular running and walking trails",
}


def _priority_sentence(values: dict[str, float], priorities: list[str]) -> str | None:
    """Lead sentence naming the user's strongest and weakest selected factors."""
    chosen = {to_snake(k): values[to_snake(k)] for k in priorities if to_snake(k) in values}
    if not chosen:
        return None
    best, worst = max(chosen, key=chosen.get), min(chosen, key=chosen.get)
    if best == worst:
        return f"For your priorities, {FACTOR_LABELS.get(best, best)} scores {chosen[best]:.0f}/100."
    return (
        f"For your priorities, {FACTOR_LABELS.get(best, best)} is strongest "
        f"({chosen[best]:.0f}/100) and {FACTOR_LABELS.get(worst, worst)} is weakest "
        f"({chosen[worst]:.0f}/100)."
    )


def to_snake(camel: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", camel).lower()


def build_explanation(
    sub_scores: SubScores,
    nearest_m: dict[str, float | None] | None = None,
    priorities: list[str] | None = None,
) -> str:
    """Rule-based explanation: calls out the strongest and weakest
    normalized sub-scores by name, then lists the rest. All SubScores
    values are already 0-100 with direction applied (openapi.yaml's
    SubScores description, enforced in scoring/engine.py before storage),
    so "highest" always means "most favorable" here -- no sign-flipping
    needed in this module. `nearest_m` (from nearest_m_by_factor) optionally
    adds the nearest-feature distances, always formatted in feet/miles."""
    values = {
        field: value
        for field, value in sub_scores.model_dump(by_alias=False).items()
        if value is not None
    }
    if not values:
        return "No sub-score breakdown is available for this location yet."

    best_field = max(values, key=values.get)
    worst_field = min(values, key=values.get)
    best_label, best_value = FACTOR_LABELS.get(best_field, best_field), values[best_field]
    worst_label, worst_value = FACTOR_LABELS.get(worst_field, worst_field), values[worst_field]

    sentences = []
    if priorities:
        lead = _priority_sentence(values, priorities)
        if lead:
            sentences.append(lead)
    sentences += [f"This location's strongest factor is {best_label} ({best_value:.0f}/100)."]
    if worst_field != best_field:
        sentences.append(f"Its weakest factor is {worst_label} ({worst_value:.0f}/100).")

    remaining = sorted(
        ((field, v) for field, v in values.items() if field not in (best_field, worst_field)),
        key=lambda item: -item[1],
    )
    if remaining:
        summary = ", ".join(
            f"{FACTOR_LABELS.get(field, field)} {v:.0f}/100" for field, v in remaining
        )
        sentences.append(f"Other factors: {summary}.")

    nearest_parts = []
    for field in dict.fromkeys((best_field, worst_field)):
        text = format_distance((nearest_m or {}).get(_snake_to_camel(field)))
        if text:
            nearest_parts.append(f"{FACTOR_LABELS.get(field, field)} {text}")
    if nearest_parts:
        sentences.append(f"Nearest feature: {', '.join(nearest_parts)}.")

    return " ".join(sentences)
