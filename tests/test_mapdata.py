"""GET /v1/map/cells and /v1/map/top: parsing, SQL construction and result
shaping. No database: the composite SQL expression is executed against an
in-memory SQLite table (see test_generated_sql_expression_equals_compute_composite)."""

import math
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
from api.main import app
from api.mapdata import (
    FACTOR_ALIASES,
    FACTOR_COLUMNS,
    InvalidMapRequest,
    ScoreSpec,
    build_cells_response,
    build_top_response,
    canonical_factor,
    composite_from_row,
    parse_bbox,
    parse_factors,
    parse_score_spec,
    parse_weights,
    select_separated,
)
from common.db import (
    build_composite_sql,
    build_map_cells_sql,
    build_map_top_sql,
)
from scoring.engine import (
    CATEGORY_SPECS_V2_1,
    LEGACY_FALLBACK_COLUMNS,
    V2_1_WEIGHTS,
    compute_composite,
)

client = TestClient(app)

ALL = list(FACTOR_COLUMNS)


# --- single source of truth ------------------------------------------------------


def test_every_scored_category_is_exposed_as_a_factor():
    assert set(FACTOR_COLUMNS.values()) == {spec.score_column for spec in CATEGORY_SPECS_V2_1}
    assert len(FACTOR_COLUMNS) == len(CATEGORY_SPECS_V2_1) == 13


def test_factor_keys_are_the_camelcase_of_the_column_names_and_match_the_contract():
    for key, column in FACTOR_COLUMNS.items():
        if key == "traffic":  # Traffic is stored in road_score
            assert column == "road_score"
            continue
        parts = column.removesuffix("_score").split("_")
        assert key == parts[0] + "".join(p.title() for p in parts[1:])
    assert ALL == [
        "grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience", "transit",
        "school", "traffic", "emergencyCorridor", "airport", "recreation",
    ]  # fmt: skip


def test_every_factor_has_a_default_weight():
    assert set(FACTOR_COLUMNS.values()) <= set(V2_1_WEIGHTS)


# --- parsing ---------------------------------------------------------------------


def test_bbox_parses_min_lon_min_lat_max_lon_max_lat():
    assert parse_bbox("-74.05, 40.68,-73.85,40.82") == (-74.05, 40.68, -73.85, 40.82)


@pytest.mark.parametrize(
    "raw",
    ["", "1,2,3", "1,2,3,4,5", "a,b,c,d", "-73,41,-74,40", "-74,41,-73,41", "-74,40,-73,40",
     "-74,40,-73,95", "-181,40,-73,41", "nan,40,-73,41", "inf,40,-73,41", "1_0,40,-73,41", "-74,,-73,41"],
)  # fmt: skip
def test_bad_bbox_is_rejected(raw):
    with pytest.raises(InvalidMapRequest):
        parse_bbox(raw)


def test_factors_default_to_all_and_come_back_in_contract_order_without_duplicates():
    assert parse_factors(None) == ALL
    assert parse_factors("transit, grocery,transit") == ["grocery", "transit"]


@pytest.mark.parametrize(
    "raw", ["", ",", "grocery,", "grocery,,gym", "nope", "grocery_score", "Grocery"]
)
def test_bad_factors_are_rejected(raw):
    with pytest.raises(InvalidMapRequest):
        parse_factors(raw)


def test_weights_default_to_engine_defaults_and_overrides_apply():
    factors = ["cafe", "transit"]
    assert parse_weights(None, factors) == {"cafe": 8.0, "transit": 14.0}
    assert parse_weights("transit:2,cafe:0.5", factors) == {"cafe": 0.5, "transit": 2.0}
    assert parse_weights("transit:1e1", factors)["transit"] == 10.0


def test_weight_overrides_for_factors_not_included_are_ignored():
    assert parse_weights("gym:9", ["cafe"]) == {"cafe": 8.0}


@pytest.mark.parametrize(
    "raw",
    ["transit", "transit:", ":2", "transit:abc", "transit:0", "transit:-1", "transit:nan",
     "transit:inf", "transit:1e999", "transit:2000000", "bogus:1", "transit:1,transit:2",
     "transit:1;drop table scores", "transit:1,", ""],
)  # fmt: skip
def test_bad_weights_are_rejected(raw):
    with pytest.raises(InvalidMapRequest):
        parse_weights(raw, ["transit", "cafe"])


def test_unknown_factor_in_weights_is_rejected_even_when_not_included():
    with pytest.raises(InvalidMapRequest):
        parse_weights("bogus:1", ["cafe"])


# --- composite semantics ---------------------------------------------------------


ROWS = [
    {c: 80.0 for c in FACTOR_COLUMNS.values()},
    {**{c: None for c in FACTOR_COLUMNS.values()}, "transit_score": 90.0, "cafe_score": 30.0},
    {**{c: None for c in FACTOR_COLUMNS.values()}, "grocery_score": 0.0, "gym_score": 100.0},
    {**{c: 55.5 for c in FACTOR_COLUMNS.values()}, "school_score": None, "road_score": None},
    {c: None for c in FACTOR_COLUMNS.values()},
]
SPECS = [
    parse_score_spec(None, None),
    parse_score_spec("transit,cafe", "transit:2,cafe:0.5"),
    parse_score_spec("grocery,gym,airport", "airport:7"),
    parse_score_spec("school", None),
]


def engine_composite(row: dict, spec: ScoreSpec) -> float | None:
    sub = {c: row[c] for c, _ in spec.columns_weights if row.get(c) is not None}
    if not sub:
        return None
    return compute_composite(sub, dict(spec.columns_weights))


@pytest.mark.parametrize("spec", SPECS)
@pytest.mark.parametrize("row", ROWS)
def test_reference_composite_equals_engine_compute_composite(row, spec):
    expected = engine_composite(row, spec)
    got = composite_from_row(row, spec)
    assert (got is None) == (expected is None)
    if got is not None:
        assert got == pytest.approx(expected)


@pytest.mark.parametrize("spec", SPECS)
def test_generated_sql_expression_equals_compute_composite(spec):
    """Executes the exact expression text build_composite_sql emits (placeholders
    rewritten to SQLite's `?`, `::float8` casts dropped) over the hand-built rows.

    Proves the expression's null handling and weight arithmetic match
    compute_composite. It does not prove Postgres's planner/types, the joins, or
    the row filters; those were checked by running the endpoints against the live
    database. SQLite and Postgres agree on coalesce/case/nullif semantics."""
    expr, params = build_composite_sql(spec.columns_weights)
    sqlite_expr = expr.replace("%s::float8", "?")
    assert "%s" not in sqlite_expr

    db = sqlite3.connect(":memory:")
    columns = list(FACTOR_COLUMNS.values())
    stored = [*columns, *LEGACY_FALLBACK_COLUMNS.values()]  # legacy columns exist, null here
    db.execute(f"create table s (id integer, {', '.join(c + ' real' for c in stored)})")
    for i, row in enumerate(ROWS):
        db.execute(
            f"insert into s values ({', '.join('?' * (len(stored) + 1))})",
            [i, *(row.get(c) for c in stored)],
        )
    results = [v for (v,) in db.execute(f"select {sqlite_expr} from s order by id", params)]

    for row, got in zip(ROWS, results):
        expected = engine_composite(row, spec)
        if expected is None:
            assert got is None
        else:
            assert got == pytest.approx(expected)


def test_composite_expression_has_one_numerator_and_one_denominator_term_per_factor():
    cw = [("transit_score", 2.0), ("cafe_score", 0.5)]
    expr, params = build_composite_sql(cw)
    assert params == [2.0, 0.5, 2.0, 0.5]
    assert expr.count("%s") == 4
    assert "nullif" in expr


def test_composite_sql_rejects_non_whitelisted_columns_and_empty_factor_sets():
    with pytest.raises(ValueError):
        build_composite_sql([("composite_score; drop table scores", 1.0)])
    with pytest.raises(ValueError):
        build_composite_sql([("id", 1.0)])
    with pytest.raises(ValueError):
        build_composite_sql([])


# --- SQL safety ------------------------------------------------------------------


def test_generated_sql_contains_only_whitelisted_identifiers_and_no_user_values():
    spec = parse_score_spec("transit,cafe", "transit:7.123456,cafe:0.333")
    version = "v-evil'; drop table scores;--"
    bbox = (-74.05123, 40.68123, -73.85456, 40.82456)
    queries = [
        build_map_cells_sql(spec.columns_weights, version, bbox, 6, 4242),
        build_map_cells_sql(spec.columns_weights, version, bbox, 5, 4242),
        build_map_top_sql(spec.columns_weights, version, bbox, 4242),
        build_map_top_sql(spec.columns_weights, version, None, 4242),
    ]
    for sql, params in queries:
        for needle in (
            "7.123456",
            "0.333",
            "evil",
            "drop",
            "74.05123",
            "40.68123",
            "73.85456",
            "40.82456",
            "4242",
        ):
            assert needle not in sql
        assert version in params
        assert 7.123456 in params and 0.333 in params
        assert sql.count("%s") == len(params)
        columns = set(re.findall(r"\bs\.(\w+)", sql))
        allowed = set(FACTOR_COLUMNS.values()) | set(LEGACY_FALLBACK_COLUMNS.values())
        assert columns <= allowed | {"geo_entity_id", "weights_version"}
        assert 4242 in params


def test_top_query_selects_every_sub_score_column_for_the_response():
    sql, _ = build_map_top_sql([("transit_score", 1.5)], "v1", None, 10)
    for column in FACTOR_COLUMNS.values():
        assert f"s.{column}" in sql


# --- response shaping ------------------------------------------------------------


def test_cells_response_rounds_scores_and_flags_truncation():
    spec = parse_score_spec("transit", None)
    rows = [{"geohash": f"dr5r{c}", "score": s} for c, s in zip("abc", (80.04, 79.96, 50.0))]
    resp = build_cells_response(rows, spec, 6, limit=2)  # fetched limit + 1
    body = resp.model_dump(by_alias=True)
    assert body["truncated"] is True
    assert body["count"] == 2
    assert body["geohashes"] == ["dr5ra", "dr5rb"]
    assert body["scores"] == [80.0, 80.0]
    assert (
        body["weightsVersion"]
        and body["factors"] == ["transit"]
        and body["weights"] == {"transit": 14.0}
    )

    not_truncated = build_cells_response(rows[:2], spec, 6, limit=2)
    assert not_truncated.truncated is False


def grid_candidates(n: int, step_km: float = 1.0) -> list[dict]:
    """n cells in a line, `step_km` apart, best first."""
    deg = step_km / 111.0
    return [
        {
            "geohash": f"g{i:05d}", "latitude": 40.7 + i * deg, "longitude": -74.0,
            "metro_area": "nyc", "score": 90.0 - i * 0.01,
            **{c: 50.0 for c in FACTOR_COLUMNS.values()},
        }
        for i in range(n)
    ]  # fmt: skip


def test_greedy_separation_keeps_best_first_and_enforces_min_distance():
    cands = grid_candidates(30, step_km=1.0)
    picked = select_separated(cands, limit=5, min_separation_km=3)
    assert [c["geohash"] for c in picked] == ["g00000", "g00003", "g00006", "g00009", "g00012"]


def test_small_separation_still_fills_the_limit_and_a_small_area_returns_fewer():
    cands = grid_candidates(30)
    assert len(select_separated(cands, limit=10, min_separation_km=0)) == 10
    assert len(select_separated(cands[:4], limit=10, min_separation_km=0)) == 4
    assert len(select_separated(cands, limit=10, min_separation_km=1000)) == 1


def test_top_response_shape_rounds_and_includes_all_sub_scores():
    spec = parse_score_spec("transit", None)
    cand = grid_candidates(1)[0] | {"latitude": 40.7816000000001, "score": 99.96}
    body = build_top_response([cand], spec, 10, 3).model_dump(by_alias=True)
    r = body["results"][0]
    assert r["latitude"] == 40.7816 and r["score"] == 100.0 and r["metroArea"] == "nyc"
    assert set(r["subScores"]) == {
        "grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience", "transit",
        "school", "traffic", "emergencyCorridor", "airport", "recreation",
    }  # fmt: skip


# --- routes (DB stubbed) ---------------------------------------------------------


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def stub_db(monkeypatch):
    calls = {}
    monkeypatch.setattr(main_mod, "get_connection", lambda: FakeConn())

    def fake_cells(conn, cw, version, bbox, precision, limit):
        calls["cells"] = (cw, version, bbox, precision, limit)
        return [{"geohash": "dr5ru0", "score": 71.26}, {"geohash": "dr5ru1", "score": 12.0}][:limit]

    monkeypatch.setattr(main_mod, "get_map_cells", fake_cells)

    from api import mapdata

    monkeypatch.setattr(
        mapdata,
        "get_map_top_candidates",
        lambda conn, cw, v, bbox, pool: calls.setdefault("top", grid_candidates(40)),
    )
    return calls


def test_cells_route_happy_path(stub_db):
    resp = client.get(
        "/v1/map/cells",
        params={
            "bbox": "-74.05,40.68,-73.85,40.82",
            "factors": "transit,cafe",
            "weights": "transit:2",
            "limit": 5,
        },
    )
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=300"
    body = resp.json()
    assert body["geohashes"] == ["dr5ru0", "dr5ru1"] and body["scores"] == [71.3, 12.0]
    assert body["factors"] == ["cafe", "transit"] and body["weights"] == {
        "cafe": 8.0,
        "transit": 2.0,
    }
    assert body["precision"] == 6 and body["truncated"] is False and body["count"] == 2
    cw, _, bbox, precision, fetch_limit = stub_db["cells"]
    assert cw == [("cafe_score", 8.0), ("transit_score", 2.0)]
    assert bbox == (-74.05, 40.68, -73.85, 40.82) and precision == 6 and fetch_limit == 6


def test_cells_route_truncation_uses_limit_plus_one(stub_db):
    resp = client.get(
        "/v1/map/cells", params={"bbox": "-74.05,40.68,-73.85,40.82", "limit": 1, "precision": 5}
    )
    body = resp.json()
    assert body["truncated"] is True and body["count"] == 1 and body["precision"] == 5
    assert stub_db["cells"][4] == 2


@pytest.mark.parametrize(
    "path,params",
    [
        ("/v1/map/cells", {}),
        ("/v1/map/cells", {"bbox": "-73,41,-74,40"}),
        ("/v1/map/cells", {"bbox": "-74,40,-73,41", "factors": "nope"}),
        ("/v1/map/cells", {"bbox": "-74,40,-73,41", "factors": ""}),
        ("/v1/map/cells", {"bbox": "-74,40,-73,41", "weights": "transit:0"}),
        ("/v1/map/cells", {"bbox": "-74,40,-73,41", "precision": 7}),
        ("/v1/map/cells", {"bbox": "-74,40,-73,41", "precision": "x"}),
        ("/v1/map/cells", {"bbox": "-74,40,-73,41", "limit": 20001}),
        ("/v1/map/top", {"bbox": "x"}),
        ("/v1/map/top", {"weights": "transit:-2"}),
        ("/v1/map/top", {"limit": 51}),
        ("/v1/map/top", {"minSeparationKm": 51}),
        ("/v1/map/top", {"minSeparationKm": -1}),
        ("/v1/map/top", {"minSeparationMi": 32}),
        ("/v1/map/top", {"minSeparationMi": -1}),
        ("/v1/map/top", {"minSeparationMi": 2, "minSeparationKm": 3}),
    ],
)
def test_map_routes_reject_bad_input_with_invalid_request(stub_db, path, params):
    resp = client.get(path, params=params)
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "invalid_request" and body["message"]
    assert "cache-control" not in resp.headers
    assert not stub_db  # never reached the database


def test_top_route_applies_separation_and_limit(stub_db):
    resp = client.get("/v1/map/top", params={"limit": 3, "minSeparationKm": 5})
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=300"
    results = resp.json()["results"]
    assert [r["geohash"] for r in results] == ["g00000", "g00005", "g00010"]
    assert math.isclose(results[0]["score"], 90.0)
    assert resp.json()["factors"] == ALL


def test_top_route_accepts_miles_and_matches_the_km_equivalent(stub_db):
    mi = client.get("/v1/map/top", params={"limit": 3, "minSeparationMi": 5 / 1.609344})
    km = client.get("/v1/map/top", params={"limit": 3, "minSeparationKm": 5})
    assert mi.status_code == 200
    assert mi.json() == km.json()


def test_openapi_document_lists_the_new_paths():
    schema = app.openapi()
    for path in ("/v1/suggest", "/v1/map/cells", "/v1/map/top"):
        assert path in schema["paths"]


def test_no_hidden_factors_omitted_list_is_all_thirteen_and_explicit_list_is_exact():
    assert len(parse_factors(None)) == 13
    assert parse_factors("grocery,shopping") == ["grocery", "shopping"]
    assert parse_factors("grocery") == ["grocery"]


def test_legacy_factor_keys_are_aliases_and_dedupe():
    assert FACTOR_ALIASES == {
        "premiumRetail": "shopping", "trailPopularity": "recreation", "road": "traffic",
        "gasStation": "gasConvenience", "convenienceStore": "gasConvenience",
    }  # fmt: skip
    assert canonical_factor("road") == "traffic" and canonical_factor("grocery") == "grocery"
    assert canonical_factor("nope") is None
    assert parse_factors("gasStation,convenienceStore,gasConvenience") == ["gasConvenience"]
    assert parse_factors("road,premiumRetail,trailPopularity,grocery") == [
        "grocery", "shopping", "traffic", "recreation",
    ]  # fmt: skip


def test_legacy_keys_work_in_weights_too():
    weights = parse_weights("premiumRetail:7,road:2", ["shopping", "traffic", "cafe"])
    assert weights == {"shopping": 7.0, "traffic": 2.0, "cafe": 8.0}
    with pytest.raises(InvalidMapRequest):  # two aliases of one factor
        parse_weights("gasStation:1,convenienceStore:2", ["gasConvenience"])


def test_default_weights_are_the_agreed_relative_weights():
    assert parse_weights(None, ALL) == {
        "grocery": 14, "gym": 9, "cafe": 8, "restaurant": 10, "bar": 5, "shopping": 4,
        "gasConvenience": 6, "transit": 14, "school": 10, "traffic": 4,
        "emergencyCorridor": 12, "airport": 5, "recreation": 5,
    }  # fmt: skip


def test_composite_sql_reads_legacy_columns_for_v2_rows():
    expr, _ = build_composite_sql([("shopping_score", 4.0), ("recreation_score", 5.0)])
    assert "coalesce(s.shopping_score, s.premium_retail_score)" in expr
    assert "coalesce(s.recreation_score, s.trail_popularity_score)" in expr
    plain, _ = build_composite_sql([("transit_score", 1.0)])
    assert "premium_retail" not in plain
    db = sqlite3.connect(":memory:")
    db.execute(
        "create table s (shopping_score real, premium_retail_score real, recreation_score real, trail_popularity_score real)"
    )
    db.execute("insert into s values (null, 80, 50, 10)")  # v2 shopping, v2.1 recreation
    sql = expr.replace("%s::float8", "?")
    (value,) = db.execute(f"select {sql} from s", [4.0, 5.0, 4.0, 5.0]).fetchone()
    assert value == pytest.approx((80 * 4 + 50 * 5) / 9)
