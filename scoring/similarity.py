"""Similar-areas helpers: the 13 factor dimensions and their z-scores.

/v1/similar compares cells on the 13 v2.1 factor scores, each z-scored against its metro
(mean and population std over the non-null values, api/metro_stats.py), so every factor
counts equally regardless of its spread. A NULL score counts as the metro average (z = 0).
The distance is computed in SQL over the stored smallint sub-scores (api/similar.py); no
embedding column or vector index is stored (a 64k-cell HNSW index cost ~46 MB, more than
the scores it indexed).
"""

import math

# The ordered dimensions: the user-facing factor score columns (api/factors.py order).
SIMILARITY_COLUMNS: tuple[str, ...] = (
    "grocery_score",
    "gym_score",
    "cafe_score",
    "restaurant_score",
    "bar_score",
    "shopping_score",
    "gas_convenience_score",
    "transit_score",
    "school_score",
    "road_score",
    "emergency_corridor_score",
    "airport_score",
    "recreation_score",
)
SIMILARITY_DIM = len(SIMILARITY_COLUMNS)


def column_stats(rows: list[dict], column: str) -> tuple[float, float]:
    """(mean, population std) over the non-null values; (0.0, 0.0) when none."""
    values = [float(r[column]) for r in rows if r.get(column) is not None]
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, math.sqrt(var)


def zscore(value: float | None, mean: float, std: float) -> float:
    """z-score, 0.0 for a missing value or a zero-variance column."""
    if value is None or std <= 0:
        return 0.0
    return (float(value) - mean) / std
