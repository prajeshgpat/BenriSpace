"""api/routing_data.py when routing migration 0022 is not applied: one concise warning."""

import logging

import psycopg

from api import routing_data


class MissingTableConn:
    def __init__(self):
        self.rollbacks = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        raise psycopg.errors.UndefinedTable('relation "cell_graph" does not exist')

    def rollback(self):
        self.rollbacks += 1


def test_missing_table_warns_once_without_traceback_and_falls_back(caplog):
    routing_data.clear_cache()
    conn = MissingTableConn()
    with caplog.at_level(logging.WARNING, logger="api.routing_data"):
        assert routing_data.load_graph(conn, "walk", (40.0, 41.0, -74.0, -73.0)) == {}
        assert routing_data.load_graph(conn, "walk", (40.0, 41.0, -74.0, -73.0)) == {}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "cell_graph" in warnings[0].getMessage() and warnings[0].exc_info is None
    assert conn.rollbacks == 2
    routing_data.clear_cache()


def test_other_errors_keep_the_traceback(caplog):
    class Broken(MissingTableConn):
        def execute(self, *args, **kwargs):
            raise RuntimeError("boom")

    routing_data.clear_cache()
    with caplog.at_level(logging.WARNING, logger="api.routing_data"):
        assert routing_data.airport_targets(Broken()) == []
    assert caplog.records[0].exc_info is not None
