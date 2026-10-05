"""common.db.ConnectionPool / api_connection: reuse, health checks, transactions."""

import psycopg
import pytest

from common import db


class FakeConn:
    def __init__(self):
        self.closed = False
        self.broken = False
        self.commits = 0
        self.rollbacks = 0
        self.fail_ping = False

    def execute(self, sql):
        if self.fail_ping:
            raise psycopg.OperationalError("gone")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.fixture
def pool(monkeypatch):
    made: list[FakeConn] = []

    def connect():
        c = FakeConn()
        made.append(c)
        return c

    now = [0.0]
    p = db.ConnectionPool(connect, size=2, clock=lambda: now[0])
    p.made, p.now = made, now
    monkeypatch.setattr(db, "_api_pools", {"x": p})
    monkeypatch.setattr(db, "DATABASE_URL", "x")
    return p


def test_reuses_one_connection_and_commits_each_request(pool):
    for _ in range(3):
        with db.api_connection() as conn:
            pass
    assert len(pool.made) == 1
    assert conn.commits == 3


def test_error_rolls_back_and_connection_is_kept(pool):
    with pytest.raises(ValueError), db.api_connection() as conn:
        raise ValueError("boom")
    assert conn.rollbacks == 1 and conn.commits == 0 and not conn.closed
    with db.api_connection() as again:
        pass
    assert again is conn


def test_operational_error_discards_connection(pool):
    with pytest.raises(psycopg.OperationalError), db.api_connection() as conn:
        raise psycopg.OperationalError("server closed the connection")
    assert conn.closed
    with db.api_connection() as fresh:
        pass
    assert fresh is not conn and len(pool.made) == 2


def test_closed_idle_connection_is_replaced(pool):
    with db.api_connection() as conn:
        pass
    conn.closed = True
    with db.api_connection() as fresh:
        pass
    assert fresh is not conn


def test_stale_idle_connection_is_pinged_and_replaced(pool):
    with db.api_connection() as conn:
        pass
    pool.now[0] += db.API_IDLE_PING_S + 1
    conn.fail_ping = True
    with db.api_connection() as fresh:
        pass
    assert fresh is not conn and conn.closed


def test_recent_connection_is_not_pinged(pool):
    with db.api_connection() as conn:
        pass
    conn.fail_ping = True  # would fail if pinged
    with db.api_connection() as again:
        pass
    assert again is conn


def test_concurrent_requests_get_distinct_connections(pool):
    with db.api_connection() as a, db.api_connection() as b:
        assert a is not b


def test_transaction_pooler_detection():
    assert db.is_transaction_pooler("postgresql://u:p@host.pooler.supabase.com:6543/postgres")
    assert not db.is_transaction_pooler("postgresql://u:p@host.pooler.supabase.com:5432/postgres")
    assert not db.is_transaction_pooler("postgresql://u:p@localhost/db")
