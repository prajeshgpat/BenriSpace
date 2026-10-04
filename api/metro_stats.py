"""Per-factor score distribution (mean, std, 0..100th percentile cut points).

One aggregate query per (weights version, metro) the first time it is needed,
then cached for the life of the process, so request handlers never scan the
~64k score rows. The mean/std match the z-scoring in scoring/embeddings.py
(population std over non-null values, per metro), which /similar needs to
re-rank by a subset of factors; the cut points give a factor's metro
percentile for the explanation evidence.
"""

import bisect
import contextlib
import sys
from dataclasses import dataclass

from api.factors import FACTOR_COLUMNS
from scoring.engine import LEGACY_FALLBACK_COLUMNS

# Stats are kept for the 13 factor columns (a v2 row's Shopping / Recreation are
# read through their legacy columns, so one query covers either version).
STATS_COLUMNS: tuple[str, ...] = tuple(FACTOR_COLUMNS.values())

QUANTILE_POINTS = 101  # cut points at 0%, 1%, ... 100%


@dataclass(frozen=True)
class ColumnStats:
    mean: float
    std: float
    quantiles: tuple[float, ...]  # QUANTILE_POINTS ascending values

    def percentile(self, value: float) -> int:
        """Share (0-100) of rows scoring at or below `value`."""
        if not self.quantiles:
            return 50
        return max(0, min(100, bisect.bisect_right(self.quantiles, float(value)) - 1))

    @property
    def median(self) -> float:
        return self.quantiles[len(self.quantiles) // 2] if self.quantiles else self.mean


MetroStats = dict[str, ColumnStats]  # score column -> stats

_CACHE: dict[tuple[str, str | None], MetroStats] = {}
_FRACTIONS = "array[" + ",".join(f"{i / 100:.2f}" for i in range(QUANTILE_POINTS)) + "]::float8[]"


def _sql(by_metro: bool) -> str:
    parts = []
    for c in STATS_COLUMNS:
        e = f"coalesce(s.{c}, s.{LEGACY_FALLBACK_COLUMNS[c]})" if c in LEGACY_FALLBACK_COLUMNS else f"s.{c}"
        parts.append(
            f"avg({e})::float8 as {c}_mean, stddev_pop({e})::float8 as {c}_std, "
            f"percentile_cont({_FRACTIONS}) within group (order by {e}) as {c}_q"
        )
    join = "join geo_entities ge on ge.id = s.geo_entity_id " if by_metro else ""
    where = "s.weights_version = %s" + (" and ge.metro_area = %s" if by_metro else "")
    return f"select {', '.join(parts)} from scores s {join}where {where}"


def _from_row(row: dict) -> MetroStats:
    out: MetroStats = {}
    for c in STATS_COLUMNS:
        mean, std, q = row.get(f"{c}_mean"), row.get(f"{c}_std"), row.get(f"{c}_q")
        if mean is None or not q:
            continue
        out[c] = ColumnStats(float(mean), float(std or 0.0), tuple(float(x) for x in q))
    return out


def get_stats(conn, weights_version: str, metro_area: str | None = None) -> MetroStats | None:
    """Cached stats, or None when they cannot be loaded (callers degrade)."""
    key = (weights_version, metro_area)
    if key in _CACHE:
        return _CACHE[key]
    try:
        params = (weights_version, metro_area) if metro_area else (weights_version,)
        with conn.cursor() as cur:
            cur.execute(_sql(metro_area is not None), params)
            row = cur.fetchone()
        stats = _from_row(dict(row)) if row else {}
    except Exception as exc:  # noqa: BLE001 - stats are an enhancement, never fatal
        print(f"metro_stats: {type(exc).__name__}; continuing without", file=sys.stderr)
        with contextlib.suppress(Exception):
            conn.rollback()
        return None
    if not stats:
        return None
    _CACHE[key] = stats
    return stats


def clear_cache() -> None:
    _CACHE.clear()
