"""Build the static area-scores file (api/areafile.py) for every road-bounded area.

Each area is scored exactly as GET /v1/area?precision=point does: sample_points over the
slim polygon, api.point_score.score_points_cells, area_aggregate_from_points, then the 13
sub-scores quantized like the score file. Many areas' sample points go into ONE scoring
call (one cell query + one live places query), and a few workers run in parallel.

    python scripts/build_area_scores.py                    # all areas, resumable
    python scripts/build_area_scores.py --limit 300        # quick throughput test
    python scripts/build_area_scores.py --out build/static --workers 3

Areas come from AREAS_DATABASE_URL (default: the local Docker PostGIS, table areas_slim).
Scores are read through DATABASE_URL in READ-ONLY sessions; nothing is written to any
database. Progress is appended to build/area_scores.<version>.jsonl (gitignored), one line
per finished area, so a crash or Ctrl-C resumes where it stopped. The output is
build/static/area-scores.<version>.bin (uncompressed; scripts/publish_static.py
hashes, gzips and uploads it).
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from api import areafile, point_score
from api.areas import point_in_polygon
from api.factors import FACTOR_COLUMNS
from api.lookup import FALLBACK_BBOX_MARGIN_DEG
from api.scorefile import FACTOR_KEYS, NULL_BYTE, quantize
from common.geo import encode as geohash_encode
from scoring.point import sample_points

DEFAULT_AREAS_URL = "postgresql://postgres:benri@localhost:5433/postgres"
AREAS_SQL = (
    "select id, neighborhood, metro_area, "
    "st_y(st_pointonsurface(geom)) as lat, st_x(st_pointonsurface(geom)) as lon, "
    "st_asgeojson(geom, 6) as geojson from areas_slim where id > %s order by id"
)
BATCH_AREAS = 20  # about 100 sample points per scoring call
COLUMNS = list(FACTOR_COLUMNS.values())

_print_lock = threading.Lock()


def log(message: str) -> None:
    with _print_lock:
        print(message, file=sys.stderr, flush=True)


def area_scores(aggregate: dict) -> list[int]:
    return [quantize(aggregate.get(c)) for c in COLUMNS]


def samples_for(row: dict) -> list[tuple[float, float]]:
    geometry = json.loads(row["geojson"])
    return sample_points(geometry, point_in_polygon) or [(row["lat"], row["lon"])]


# Which sample points have a cell the API would use: the exact geohash6 cell, else any cell in
# the fallback bbox (api.lookup.bbox_around). Lets out-of-coverage areas (about a third, mostly
# with no metro) be dropped in one cheap query instead of failing a whole scoring call.
COVERED_SQL = """
    select p.i from unnest(%s::int[], %s::float8[], %s::float8[], %s::text[]) as p(i, lat, lon, gh)
    where exists (select 1 from geo_entities ge where ge.geohash = p.gh)
       or exists (select 1 from geo_entities ge
                  where ge.latitude between p.lat - %s and p.lat + %s
                    and ge.longitude between p.lon - %s and p.lon + %s)
"""


def covered_areas(conn, rows: list[dict], per_area: list[list[tuple[float, float]]]) -> set[int]:
    """Ids of areas whose sample points ALL have a cell (so scoring cannot raise for them)."""
    owner = [a for a, pts in enumerate(per_area) for _ in pts]
    flat = [p for pts in per_area for p in pts]
    margin = FALLBACK_BBOX_MARGIN_DEG
    with conn.cursor() as cur:
        cur.execute(
            COVERED_SQL,
            (
                list(range(len(flat))),
                [lat for lat, _ in flat],
                [lon for _, lon in flat],
                [geohash_encode(lat, lon, precision=6) for lat, lon in flat],
                margin,
                margin,
                margin,
                margin,
            ),
        )
        have = {r["i"] for r in cur.fetchall()}
    conn.rollback()
    missing = {owner[k] for k in range(len(flat)) if k not in have}
    return {r["id"] for a, r in enumerate(rows) if a not in missing}


def score_batch(conn, rows: list[dict], version: str) -> dict[int, list[int] | None]:
    """{area id: 13 quantized scores, or None when the area has no score}. One scoring call
    for the whole batch; if any point cannot be scored the batch is redone area by area."""
    per_area = [samples_for(r) for r in rows]
    covered = covered_areas(conn, rows, per_area)
    out: dict[int, list[int] | None] = {r["id"]: None for r in rows if r["id"] not in covered}
    keep = [(r, pts) for r, pts in zip(rows, per_area, strict=True) if r["id"] in covered]
    if not keep:
        return out
    rows = [r for r, _ in keep]
    per_area = [pts for _, pts in keep]
    flat = [p for points in per_area for p in points]
    try:
        results, _ = point_score.score_points_cells(conn, flat, version)
        conn.rollback()  # read-only; ends the transaction between batches
    except point_score.PointScoringError:
        conn.rollback()
        if len(rows) == 1:
            return {**out, rows[0]["id"]: None}
        for r in rows:
            out.update(score_batch(conn, [r], version))
        return out
    at = 0
    for row, points in zip(rows, per_area, strict=True):
        chunk = results[at : at + len(points)]
        at += len(points)
        aggregate = point_score.area_aggregate_from_points(chunk, version)
        out[row["id"]] = area_scores(aggregate)
    return out


def load_done(path: Path) -> dict[int, list[int] | None]:
    done: dict[int, list[int] | None] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:  # a torn last line from a crash
                continue
            done[rec["id"]] = rec["s"]
    return done


def worker(
    wid: int, batches: list[list[dict]], url: str, version: str, sink, started: float, total: int
):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.read_only = True
        for rows in batches:
            for attempt in range(4):
                try:
                    scores = score_batch(conn, rows, version)
                    break
                except psycopg.OperationalError as exc:
                    log(f"worker {wid}: {exc}; retrying")
                    time.sleep(5 * (attempt + 1))
                    conn.close()
                    conn = psycopg.connect(url, row_factory=dict_row)
                    conn.read_only = True
            else:
                raise RuntimeError("giving up after repeated connection errors")
            n = sink(scores)
            if n % 500 < len(rows):
                rate = n / (time.time() - started)
                log(f"{n}/{total} areas, {rate:.1f}/s, eta {(total - n) / rate / 60:.0f} min")


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="build/static", help="output directory")
    ap.add_argument("--workers", type=int, default=3, help="parallel connections (max 4)")
    ap.add_argument("--limit", type=int, default=0, help="score only the first N areas")
    ap.add_argument("--every", type=int, default=1, help="score every Nth area (throughput test)")
    ap.add_argument("--batch", type=int, default=BATCH_AREAS, help="areas per scoring call")
    ap.add_argument("--fresh", action="store_true", help="ignore the checkpoint")
    ap.add_argument("--weights-version", default="")
    args = ap.parse_args()
    if not 1 <= args.workers <= 4:
        ap.error("--workers must be 1..4 (Supabase free tier)")

    from common.config import SCORING_WEIGHTS_VERSION

    version = args.weights_version or SCORING_WEIGHTS_VERSION
    url = os.environ["DATABASE_URL"]
    areas_url = os.environ.get("AREAS_DATABASE_URL", "").strip() or DEFAULT_AREAS_URL

    with psycopg.connect(areas_url, row_factory=dict_row) as aconn:
        areas = aconn.execute(AREAS_SQL, (0,)).fetchall()
    areas = areas[:: args.every]
    if args.limit:
        areas = areas[: args.limit]

    checkpoint = Path("build") / f"area_scores.{version}.jsonl"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    if args.fresh and checkpoint.exists():
        checkpoint.unlink()
    done = load_done(checkpoint)
    todo = [a for a in areas if a["id"] not in done]
    log(f"{len(areas)} areas, {len(done)} already done, {len(todo)} to score ({version})")

    lock = threading.Lock()
    handle = checkpoint.open("a")
    counter = [len(done)]

    def sink(scores: dict[int, list[int] | None]) -> int:
        with lock:
            for aid, s in scores.items():
                handle.write(json.dumps({"id": aid, "s": s}, separators=(",", ":")) + "\n")
                done[aid] = s
            handle.flush()
            counter[0] += len(scores)
            return counter[0]

    batches = [todo[i : i + args.batch] for i in range(0, len(todo), args.batch)]
    started = time.time()
    if batches:
        shares = [batches[i :: args.workers] for i in range(args.workers)]
        with ThreadPoolExecutor(args.workers) as pool:
            futures = [
                pool.submit(worker, i, share, url, version, sink, started, len(areas))
                for i, share in enumerate(shares)
                if share
            ]
            for f in futures:
                f.result()
        elapsed = time.time() - started
        log(f"scored {len(todo)} areas in {elapsed:.0f}s ({len(todo) / elapsed:.1f}/s)")
    handle.close()

    rows = [
        areafile.AreaRow(
            a["id"],
            a["lat"],
            a["lon"],
            a["neighborhood"],
            a["metro_area"],
            tuple(done[a["id"]] or [NULL_BYTE] * len(FACTOR_KEYS)),
        )
        for a in areas
    ]
    body = areafile.encode(rows, version, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = ".partial" if args.limit or args.every > 1 else ""
    target = out / f"area-scores.{version}{suffix}.bin"
    target.write_bytes(body)
    unscored = sum(1 for a in areas if done[a["id"]] is None)
    log(f"wrote {target} ({len(body):,} bytes, {len(rows)} areas, {unscored} without scores)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
