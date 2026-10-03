"""scoring/embeddings.py pure functions (no database)."""

import math

from scoring.embeddings import (
    EMBEDDING_COLUMNS,
    EMBEDDING_DIM,
    build_embeddings,
    column_stats,
    vector_literal,
    zscore,
)


def row(gid, **scores):
    base = {c: 50.0 for c in EMBEDDING_COLUMNS}
    base.update(scores)
    return {"geo_entity_id": gid, **base}


def test_dimension_count_and_order():
    assert EMBEDDING_DIM == 14
    assert len(set(EMBEDDING_COLUMNS)) == 14
    assert EMBEDDING_COLUMNS[0] == "grocery_score"
    assert EMBEDDING_COLUMNS[-1] == "trail_popularity_score"


def test_zscore_basic_and_guards():
    assert zscore(60.0, 50.0, 10.0) == 1.0
    assert zscore(60.0, 50.0, 0.0) == 0.0
    assert zscore(None, 50.0, 10.0) == 0.0


def test_column_stats_ignores_nulls():
    mean, std = column_stats([{"a": 10}, {"a": 30}, {"a": None}], "a")
    assert mean == 20.0 and math.isclose(std, 10.0)
    assert column_stats([{"a": None}], "a") == (0.0, 0.0)


def test_build_embeddings_zscores_in_column_order():
    rows = [row("a", grocery_score=40.0), row("b", grocery_score=60.0)]
    out = build_embeddings(rows)
    assert out["a"][0] == -1.0 and out["b"][0] == 1.0
    # constant columns have std 0 -> 0.0
    assert out["a"][1:] == [0.0] * 13
    assert all(len(v) == 14 for v in out.values())


def test_null_imputed_with_zero():
    rows = [
        row("a", school_score=None),
        row("b", school_score=20.0),
        row("c", school_score=80.0),
    ]
    out = build_embeddings(rows)
    idx = EMBEDDING_COLUMNS.index("school_score")
    assert out["a"][idx] == 0.0
    assert out["b"][idx] < 0 < out["c"][idx]


def test_vector_literal():
    assert vector_literal([0.0, -1.5, 2.0]) == "[0.000000,-1.500000,2.000000]"
    assert vector_literal([]) == "[]"
