"""GET /v1/similar: areas with a similar factor profile, found with pgvector.

Each scored cell has a 14-dim z-scored embedding (scoring/embeddings.py). The
nearest neighbours by L2 distance, spread out geographically, are returned with
the factors on which they differ most. With `factors` the over-fetched pool is
re-ranked on the selected factors only (z-scores from api/metro_stats.py, which
match scoring/embeddings.py). Distances shown are imperial.
"""

import math

import psycopg

from api.areas import bounded_by_text, pick_area, usable_areas
from api.factors import FACTOR_COLUMNS
from api.lookup import neighborhood_map
from api.metro_stats import MetroStats
from api.priorities import Priorities
from common.db import get_area_candidates
from common.geo import haversine_m
from common.places import compass
from common.units import M_PER_MI, format_distance
from scoring.embeddings import EMBEDDING_COLUMNS, EMBEDDING_DIM, zscore
from scoring.engine import LEGACY_FALLBACK_COLUMNS

# L2 distance (in z-score units, 14 dims) at which similarity reaches 0. Two
# unrelated cells sit roughly 5 apart, so 6.0 spreads 0..100 usefully.
SIMILARITY_MAX_DIST = 6.0
DIFF_MIN_POINTS = 6
MAX_DIFFS = 3
OVERFETCH_FACTOR = 20
OVERFETCH_MAX = 200
# Used for the z-score when metro stats cannot be loaded: a typical factor
# spread (points), so re-ranking still works, just less precisely.
FALLBACK_STD = 25.0

# Short labels for the summary sentence, keyed by score column.
SHORT_LABELS: dict[str, str] = {
    "grocery_score": "grocery",
    "gym_score": "gyms",
    "cafe_score": "cafes",
    "restaurant_score": "restaurants",
    "bar_score": "bars",
    "shopping_score": "shopping",
    "gas_convenience_score": "gas and convenience",
    "transit_score": "transit",
    "school_score": "schools",
    "road_score": "traffic",
    "emergency_corridor_score": "noise",
    "airport_score": "airport access",
    "recreation_score": "parks and trails",
}

# The 13 factor columns, in wire order; wire key per column.
FACTOR_SCORE_COLUMNS: tuple[str, ...] = tuple(FACTOR_COLUMNS.values())
_KEY_BY_COLUMN = {column: key for key, column in FACTOR_COLUMNS.items()}


def _select_expr(column: str) -> str:
    legacy = LEGACY_FALLBACK_COLUMNS.get(column)
    return f"coalesce(s.{column}, s.{legacy}) as {column}" if legacy else f"s.{column}"


# The 13 factor scores (v2 rows read Shopping / Recreation through their legacy
# columns) plus whatever legacy embedding columns are not factor columns.
_SCORE_SELECT = ", ".join(
    [
        *(_select_expr(c) for c in FACTOR_SCORE_COLUMNS),
        *(f"s.{c}" for c in EMBEDDING_COLUMNS if c not in FACTOR_SCORE_COLUMNS),
    ]
)


def overfetch_limit(k: int, wide: bool = False) -> int:
    """Candidates pulled by full-embedding distance; re-ranking by a factor
    subset needs the widest pool."""
    return OVERFETCH_MAX if wide else min(k * OVERFETCH_FACTOR, OVERFETCH_MAX)


def similarity(dist: float) -> int:
    """0-100 integer: 100 * max(0, 1 - dist / SIMILARITY_MAX_DIST), half up."""
    return int(100 * max(0.0, 1.0 - float(dist) / SIMILARITY_MAX_DIST) + 0.5)


def _round_signed(value: float) -> int:
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def factor_label(column: str) -> str:
    return SHORT_LABELS[column]


def differences(target: dict, row: dict, columns: tuple[str, ...] | list[str] | None = None):
    """Up to MAX_DIFFS factors where `row` differs from `target` by at least
    DIFF_MIN_POINTS, largest gap first (ties keep dimension order). delta > 0
    means `row` scores higher (better) than the target. `columns` limits which
    factors are compared (default all)."""
    found = []
    for column in FACTOR_SCORE_COLUMNS:
        if columns is not None and column not in columns:
            continue
        a, b = target.get(column), row.get(column)
        if a is None or b is None:
            continue
        delta = float(b) - float(a)
        if abs(delta) >= DIFF_MIN_POINTS:
            found.append((abs(delta), column, delta))
    found.sort(key=lambda item: -item[0])  # stable
    return [
        {
            "factor": _KEY_BY_COLUMN[column],
            "label": factor_label(column),
            "delta": _round_signed(delta),
        }
        for _, column, delta in found[:MAX_DIFFS]
    ]


def rerank(
    target: dict, candidates: list[dict], priorities: Priorities, stats: MetroStats | None
) -> list[dict]:
    """Candidates re-ordered by weighted Euclidean distance over only the
    selected factors, on the same z-scores the embedding uses (stats are the
    metro's mean/std, a missing score counts as average). Weights are scaled to
    sum to 14 so `dist` stays comparable with the full-embedding distance that
    `similarity()` is calibrated on. Returns copies with `dist` replaced."""
    spec = priorities.spec
    scale = EMBEDDING_DIM / sum(spec.weights[f] for f in spec.factors)
    dims = []
    for factor, column in zip(spec.factors, priorities.columns, strict=True):
        st = (stats or {}).get(column)
        mean, std = (st.mean, st.std) if st else (0.0, FALLBACK_STD)
        dims.append((column, mean, std, spec.weights[factor] * scale))
    tz = {c: zscore(target.get(c), m, sd) for c, m, sd, _ in dims}
    out = []
    for cand in candidates:
        total = sum(w * (zscore(cand.get(c), m, sd) - tz[c]) ** 2 for c, m, sd, w in dims)
        out.append({**cand, "dist": math.sqrt(total)})
    out.sort(key=lambda c: c["dist"])  # stable
    return out


def summary(diffs: list[dict]) -> str:
    if not diffs:
        return "Very similar across all factors."
    parts = []
    for d in diffs:
        n = abs(d["delta"])
        unit = "point" if n == 1 else "points"
        parts.append(f"{n} {unit} {'better' if d['delta'] > 0 else 'weaker'} for {d['label']}")
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + "."


def spread_out(
    lat: float, lon: float, candidates: list[dict], k: int, min_separation_mi: float
) -> list[dict]:
    """Walk candidates (nearest in embedding space first), keeping those at
    least min_separation_mi from the point and from every kept result."""
    min_m = min_separation_mi * M_PER_MI
    chosen: list[dict] = []
    for c in candidates:
        if haversine_m(lat, lon, c["latitude"], c["longitude"]) < min_m:
            continue
        if any(haversine_m(p["latitude"], p["longitude"], c["latitude"], c["longitude"]) < min_m
               for p in chosen):  # fmt: skip
            continue
        chosen.append(c)
        if len(chosen) == k:
            break
    return chosen


def fetch_target(conn, geo_entity_id: str, weights_version: str) -> dict | None:
    """The cell's score row if it has an embedding, else None (also None when
    migration 0007 has not been applied)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select s.composite_score, {_SCORE_SELECT}
                from scores s
                where s.geo_entity_id = %s and s.weights_version = %s
                  and s.embedding is not null
                """,
                (geo_entity_id, weights_version),
            )
            return cur.fetchone()
    except psycopg.errors.UndefinedColumn:
        conn.rollback()
        return None


# Nearest cells by L2 distance through pgvector's HNSW index (migration 0007): the
# target vector comes from an InitPlan so the planner keeps the index scan, and the
# inner LIMIT bounds the scan. The pool is wider than `limit` because z-scores are
# per metro, so some index hits belong to another metro and are dropped by the join.
NEIGHBOURS_SQL = f"""
select ge.geohash, ge.latitude, ge.longitude, s.composite_score, {_SCORE_SELECT}, s.dist
from (
    select *, embedding <-> (
               select embedding from scores where geo_entity_id = %(id)s and weights_version = %(v)s
           ) as dist
    from scores
    where weights_version = %(v)s and embedding is not null and geo_entity_id <> %(id)s
    order by embedding <-> (
               select embedding from scores where geo_entity_id = %(id)s and weights_version = %(v)s
           )
    limit %(pool)s
) s
join geo_entities ge on ge.id = s.geo_entity_id
where ge.metro_area = %(metro)s
order by s.dist
limit %(limit)s
"""

# Precomputed top-20 neighbours (similar_cells, migration 0011; scoring/embeddings.py).
PRECOMPUTED_SQL = f"""
select ge.geohash, ge.latitude, ge.longitude, s.composite_score, {_SCORE_SELECT},
       sc.distance as dist
from similar_cells sc
join geo_entities ge on ge.id = sc.neighbor_id
join scores s on s.geo_entity_id = sc.neighbor_id and s.weights_version = sc.weights_version
where sc.geo_entity_id = %s and sc.weights_version = %s
order by sc.rank
"""

PRECOMPUTED_MAX = 20
POOL_FACTOR = 3
POOL_MAX = 900


def _tune_hnsw(conn, pool: int) -> None:
    """Sizes the HNSW candidate list to the pool (default 40 would return too few
    rows once filtered) and turns on iterative scans where pgvector 0.8+ has them.
    Transaction-local; an older pgvector without the setting is left alone."""
    with conn.cursor() as cur:
        cur.execute("select set_config('hnsw.ef_search', %s, true)", (str(min(max(pool, 40), 1000)),))
        cur.execute("select current_setting('hnsw.iterative_scan', true) as v")
        row = cur.fetchone()
        if row and row["v"] is not None:
            cur.execute("select set_config('hnsw.iterative_scan', 'relaxed_order', true)")


def fetch_precomputed(conn, geo_entity_id: str, weights_version: str) -> list[dict]:
    """The cell's precomputed neighbours, nearest first; [] when none are stored
    or migration 0011 has not been applied."""
    try:
        with conn.cursor() as cur:
            cur.execute(PRECOMPUTED_SQL, (geo_entity_id, weights_version))
            return list(cur)
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        return []


def fetch_neighbours(
    conn,
    geo_entity_id: str,
    weights_version: str,
    metro_area: str,
    limit: int,
    spread: tuple[float, float, int, float] | None = None,
) -> list[dict]:
    """Up to `limit` nearest cells in embedding space. When `limit` fits the
    precomputed list and `spread` = (lat, lon, k, min_separation_mi) shows those
    neighbours still yield k spread-out results, the lookup is used; otherwise
    the HNSW index answers the query."""
    if spread is not None and limit <= PRECOMPUTED_MAX:
        pre = fetch_precomputed(conn, geo_entity_id, weights_version)
        lat, lon, k, min_sep = spread
        if pre and len(spread_out(lat, lon, pre, k, min_sep)) >= k:
            return pre[:limit]
    pool = min(limit * POOL_FACTOR, POOL_MAX)
    _tune_hnsw(conn, pool)
    with conn.cursor() as cur:
        cur.execute(
            NEIGHBOURS_SQL,
            {"id": geo_entity_id, "v": weights_version, "metro": metro_area,
             "pool": pool, "limit": limit},
        )  # fmt: skip
        return list(cur)


def area_label(conn, lat: float, lon: float) -> str | None:
    """Smallest road-bounded area containing the point, as 'Area bounded by ...'."""
    area = pick_area(lat, lon, usable_areas(get_area_candidates(conn, lat, lon)))
    if area is None:
        return None
    return bounded_by_text(list(area.get("bounded_by") or []))


def build_similar(
    conn,
    lat: float,
    lon: float,
    target: dict,
    candidates: list[dict],
    k: int,
    min_separation_mi: float,
    priorities: Priorities | None = None,
    stats: MetroStats | None = None,
) -> dict:
    """With an explicit `priorities` the over-fetched candidates are re-ranked on
    the selected factors before spacing; differences only cover selected factors."""
    columns = None
    if priorities is not None:
        columns = priorities.columns
        if priorities.explicit:
            candidates = rerank(target, candidates, priorities, stats)
    results = []
    chosen = spread_out(lat, lon, candidates, k, min_separation_mi)
    names = neighborhood_map(conn, [c.get("geohash") for c in chosen])
    for c in chosen:
        diffs = differences(target, c, columns)
        d = haversine_m(lat, lon, c["latitude"], c["longitude"])
        results.append(
            {
                "latitude": c["latitude"],
                "longitude": c["longitude"],
                "direction": compass(lat, lon, c["latitude"], c["longitude"]),
                "distance_label": format_distance(d),
                "similarity": similarity(c["dist"]),
                "composite_score": int(float(c["composite_score"]) + 0.5),
                "area_label": area_label(conn, c["latitude"], c["longitude"]),
                "neighborhood": names.get(c.get("geohash")),
                "differences": diffs,
                "summary": summary(diffs),
            }
        )
    return {
        "min_separation_mi": min_separation_mi,
        "results": results,
        "priorities": priorities.factors if priorities else [],
    }
