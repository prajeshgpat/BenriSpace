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

from api.schemas import SubScores

# Human-facing names for each SubScores field (snake_case, matching the
# Pydantic field names -- CamelModel handles the wire-format camelCase
# separately).
FACTOR_LABELS: dict[str, str] = {
    "grocery": "grocery access",
    "gym": "gym access",
    "cafe": "cafe access",
    "gas_station": "distance from gas stations",
    "convenience_store": "distance from convenience stores",
    "transit": "transit access",
    "school": "school quality and proximity",
    "road": "road and traffic conditions",
    "emergency_corridor": "distance from emergency-vehicle corridors",
    "airport": "airport drive time",
}


def build_explanation(sub_scores: SubScores) -> str:
    """Rule-based explanation: calls out the strongest and weakest
    normalized sub-scores by name, then lists the rest. All SubScores
    values are already 0-100 with direction applied (openapi.yaml's
    SubScores description, enforced in scoring/engine.py before storage),
    so "highest" always means "most favorable" here -- no sign-flipping
    needed in this module."""
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

    sentences = [f"This location's strongest factor is {best_label} ({best_value:.0f}/100)."]
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

    return " ".join(sentences)
