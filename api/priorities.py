"""The `factors` (and optional `weights`) query params shared by /improve,
/similar and the two explanation endpoints: the user's selected priorities.

Parsing and weighting reuse api/mapdata.py (same keys and semantics as
/map/top). Omitted `factors` means the 12 toggleable factors (the website's
toggles), not the two underlying metrics (premiumRetail, trailPopularity).
`explicit` records whether the caller chose anything, so endpoints can keep
their stored-composite behaviour when nothing was chosen.
"""

from dataclasses import dataclass

from api.mapdata import (
    FACTOR_COLUMNS,
    UNDERLYING_FACTOR_KEYS,
    ScoreSpec,
    composite_from_row,
    parse_factors,
    parse_weights,
)

TOGGLEABLE_FACTORS: tuple[str, ...] = tuple(
    k for k in FACTOR_COLUMNS if k not in UNDERLYING_FACTOR_KEYS
)


@dataclass(frozen=True)
class Priorities:
    spec: ScoreSpec
    explicit: bool

    @property
    def factors(self) -> list[str]:
        return self.spec.factors

    @property
    def columns(self) -> list[str]:
        return [FACTOR_COLUMNS[f] for f in self.spec.factors]

    @property
    def cache_part(self) -> str:
        """Stable text for cache keys: sorted factors with their weights."""
        return ",".join(f"{f}:{self.spec.weights[f]:g}" for f in sorted(self.spec.factors))

    def ordered_by_weight(self) -> list[str]:
        """Selected factors, heaviest first (ties keep contract order)."""
        return sorted(self.spec.factors, key=lambda f: -self.spec.weights[f])

    def composite_from_columns(self, row: dict) -> float | None:
        """Weighted composite of a `scores` row over the selected factors."""
        return composite_from_row(row, self.spec)

    def composite_from_keys(self, sub_scores: dict) -> float | None:
        """Same, for a dict keyed by wire factor keys (camelCase)."""
        total = weighted = 0.0
        for f in self.spec.factors:
            value = sub_scores.get(f)
            if value is None:
                continue
            weighted += self.spec.weights[f] * float(value)
            total += self.spec.weights[f]
        return weighted / total if total else None


def parse_priorities(factors: str | None, weights: str | None = None) -> Priorities:
    """Raises api.mapdata.InvalidMapRequest on bad input (routes return 400)."""
    if factors is None:
        used = list(TOGGLEABLE_FACTORS)
    else:
        used = parse_factors(factors)
    parsed_weights = parse_weights(weights, used)
    return Priorities(ScoreSpec(used, parsed_weights), explicit=factors is not None or weights is not None)
