"""Wraps an ingestion script's main loop with ingestion_runs bookkeeping,
so every script gets consistent start/success/failure logging without
each one reimplementing it."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from common.db import log_ingestion_run


class IngestionRunContext:
    def __init__(self):
        self.rows_affected = 0


@contextmanager
def ingestion_job(conn: psycopg.Connection, source: str) -> Iterator[IngestionRunContext]:
    ctx = IngestionRunContext()
    run_id = log_ingestion_run(conn, source, status="running")
    try:
        yield ctx
    except Exception as exc:
        log_ingestion_run(
            conn, source, status="failed", rows_affected=ctx.rows_affected,
            error_message=str(exc), run_id=run_id,
        )
        raise
    else:
        log_ingestion_run(
            conn, source, status="success", rows_affected=ctx.rows_affected,
            run_id=run_id,
        )
