"""Wave 1/2 additions: migration 0011, score file, sources, feedback, similar
neighbours, similar_cells, brand patterns (fakes, no database)."""

import gzip
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import feedback, main, scorefile, similar, sources
from api.factors import FACTOR_COLUMNS
from common.places import brand_like_patterns
from scoring import embeddings

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


def test_fetch_neighbours_uses_precomputed_when_spread_ok(monkeypatch):
    pre = [{"latitude": 40.7 + i * 0.05, "longitude": -74.0, "dist": 0.1 * i} for i in range(1, 6)]
    monkeypatch.setattr(similar, "fetch_precomputed", lambda c, g, v: pre)
    conn = Conn(lambda sql: [])
    got = similar.fetch_neighbours(conn, "g", "v", "nyc", 20, spread=(40.7, -74.0, 3, 1.0))
    assert got == pre and not conn.sql  # no HNSW query


def test_fetch_neighbours_falls_back_to_hnsw(monkeypatch):
    monkeypatch.setattr(similar, "fetch_precomputed", lambda c, g, v: [])
    conn = Conn(lambda sql: [{"v": "off"}] if "current_setting" in sql else [])
    similar.fetch_neighbours(conn, "g", "v", "nyc", 100, spread=(40.7, -74.0, 3, 1.0))
    assert any("set_config('hnsw.ef_search'" in s for s in conn.sql)
    assert any("hnsw.iterative_scan', 'relaxed_order'" in s for s in conn.sql)
    last = conn.params[-1]
    assert last["pool"] == 300 and last["limit"] == 100
    assert "order by embedding <->" in similar.NEIGHBOURS_SQL and "limit %(pool)s" in similar.NEIGHBOURS_SQL


def test_precomputed_too_close_falls_back(monkeypatch):
    close = [{"latitude": 40.7, "longitude": -74.0 + i * 1e-4, "dist": 0.1} for i in range(1, 6)]
    monkeypatch.setattr(similar, "fetch_precomputed", lambda c, g, v: close)
    conn = Conn(lambda sql: [])
    similar.fetch_neighbours(conn, "g", "v", "nyc", 20, spread=(40.7, -74.0, 3, 1.0))
    assert conn.sql  # HNSW query ran


# --- similar_cells -----------------------------------------------------------


def test_top_neighbours_exact():
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(1)
    vecs = rng.normal(size=(60, 14)).tolist()
    ids = [f"c{i}" for i in range(60)]
    got = embeddings.top_neighbours(ids, vecs, k=5)
    x = np.array(vecs)
    for i in (0, 17, 59):
        d = np.linalg.norm(x - x[i], axis=1)
        d[i] = np.inf
        want = [f"c{j}" for j in np.argsort(d)[:5]]
        assert [n for n, _ in got[ids[i]]] == want
        assert got[ids[i]][0][1] == pytest.approx(float(np.sort(d)[0]), abs=1e-4)
        assert ids[i] not in [n for n, _ in got[ids[i]]]
    assert embeddings.top_neighbours(["a"], [[0.0] * 14]) == {"a": []}


def test_write_similar_cells_skips_missing_table():
    conn = Conn(lambda sql: [{"t": None}])
    assert embeddings.write_similar_cells(conn, "v", {"a": [("b", 1.0)]}) == 0


# --- brand search ------------------------------------------------------------


def test_brand_patterns_cover_possessives():
    pats = brand_like_patterns("trader joes")
    assert "%trader joes%" in pats and "%trader joe%s%" in pats
    assert brand_like_patterns("starbucks")[0] == "%starbucks%"
    assert brand_like_patterns("100%_")[0] == "%100\\%\\_%"
