"""Wraps an ingestion script's main loop with ingestion_runs bookkeeping,
so every script gets consistent start/success/failure logging without
each one reimplementing it."""

from collections.abc import Iterator
from contextlib import contextmanager

from common.db import log_ingestion_run


class IngestionRunContext:
    def __init__(self):
        self.rows_affected = 0


@contextmanager
def ingestion_job(source: str) -> Iterator[IngestionRunContext]:
    """Takes only `source`, not a connection -- log_ingestion_run() opens
    its own independent connection for the bookkeeping writes (see its
    docstring), deliberately decoupled from whatever connection the
    wrapped block uses for its actual data writes."""
    ctx = IngestionRunContext()
    run_id = log_ingestion_run(source, status="running")
    try:
        yield ctx
    except Exception as exc:
        log_ingestion_run(
            source, status="failed", rows_affected=ctx.rows_affected,
            error_message=str(exc), run_id=run_id,
        )
        raise
    else:
        log_ingestion_run(
            source, status="success", rows_affected=ctx.rows_affected,
            run_id=run_id,
        )
