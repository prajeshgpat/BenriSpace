"""Copy the routing tables (migration 0022) from the local build database to another database.

The full-region routing run (`python -m ingestion.routing.run --all --networks build/routing
--steps amenity,graph,hubs`, plus the rail stations and matrix from the `transit` step) writes
the local Docker database. This script moves the results to production in ONE transaction, so
the "How far can I get?" card, triangulate and the optimizer switch from straight-line
estimates to routed minutes all at once, or not at all.

    python scripts/copy_routing.py --dry-run --target-url postgresql://...
    python scripts/copy_routing.py --target-url postgresql://...

Source: ROUTING_SOURCE_URL, else AREAS_DATABASE_URL, else the local Docker database. The target
must be given explicitly (never read from DATABASE_URL, so production is never written by
accident) and must already have the tables (migration 0022). The copy replaces them: truncate,
COPY every table, verify the row counts, commit. If anything fails the target is untouched.

It refuses when the copy would take the target database past --max-db-mb (default 470 of the
free tier's 500 MB). `--dry-run` only measures.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg

DEFAULT_SOURCE_URL = "postgresql://postgres:benri@localhost:5433/postgres"
MB = 1024 * 1024

# Load order respects rail_matrix.origin_id -> routing_hubs.id.
TABLES: dict[str, str] = {
    "routing_meta": "key, value, computed_at",
    "routing_hubs": "id, kind, code, name, latitude, longitude",
    "rail_matrix": "origin_id, minutes_dm",
    "cell_travel": "geohash, mode, minutes_dm, computed_at",
    "cell_graph": "geohash, mode, latitude, longitude, edges_dm",
    "cell_hubs": "geohash, kind, hub_ids, minutes_dm",
}
MUST_HAVE_ROWS = ("routing_hubs", "rail_matrix", "cell_travel", "cell_graph", "cell_hubs")


def projected_db_mb(target_bytes: int, source_tables_bytes: int, target_tables_bytes: int) -> float:
    """Target database size in MB after replacing its routing tables with the source's."""
    return (target_bytes - target_tables_bytes + source_tables_bytes) / MB


def table_bytes(conn, tables) -> dict[str, int]:
    out = {}
    for t in tables:
        row = conn.execute(
            "select coalesce(pg_total_relation_size(to_regclass(%s)), 0)", (t,)
        ).fetchone()
        out[t] = int(row[0])
    return out


def row_counts(conn, tables) -> dict[str, int]:
    return {t: int(conn.execute(f"select count(*) from {t}").fetchone()[0]) for t in tables}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target-url", required=True, help="database to write the routing tables into")
    ap.add_argument(
        "--source-url",
        default=os.environ.get("ROUTING_SOURCE_URL")
        or os.environ.get("AREAS_DATABASE_URL")
        or DEFAULT_SOURCE_URL,
    )
    ap.add_argument("--max-db-mb", type=float, default=470.0)
    ap.add_argument("--dry-run", action="store_true", help="measure only, write nothing")
    args = ap.parse_args()
    if args.target_url == args.source_url:
        ap.error("target and source are the same database")

    with psycopg.connect(args.source_url) as src, psycopg.connect(args.target_url) as dst:
        src.read_only = True
        counts = row_counts(src, TABLES)
        empty = [t for t in MUST_HAVE_ROWS if counts[t] == 0]
        if empty:
            print(f"source tables are empty: {', '.join(empty)}; refusing to copy", file=sys.stderr)
            return 1
        missing = [
            t for t in TABLES if dst.execute("select to_regclass(%s)", (t,)).fetchone()[0] is None
        ]
        if missing:
            print(f"target lacks {', '.join(missing)}: apply migration 0022 first", file=sys.stderr)
            return 1

        src_sizes = table_bytes(src, TABLES)
        dst_sizes = table_bytes(dst, TABLES)
        target_db = int(dst.execute("select pg_database_size(current_database())").fetchone()[0])
        after = projected_db_mb(target_db, sum(src_sizes.values()), sum(dst_sizes.values()))
        print(f"{'table':14s} {'source rows':>12s} {'source MB':>10s}")
        for t in TABLES:
            print(f"{t:14s} {counts[t]:12,d} {src_sizes[t] / MB:10.1f}")
        print(
            f"target database {target_db / MB:.0f} MB now; about {after:.0f} MB after the copy"
            f" (limit for this run {args.max_db_mb:.0f} MB)"
        )
        if after > args.max_db_mb:
            print(
                "copy would leave too little room; free space first or raise --max-db-mb",
                file=sys.stderr,
            )
            return 1
        if args.dry_run:
            return 0

        with dst.transaction(), dst.cursor() as cur:
            cur.execute("truncate " + ", ".join(TABLES))
            for table, columns in TABLES.items():
                with (
                    src.cursor().copy(f"copy {table} ({columns}) to stdout") as reader,
                    cur.copy(f"copy {table} ({columns}) from stdin") as writer,
                ):
                    for block in reader:
                        writer.write(block)
            copied = row_counts(dst, TABLES)
            if copied != counts:
                raise RuntimeError(f"row counts differ after the copy: {copied} vs {counts}")
        for table in TABLES:
            dst.execute(f"analyze {table}")
        dst.commit()
        print("copied: " + ", ".join(f"{t} {n:,}" for t, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
