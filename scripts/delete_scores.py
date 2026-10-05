"""Owner-run housekeeping: delete the score rows of one retired weights version.

Old versions (64,320 rows each, one per cell) are history kept for rollback only, so they
take database space for nothing (v1-handtuned is already gone; v2-handtuned is next).
Dry run by default:

  .venv/bin/python scripts/delete_scores.py --version v2-handtuned          # counts and size only
  .venv/bin/python scripts/delete_scores.py --version v2-handtuned --yes    # delete, in batches

Deletes in batches (default 5,000 rows, one transaction each) so no single statement holds
a long lock or a huge WAL burst, prints the row counts and the database size before and
after, and refuses to touch the version the API is configured to serve. It deletes only the
one --version you name (the same rows' score_scales and score_files entries go with them). Deleted rows leave reusable free space in the table, but the
file size on disk (and so the Supabase "database size") only shrinks after
`vacuum full scores;` (takes a short exclusive lock on `scores`; run it off-peak and
only if you need the space back immediately).
"""

from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg.rows import dict_row

from common.config import DATABASE_URL, SCORING_WEIGHTS_VERSION

DEFAULT_BATCH = 5000

COUNT_SQL = "select count(*) as n from scores where weights_version = %s"
# Side tables keyed by weights_version. A missing table (migration not applied) is skipped.
SIDE_TABLES = ("score_scales", "score_files")
SIZE_SQL = (
    "select pg_size_pretty(pg_database_size(current_database())) as db, "
    "pg_size_pretty(pg_total_relation_size('scores')) as scores"
)
DELETE_BATCH_SQL = (
    "delete from scores where ctid in (select ctid from scores where weights_version = %s limit %s)"
)


def report(conn, label: str, version: str) -> int:
    with conn.cursor() as cur:
        cur.execute(COUNT_SQL, (version,))
        n = int(cur.fetchone()["n"])
        cur.execute(SIZE_SQL)
        sizes = cur.fetchone()
    print(f"{label}: {n:,} {version} rows; database {sizes['db']}; scores table {sizes['scores']}")
    return n


def drop_side_rows(conn, version: str) -> None:
    """Removes the version's rows from the tables keyed by weights_version."""
    for table in SIDE_TABLES:
        with conn.cursor() as cur:
            cur.execute("select to_regclass(%s) as t", (table,))
            if cur.fetchone()["t"] is None:
                continue
            cur.execute(f"delete from {table} where weights_version = %s", (version,))
        conn.commit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--version", required=True, help="weights_version to delete, e.g. v2-handtuned")
    ap.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    args = ap.parse_args(argv)

    version = args.version
    if SCORING_WEIGHTS_VERSION == version:
        print(f"Refusing: the API is configured to serve {version}.", file=sys.stderr)
        return 2
    if args.batch_size < 1:
        print("--batch-size must be positive.", file=sys.stderr)
        return 2

    # A plain connection (not common.db's pipelined one) so rowcount is exact per batch.
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        before = report(conn, "before", version)
        if not args.yes:
            print(
                f"Dry run: would delete {before:,} rows in batches of {args.batch_size:,}. "
                "Re-run with --yes to execute."
            )
            return 0
        deleted = 0
        while True:
            with conn.cursor() as cur:
                cur.execute(DELETE_BATCH_SQL, (version, args.batch_size))
                batch = cur.rowcount
            conn.commit()
            if batch <= 0:
                break
            deleted += batch
            print(f"  deleted {deleted:,} / {before:,}")
        drop_side_rows(conn, version)
        after = report(conn, "after ", version)
        print(
            f"Deleted {deleted:,} rows; {after:,} remain. "
            "Run `vacuum full scores;` to return disk space to the OS if needed."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
