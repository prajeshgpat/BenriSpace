"""Copy areas_slim from the local build database to another database with simplified outlines.

Owner decision: Postgres keeps only simplified polygon outlines (the free tier is 500 MB);
full detail lives in the PMTiles, which scripts/build_tiles.py builds from the LOCAL table
this script reads. Simplification is Douglas-Peucker at ~3 m (3e-5 degrees), then snapped to
the 1e-5 degree grid and made valid; an area whose simplified shape comes out empty keeps
its grid-snapped original.

    python scripts/copy_areas_slim.py --dry-run --target-url postgresql://...
    python scripts/copy_areas_slim.py --target-url postgresql://...

Source: AREAS_DATABASE_URL (default the local Docker PostGIS). The target must be given
explicitly (never read from DATABASE_URL, so production is never written by accident), must
already have areas_slim (migration 0014), and is replaced in ONE transaction. `--dry-run`
only measures the simplified rows in the source.
"""

import argparse
import os
import sys

import psycopg

from ingestion.areas.slim import INSERT_SLIM_SQL, PROD_SIMPLIFY_DEG, simplified_select_sql

DEFAULT_SOURCE_URL = "postgresql://postgres:benri@localhost:5433/postgres"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target-url", required=True, help="database to write areas_slim into")
    ap.add_argument(
        "--source-url", default=os.environ.get("AREAS_DATABASE_URL", DEFAULT_SOURCE_URL)
    )
    ap.add_argument("--tolerance-deg", type=float, default=PROD_SIMPLIFY_DEG)
    ap.add_argument("--dry-run", action="store_true", help="measure only, write nothing")
    args = ap.parse_args()
    if args.target_url == args.source_url:
        ap.error("target and source are the same database")

    sql = simplified_select_sql(args.tolerance_deg)
    with psycopg.connect(args.source_url) as src:
        src.read_only = True
        rows = src.execute(sql).fetchall()
        full = src.execute("select sum(st_npoints(geom)) from areas_slim").fetchone()[0]
    if not rows:
        print("source areas_slim is empty; refusing to copy", file=sys.stderr)
        return 1
    wkb_bytes = sum(len(r[3]) for r in rows)
    print(f"{len(rows)} areas, tolerance {args.tolerance_deg} deg, {wkb_bytes / 1e6:.1f} MB of WKB")
    print(f"vertices in the source table: {full}")
    if args.dry_run:
        return 0
    with psycopg.connect(args.target_url) as dst:
        with dst.cursor() as cur:
            cur.execute("delete from areas_slim")
            cur.executemany(INSERT_SLIM_SQL, rows)
            cur.execute("analyze areas_slim")
        dst.commit()
    print(f"copied {len(rows)} areas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
