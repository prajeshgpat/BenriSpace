"""Wave 1/2 additions: migration 0011, score file, sources, feedback, similar
neighbours, brand patterns (fakes, no database)."""

import gzip
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import feedback, main, scorefile, similar, sources
from api.factors import FACTOR_COLUMNS
from api.metro_stats import ColumnStats
from common.places import brand_like_patterns

ROOT = Path(__file__).resolve().parent.parent / "contracts"
STAMP = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


class Cur:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        self.conn.params.append(params)
        self.rows = self.conn.respond(sql)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class Conn:
    def __init__(self, respond):
        self.respond, self.sql, self.params = respond, [], []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return Cur(self)

    def commit(self):
        pass

    def rollback(self):
        pass


# --- migration ---------------------------------------------------------------


def test_migration_0011_is_additive_idempotent_and_mirrored():
    migration = (ROOT / "migrations" / "0011_perf.sql").read_text()
    
    code = "\n".join(l for l in migration.splitlines() if not l.lstrip().startswith("--"))
    statements = [s.strip() for s in code.split(";") if s.strip()]
    assert len(statements) == 7
    schema = (ROOT / "schema.sql").read_text()
    for stmt in statements:
        assert stmt.startswith(("create index if not exists", "create extension if not exists",
                                "create table if not exists"))  # fmt: skip
        assert " ".join(stmt.split()) in " ".join(schema.split())
        assert not any(w in stmt.lower() for w in ("drop ", "alter ", "truncate"))


# --- score file --------------------------------------------------------------


def decode(blob: bytes) -> dict:
    (hlen,) = struct.unpack_from("<I", blob, 0)
    header = json.loads(blob[4 : 4 + hlen])
    n, w = header["count"], header["geohashLength"]
    p = 4 + hlen
    hashes = [blob[p + i * w : p + (i + 1) * w].decode("ascii") for i in range(n)]
    p += n * w
    f = len(header["factors"])
    cells = {}
    for i, h in enumerate(hashes):
        row = blob[p + i * f : p + (i + 1) * f]
        cells[h] = [None if b == 255 else b for b in row]
    assert len(blob) == p + n * f
    return {"header": header, "cells": cells}


def score_rows():
    cols = list(FACTOR_COLUMNS.values())
    return [
        {"geohash": "dr5rux", **{c: 49.5 for c in cols}},
        {"geohash": "dr5ruq", **{c: None for c in cols}, cols[0]: 100, cols[1]: 0.2},
    ]


def test_scorefile_roundtrip():
    out = decode(scorefile.encode(score_rows(), "v2-handtuned", STAMP))
    assert out["header"]["factors"] == list(FACTOR_COLUMNS)
    assert out["header"]["count"] == 2 and out["header"]["version"] == "v2-handtuned"
    assert list(out["cells"]) == ["dr5ruq", "dr5rux"]  # sorted
    assert out["cells"]["dr5rux"] == [50] * 13  # half up
    assert out["cells"]["dr5ruq"] == [100, 0] + [None] * 11


def test_map_scores_endpoint_headers_etag_gzip_and_304(monkeypatch):
    scorefile._cache.clear()

    def respond(sql):
        if "from score_files" in sql:
            return []  # nothing persisted yet: build from the scores table
        return [{"stamp": STAMP}] if "max(computed_at)" in sql else score_rows()

    conn = Conn(respond)
    monkeypatch.setattr(main, "get_connection", lambda: conn)
    client = TestClient(main.app)
    r = client.get("/v1/map/scores", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["cache-control"] == "public, max-age=86400"
    etag = r.headers["etag"]
    assert etag.startswith('"') and str(int(STAMP.timestamp())) in etag
    assert decode(r.content)["header"]["count"] == 2
    queries = sum("from scores s join" in s for s in conn.sql)
    r2 = client.get("/v1/map/scores", headers={"Accept-Encoding": "identity"})
    assert r2.content == r.content
    assert sum("from scores s join" in s for s in conn.sql) == queries  # cached by ETag
    assert client.get("/v1/map/scores", headers={"If-None-Match": etag}).status_code == 304
    assert client.get("/v1/map/scores?version=nope").status_code == 404
    raw = scorefile._cache[etag]
    assert gzip.decompress(raw.gzipped) == raw.body


def test_scorefile_uses_the_persisted_row_when_the_etag_matches():
    scorefile._cache.clear()
    built = scorefile.build_fresh(Conn(lambda sql: score_rows()), "v2.1-handtuned", STAMP)
    stored = {"body_gz": built.gzipped}

    def respond(sql):
        if "from score_files" in sql:
            return [stored]
        if "max(computed_at)" in sql:
            return [{"stamp": STAMP}]
        raise AssertionError("scores must not be scanned when the file is stored")

    conn = Conn(respond)
    got = scorefile.build(conn, "v2.1-handtuned")
    assert got.etag == built.etag and got.body == built.body and got.gzipped == built.gzipped
    assert conn.params[-1] == ("v2.1-handtuned", built.etag)
    scorefile._cache.clear()


def test_scorefile_survives_a_missing_table(monkeypatch):
    import psycopg

    scorefile._cache.clear()

    class Boom(Conn):
        rolled = 0

        def cursor(self):
            outer = self

            class C(Cur):
                def execute(self, sql, params=None):
                    if "from score_files" in sql:
                        raise psycopg.errors.UndefinedTable("score_files")
                    super().execute(sql, params)

            return C(outer)

        def rollback(self):
            self.rolled += 1

    conn = Boom(lambda sql: [{"stamp": STAMP}] if "max(computed_at)" in sql else score_rows())
    got = scorefile.build(conn, "v2.1-handtuned")
    assert got is not None and conn.rolled == 1 and got.etag.startswith('"v2.1-handtuned-')
    scorefile._cache.clear()


def test_scorefile_store_upserts_the_gzipped_file():
    class Store(Conn):
        commits = 0

        def commit(self):
            self.commits += 1

    conn = Store(lambda sql: [{"stamp": STAMP}] if "max(computed_at)" in sql else score_rows())
    size = scorefile.store(conn, "v2.1-handtuned")
    insert = next(
        p for s, p in zip(conn.sql, conn.params, strict=True) if "insert into score_files" in s
    )
    assert insert[0] == "v2.1-handtuned" and insert[1].startswith('"v2.1-handtuned-')
    assert decode(gzip.decompress(insert[2]))["header"]["count"] == 2
    assert size == len(insert[2]) and conn.commits == 1
    assert scorefile.store(Store(lambda sql: [{"stamp": None}]), "x") == 0


# --- sources -----------------------------------------------------------------


def test_sources_registry_and_freshness(monkeypatch):
    runs = [
        {"source": "osm_poi", "finished_at": STAMP, "rows_affected": 10},
        {"source": "gtfs_mta", "finished_at": STAMP, "rows_affected": 5},
        {"source": "gtfs_lirr", "finished_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
         "rows_affected": 7},
    ]  # fmt: skip
    monkeypatch.setattr(main, "get_connection", lambda: Conn(lambda sql: runs))
    body = TestClient(main.app).get("/v1/sources").json()
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["osm_poi"]["rowsAffected"] == 10 and by_id["osm_poi"]["license"].startswith("ODbL")
    assert by_id["gtfs"]["rowsAffected"] == 12 and by_id["gtfs"]["lastUpdated"].startswith("2026-10-04")
    assert by_id["schools"]["lastUpdated"] is None
    assert all(s["name"] and s["feeds"] and s["url"] for s in body["sources"])
    assert len(sources.SOURCES) == len({s.id for s in sources.SOURCES})


# --- feedback ----------------------------------------------------------------


def post(client, **body):
    return client.post("/v1/feedback", json=body, headers={"X-Forwarded-For": "9.9.9.9"})


def test_feedback_stores_and_limits(monkeypatch):
    state = {"n": 0}

    def respond(sql):
        return [{"n": state["n"]}] if sql.lstrip().startswith("select") else []

    conn = Conn(respond)
    monkeypatch.setattr(feedback, "get_connection", lambda: conn)
    client = TestClient(main.app)
    r = post(client, kind="summary", target="dr5rux", rating=1, message="  nice ")
    assert r.status_code == 204 and r.content == b""
    insert = next(p for s, p in zip(conn.sql, conn.params) if s.startswith("insert into feedback"))
    assert insert[:4] == ("summary", "dr5rux", 1, "nice") and "9.9.9.9" not in insert[4]
    state["n"] = feedback.DAILY_LIMIT
    assert post(client, kind="chat").status_code == 429
    assert post(client, kind="bogus").status_code in (400, 422)
    assert post(client, kind="place", message="x" * 1001).status_code in (400, 422)


def test_feedback_tolerates_missing_table(monkeypatch):
    def boom():
        raise RuntimeError("relation feedback does not exist")

    monkeypatch.setattr(feedback, "get_connection", boom)
    assert post(TestClient(main.app), kind="place", message="closed").status_code == 204


# --- similar -----------------------------------------------------------------


def test_neighbours_sql_scans_one_metro_with_inlined_z_scores():
    stats = {c: ColumnStats(50.0, 10.0, tuple(range(101))) for c in similar.FACTOR_SCORE_COLUMNS}
    sql = similar.build_neighbours_sql(stats)
    assert "embedding" not in sql and "hnsw" not in sql.lower()
    assert "ge.metro_area = %(metro)s" in sql and "s.geo_entity_id <> %(id)s" in sql
    assert "order by dist" in sql and "limit %(limit)s" in sql
    assert sql.count("power(") == 13
    # v2 rows read Shopping / Recreation through their legacy columns
    assert "coalesce(s.shopping_score, s.premium_retail_score)" in sql
    assert "coalesce(t.recreation_score, t.trail_popularity_score)" in sql
    assert "(s.transit_score - 50.000000) / 10.000000" in sql


def test_neighbours_sql_skips_flat_columns_and_survives_missing_stats():
    stats = {c: ColumnStats(50.0, 10.0, tuple(range(101))) for c in similar.FACTOR_SCORE_COLUMNS}
    stats["bar_score"] = ColumnStats(50.0, 0.0, tuple(range(101)))
    assert similar.build_neighbours_sql(stats).count("power(") == 12
    assert similar.build_neighbours_sql(None).count("power(") == 13  # fallback spread


def test_fetch_neighbours_binds_the_request_and_loads_stats(monkeypatch):
    stats = {c: ColumnStats(50.0, 10.0, tuple(range(101))) for c in similar.FACTOR_SCORE_COLUMNS}
    seen = {}
    monkeypatch.setattr(similar, "get_stats", lambda c, v, m: seen.update(v=v, m=m) or stats)
    rows = [{"geohash": "dr5ru9", "dist": 0.5}]
    conn = Conn(lambda sql: rows)
    assert similar.fetch_neighbours(conn, "g1", "v2.1-handtuned", "nyc", 40) == rows
    assert seen == {"v": "v2.1-handtuned", "m": "nyc"}
    assert conn.params[-1] == {"id": "g1", "v": "v2.1-handtuned", "metro": "nyc", "limit": 40}


def test_similarity_dimensions_match_the_factor_columns():
    from scoring.similarity import SIMILARITY_COLUMNS, SIMILARITY_DIM, column_stats, zscore

    assert SIMILARITY_COLUMNS == tuple(FACTOR_COLUMNS.values()) and SIMILARITY_DIM == 13
    assert zscore(60.0, 50.0, 10.0) == 1.0
    assert zscore(60.0, 50.0, 0.0) == 0.0 and zscore(None, 50.0, 10.0) == 0.0
    mean, std = column_stats([{"a": 10}, {"a": 30}, {"a": None}], "a")
    assert mean == 20.0 and std == pytest.approx(10.0)
    assert column_stats([{"a": None}], "a") == (0.0, 0.0)


# --- brand search ------------------------------------------------------------


def test_brand_patterns_cover_possessives():
    pats = brand_like_patterns("trader joes")
    assert "%trader joes%" in pats and "%trader joe%s%" in pats
    assert brand_like_patterns("starbucks")[0] == "%starbucks%"
    assert brand_like_patterns("100%_")[0] == "%100\\%\\_%"
