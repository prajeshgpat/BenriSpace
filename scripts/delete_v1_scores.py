"""Owner-run housekeeping: delete the retired v1 score rows (weights_version 'v1-handtuned').

The v1 rows (64,320, one per cell) are history kept for rollback only; v2 and v2.1 are
the live models, so they take database space for nothing. Dry run by default:

  .venv/bin/python scripts/delete_v1_scores.py            # counts and size only
  .venv/bin/python scripts/delete_v1_scores.py --yes      # delete, in batches

Deletes in batches (default 5,000 rows, one transaction each) so no single statement holds
a long lock or a huge WAL burst, prints the row counts and the database size before and
after, and refuses to touch the version the API is configured to serve. It never deletes
any other weights_version. Deleted rows leave reusable free space in the table, but the
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

VERSION = "v1-handtuned"
DEFAULT_BATCH = 5000

COUNT_SQL = "select count(*) as n from scores where weights_version = %s"
SIZE_SQL = (
    "select pg_size_pretty(pg_database_size(current_database())) as db, "
    "pg_size_pretty(pg_total_relation_size('scores')) as scores"
)
DELETE_BATCH_SQL = (
    "delete from scores where ctid in (select ctid from scores where weights_version = %s limit %s)"
)


def report(conn, label: str) -> int:
    with conn.cursor() as cur:
        cur.execute(COUNT_SQL, (VERSION,))
        n = int(cur.fetchone()["n"])
        cur.execute(SIZE_SQL)
        sizes = cur.fetchone()
    print(f"{label}: {n:,} {VERSION} rows; database {sizes['db']}; scores table {sizes['scores']}")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    args = ap.parse_args(argv)

    if SCORING_WEIGHTS_VERSION == VERSION:
        print(f"Refusing: the API is configured to serve {VERSION}.", file=sys.stderr)
        return 2
    if args.batch_size < 1:
        print("--batch-size must be positive.", file=sys.stderr)
        return 2

    # A plain connection (not common.db's pipelined one) so rowcount is exact per batch.
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        before = report(conn, "before")
        if not args.yes:
            print(
                f"Dry run: would delete {before:,} rows in batches of {args.batch_size:,}. "
                "Re-run with --yes to execute."
            )
            return 0
        deleted = 0
        while True:
            with conn.cursor() as cur:
                cur.execute(DELETE_BATCH_SQL, (VERSION, args.batch_size))
                batch = cur.rowcount
            conn.commit()
            if batch <= 0:
                break
            deleted += batch
            print(f"  deleted {deleted:,} / {before:,}")
        after = report(conn, "after ")
        print(
            f"Deleted {deleted:,} rows; {after:,} remain. "
            "Run `vacuum full scores;` to return disk space to the OS if needed."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
