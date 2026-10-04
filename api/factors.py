"""The 13 user-facing scoring factors: wire keys, `scores` columns, legacy aliases
and default weights. Pure data; shared by api/lookup.py and api/mapdata.py."""

import re

from scoring.engine import V2_1_WEIGHTS

# Wire factor key -> `scores` column (the 13 user-facing factors; none hidden).
# The only place that maps them; ordering is the contract's FactorKey order.
# tests/test_mapdata.py fails if a v2.1 category is added to
# scoring.engine.CATEGORY_SPECS_V2_1 without a row here.
# v2 rows hold Shopping / Recreation under their legacy columns and have no Gas &
# Convenience score: see scoring.engine.LEGACY_FALLBACK_COLUMNS.
FACTOR_COLUMNS: dict[str, str] = {
    "grocery": "grocery_score",
    "gym": "gym_score",
    "cafe": "cafe_score",
    "restaurant": "restaurant_score",
    "bar": "bar_score",
    "shopping": "shopping_score",
    "gasConvenience": "gas_convenience_score",
    "transit": "transit_score",
    "school": "school_score",
    "traffic": "road_score",
    "emergencyCorridor": "emergency_corridor_score",
    "airport": "airport_score",
    "recreation": "recreation_score",
}

# Old (v1/v2-era) wire keys, accepted wherever `factors` or `weights` are parsed
# and mapped onto the 13 factors above. Several old keys can map to one factor
# (gasStation and convenienceStore -> gasConvenience); the result is deduplicated.
FACTOR_ALIASES: dict[str, str] = {
    "premiumRetail": "shopping",
    "trailPopularity": "recreation",
    "road": "traffic",
    "gasStation": "gasConvenience",
    "convenienceStore": "gasConvenience",
}


def canonical_factor(key: str) -> str | None:
    """The current factor key for a current or legacy key, else None."""
    if key in FACTOR_COLUMNS:
        return key
    return FACTOR_ALIASES.get(key)


# Default relative weight per factor (SCORING_FRAMEWORK.md section 2); only the
# ratios matter because the composite is normalized by the weight of the factors
# that have a score.
DEFAULT_FACTOR_WEIGHTS: dict[str, float] = {
    key: V2_1_WEIGHTS[column] for key, column in FACTOR_COLUMNS.items()
}



def to_snake(camel: str) -> str:
    """'gasConvenience' -> 'gas_convenience' (the SubScores field name)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", camel).lower()
