"""scoring/run.py write_scales, migration 0013 shape and scripts/delete_scores.py."""

import importlib.util
from pathlib import Path

import psycopg
import pytest

from scoring import run
from scoring.engine import WEIGHTS_VERSION_V2_1
from scoring.scales import compute_scales
from tests.test_scales import make_rows

ROOT = Path(__file__).resolve().parent.parent


class Cur:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def executemany(self, sql, rows):
        if self.conn.missing:
            raise psycopg.errors.UndefinedTable("score_scales")
        self.conn.sql, self.conn.rows = sql, list(rows)


class Conn:
    def __init__(self, missing=False):
        self.missing, self.rolled, self.committed = missing, 0, 0

    def cursor(self):
        return Cur(self)

    def rollback(self):
        self.rolled += 1

    def commit(self):
        self.committed += 1


def test_write_scales_upserts_one_row_per_component():
    scales = compute_scales(make_rows(40), WEIGHTS_VERSION_V2_1)
    conn = Conn()
    n = run.write_scales(conn, WEIGHTS_VERSION_V2_1, "nyc", scales)
    assert n == len(conn.rows) == 15  # 13 factors + school rating + recreation's trail half
    assert "insert into score_scales" in conn.sql and "on conflict" in conn.sql
    assert conn.rows[0][:2] == (WEIGHTS_VERSION_V2_1, "nyc") and conn.committed == 1


def test_write_scales_skips_quietly_before_the_migration():
    conn = Conn(missing=True)
    scales = compute_scales(make_rows(10), WEIGHTS_VERSION_V2_1)
    assert run.write_scales(conn, WEIGHTS_VERSION_V2_1, "nyc", scales) == 0
    assert conn.rolled >= 1


def test_migration_0013_is_additive_idempotent_and_mirrored():
    sql = (ROOT / "contracts/migrations/0013_score_scales.sql").read_text()
    schema = (ROOT / "contracts/schema.sql").read_text()
    body = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    assert "create table if not exists score_scales" in body
    for forbidden in ("drop ", "delete ", "truncate", "alter table scores"):
        assert forbidden not in body.lower()
    assert "primary key (weights_version, metro_area, factor, component)" in body
    assert "create table if not exists score_scales" in schema
    for col in ("weights_version", "metro_area", "factor", "component", "lo", "hi", "n"):
        assert f"    {col} " in body


# --- scripts/delete_scores.py -------------------------------------------------------


def load_script():
    spec = importlib.util.spec_from_file_location(
        "delete_scores", ROOT / "scripts" / "delete_scores.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DelCur:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = -1
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))
        low = sql.lower()
        if low.startswith("select count"):
            self.row = {"n": self.conn.remaining}
        elif "pg_database_size" in low:
            self.row = {"db": "445 MB", "scores": "171 MB"}
        elif low.startswith("select to_regclass"):
            self.row = {"t": params[0] if params[0] in self.conn.tables else None}
        elif low.startswith("delete from score_"):
            self.conn.side_deletes.append((sql, params))
        elif low.startswith("delete"):
            take = min(self.conn.remaining, params[1])
            self.conn.remaining -= take
            self.rowcount = take
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.row


class DelConn:
    def __init__(self, remaining):
        self.remaining, self.statements, self.commits = remaining, [], 0
        self.tables, self.side_deletes = {"score_scales"}, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return DelCur(self)

    def commit(self):
        self.commits += 1


@pytest.fixture
def script(monkeypatch):
    module = load_script()
    conns = []

    def connect(*a, **k):
        conns.append(DelConn(12_000))
        return conns[-1]

    monkeypatch.setattr(module.psycopg, "connect", connect)
    monkeypatch.setattr(module, "SCORING_WEIGHTS_VERSION", "v2.1-handtuned")
    module.conns = conns
    return module


def deletes(conn):
    return [
        s
        for s in conn.statements
        if s[0].lower().startswith("delete") and "from scores" in s[0].lower()
    ]


def test_default_is_a_dry_run(script, capsys):
    assert script.main(["--version", "v2-handtuned"]) == 0
    assert deletes(script.conns[0]) == []
    out = capsys.readouterr().out
    assert "12,000 v2-handtuned rows" in out and "445 MB" in out and "Dry run" in out


def test_yes_deletes_in_batches_and_reports(script, capsys):
    assert script.main(["--version", "v2-handtuned", "--yes", "--batch-size", "5000"]) == 0
    conn = script.conns[0]
    assert [p for _, p in deletes(conn)] == [("v2-handtuned", 5000)] * 4  # 5000, 5000, 2000, 0
    assert conn.remaining == 0 and conn.commits == 5  # 4 batches + score_scales
    out = capsys.readouterr().out
    assert "before" in out and "after" in out and "Deleted 12,000 rows" in out


def test_only_the_named_version_is_ever_targeted(script):
    script.main(["--version", "v2-handtuned", "--yes"])
    conn = script.conns[0]
    for sql, params in deletes(conn):
        assert params[0] == "v2-handtuned"
        assert "weights_version = %s" in sql
    # score_scales exists in the fake, score_files does not (migration not applied)
    assert [(s.split()[2], p) for s, p in conn.side_deletes] == [
        ("score_scales", ("v2-handtuned",))
    ]


def test_refuses_the_served_version(script):
    assert script.main(["--version", "v2.1-handtuned", "--yes"]) == 2
    assert script.conns == []


def test_requires_a_version(script):
    with pytest.raises(SystemExit):
        script.main(["--yes"])


def test_rejects_bad_batch_size(script):
    assert script.main(["--version", "v2-handtuned", "--yes", "--batch-size", "0"]) == 2
