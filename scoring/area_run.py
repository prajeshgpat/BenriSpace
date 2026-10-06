"""Score every road-bounded area for a density weights version (v2.2-density) and publish it.

    python -m ingestion.routing.reach                # routed inputs -> build/reach/reach.npz
    python -m scoring.area_run                       # score; write build files only
    python -m scoring.area_run --write               # ...and write the database (production)
    python -m scoring.area_run --preview build/preview   # local static files for the web app

Inputs
  build/reach/reach.npz   routed density, proximity and transit inputs per area
  AREAS_DATABASE_URL      areas_slim and the grid (local Docker database by default):
                          which area each grid cell falls in, names and metros
  DATABASE_URL            feature_store, read-only unless --write

Factors
  restaurant, cafe, bar, shopping, grocery, gym, gas & convenience, transit:
      scoring/density.py (absolute scales, routed reach)
  school:   20 % proximity (routed) + 80 % district rating (a statewide percentile, 0-100);
            no score where the district has no rating, as in v2.1
  airport:  drive minutes from the cell (density.AIRPORT_DRIVE curve)
  traffic, noise corridor, recreation:
            the v2.1 signals, normalized ONCE over the whole region (2nd-98th percentile)
            instead of per sub-region
  Cell-based factors are averaged over the cells inside each area (the nearest cell for an
  area too small to hold one). Every cell then takes its area's scores, so the map, hover,
  card, score file and /v1/score all agree.

Outputs (always)
  build/static/area-scores.<version>.bin   the static per-area file (api/areafile.py) that
                                           scripts/publish_static.py uploads
  build/scores/<version>.npz               area and cell scores, for review
With --write, in one transaction: area_scores rows, `scores` rows for every cell, then the
persisted score file (api.scorefile).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from api import areafile
from api.factors import FACTOR_COLUMNS
from api.scorefile import FACTOR_KEYS, NULL_BYTE
from common.feature_columns import from_db_row
from ingestion.routing.reach import LOCAL_DATABASE_URL, OUT_PATH, to_miles_xy
from scoring import density
from scoring.engine import (
    CATEGORY_SPECS_V2_1,
    V2_1_WEIGHTS,
    WEIGHTS_VERSION_V2_2,
    _spec_scores,
    robust_normalize,
)

SCHOOL_PROXIMITY_WEIGHT = 0.2
REGION_WIDE = ("road_score", "emergency_corridor_score", "recreation_score")
SCORE_COLUMNS = [*FACTOR_COLUMNS.values(), "school_proximity_score"]
DENSITY_KEYS = {  # density.score() key -> score column
    "restaurant": "restaurant_score",
    "cafe": "cafe_score",
    "bar": "bar_score",
    "shopping": "shopping_score",
    "grocery": "grocery_score",
    "gym": "gym_score",
    "gasConvenience": "gas_convenience_score",
    "transit": "transit_score",
    "schoolProximity": "school_proximity_score",
}

CELLS_SQL = """
select ge.geohash, ge.latitude::float8 as lat, ge.longitude::float8 as lon, a.id as area_id
from geo_entities ge
left join areas_slim a
  on st_contains(a.geom, st_setsrid(st_makepoint(ge.longitude, ge.latitude), 4326))
where length(ge.geohash) = 6
"""
AREA_NAMES_SQL = "select id, neighborhood, metro_area from areas_slim"
FEATURES_SQL = """
select ge.id::text as geo_entity_id, ge.geohash, ge.metro_area, fs.*
from feature_store fs join geo_entities ge on ge.id = fs.geo_entity_id
where length(ge.geohash) = 6
"""


def cell_factor_scores(rows: list[dict]) -> dict[str, dict[str, float]]:
    """{score column: {geohash: 0-100}} for the cell-based factors, over the whole region."""
    by_column = {s.score_column: s for s in CATEGORY_SPECS_V2_1}
    by_id = {r["geo_entity_id"]: r["geohash"] for r in rows}
    out: dict[str, dict[str, float]] = {}
    for column in REGION_WIDE:
        scores, _ = _spec_scores(rows, by_column[column], robust_normalize)
        out[column] = {by_id[k]: v for k, v in scores.items()}
    airport = {}
    rating = {}
    for r in rows:
        minutes = r.get("airport_drive_time_min")
        if minutes is not None:
            airport[r["geohash"]] = 100.0 * float(
                density.AIRPORT_DRIVE(np.array([float(minutes)]))[0]
            )
        value = r.get("school_avg_rating_1600m")
        if value is not None:
            rating[r["geohash"]] = min(100.0, max(0.0, float(value)))
    out["airport_score"] = airport
    out["school_rating"] = rating
    return out


def area_means(
    cell_values: dict[str, float],
    cell_area: dict[str, int],
    area_index: dict[int, int],
    n_areas: int,
    fallback_cell: list[str],
) -> np.ndarray:
    """Mean of each area's cells (NaN-free), else the area's nearest cell, else NaN."""
    total = np.zeros(n_areas)
    count = np.zeros(n_areas)
    for geohash, value in cell_values.items():
        i = area_index.get(cell_area.get(geohash, -1))
        if i is not None:
            total[i] += value
            count[i] += 1
    out = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    for i in np.flatnonzero(count == 0):
        out[i] = cell_values.get(fallback_cell[i], np.nan)
    return out


def composite(scores: dict[str, np.ndarray]) -> np.ndarray:
    """v2.1 default weights over the factors each area has (the web recomputes per filter)."""
    num = np.zeros(len(next(iter(scores.values()))))
    den = np.zeros_like(num)
    for column, weight in V2_1_WEIGHTS.items():
        values = scores.get(column)
        if values is None:
            continue
        ok = ~np.isnan(values)
        num[ok] += weight * values[ok]
        den[ok] += weight
    return np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)


def to_int(values: np.ndarray) -> list[int | None]:
    """Whole points, half up (like the score file); None for NaN."""
    return [None if np.isnan(v) else int(min(100.0, max(0.0, v)) + 0.5) for v in values]


def build(reach_path: Path, areas_conn, features_conn) -> dict:
    t0 = time.time()
    r = density.Reach.load(reach_path)
    area_ids = r.area_id.astype(np.int64)
    area_index = {int(a): i for i, a in enumerate(area_ids)}
    n = len(area_ids)

    with areas_conn.cursor() as cur:
        cur.execute(CELLS_SQL)
        cells = cur.fetchall()
        cur.execute(AREA_NAMES_SQL)
        names = {int(x["id"]): (x["neighborhood"], x["metro_area"]) for x in cur.fetchall()}
    with features_conn.cursor() as cur:
        cur.execute(FEATURES_SQL)
        rows = [from_db_row(x) for x in cur.fetchall()]
    print(
        f"[area_run] {n:,} areas, {len(cells):,} cells, inputs {time.time() - t0:.0f}s",
        file=sys.stderr,
    )

    # Each cell's area: the polygon holding its centre, else the nearest area origin.
    from scipy.spatial import cKDTree

    with np.load(reach_path) as z:
        o_lat, o_lon = z["lat"], z["lon"]
    ref = float(np.mean(o_lat))
    origin_tree = cKDTree(to_miles_xy(o_lat, o_lon, ref))
    c_lat = np.array([c["lat"] for c in cells])
    c_lon = np.array([c["lon"] for c in cells])
    _, nearest_origin = origin_tree.query(to_miles_xy(c_lat, c_lon, ref))
    cell_area = {
        c["geohash"]: int(c["area_id"]) if c["area_id"] is not None else int(area_ids[j])
        for c, j in zip(cells, nearest_origin, strict=True)
    }
    # Each area's nearest cell, for areas too small to contain a cell centre.
    _, nearest_cell = cKDTree(to_miles_xy(c_lat, c_lon, ref)).query(to_miles_xy(o_lat, o_lon, ref))
    fallback_cell = [cells[j]["geohash"] for j in nearest_cell]

    dens = density.score(r)
    scores = {
        column: np.asarray(dens[key], dtype=np.float64) for key, column in DENSITY_KEYS.items()
    }
    per_cell = cell_factor_scores(rows)
    for column in (*REGION_WIDE, "airport_score"):
        scores[column] = area_means(per_cell[column], cell_area, area_index, n, fallback_cell)
    rating = area_means(per_cell["school_rating"], cell_area, area_index, n, fallback_cell)
    scores["school_score"] = np.where(
        np.isnan(rating),
        np.nan,
        SCHOOL_PROXIMITY_WEIGHT * scores["school_proximity_score"]
        + (1 - SCHOOL_PROXIMITY_WEIGHT) * rating,
    )
    scores["composite_score"] = composite({c: scores[c] for c in FACTOR_COLUMNS.values()})
    print(f"[area_run] scored in {time.time() - t0:.0f}s", file=sys.stderr)
    return {
        "area_ids": area_ids,
        "lat": o_lat,
        "lon": o_lon,
        "names": names,
        "scores": scores,
        "cell_area": cell_area,
        "area_index": area_index,
    }


def area_file(built: dict, version: str, generated_at: str) -> bytes:
    columns = [FACTOR_COLUMNS[k] for k in FACTOR_KEYS]
    ints = {c: to_int(built["scores"][c]) for c in columns}
    rows = []
    for i, aid in enumerate(built["area_ids"]):
        name, metro = built["names"].get(int(aid), (None, None))
        values = tuple(NULL_BYTE if ints[c][i] is None else ints[c][i] for c in columns)
        rows.append(
            areafile.AreaRow(
                int(aid), float(built["lat"][i]), float(built["lon"][i]), name, metro, values
            )
        )
    return areafile.encode(rows, version, generated_at)


AREA_UPSERT = (
    "insert into area_scores (area_id, weights_version, "
    + ", ".join(SCORE_COLUMNS)
    + ", composite_score) values ("
    + ", ".join(["%s"] * (len(SCORE_COLUMNS) + 3))
    + ") on conflict (area_id, weights_version) do update set "
    + ", ".join(f"{c} = excluded.{c}" for c in [*SCORE_COLUMNS, "composite_score"])
    + ", computed_at = now()"
)
CELL_UPSERT = (
    "insert into scores (geo_entity_id, weights_version, "
    + ", ".join(SCORE_COLUMNS)
    + ", composite_score) select ge.id, %s, "
    + ", ".join(["%s"] * (len(SCORE_COLUMNS) + 1))
    + " from geo_entities ge where ge.geohash = %s"
    + " on conflict (geo_entity_id, weights_version) do update set "
    + ", ".join(f"{c} = excluded.{c}" for c in [*SCORE_COLUMNS, "composite_score"])
    + ", computed_at = now()"
)


def row_values(built: dict, i: int) -> list:
    s = built["scores"]
    values: list = [to_int(s[c][i : i + 1])[0] for c in SCORE_COLUMNS]
    comp = s["composite_score"][i]
    values.append(None if np.isnan(comp) else round(float(comp), 1))
    return values


def write(conn, built: dict, version: str) -> dict:
    """area_scores + every cell's scores rows in one transaction."""
    area_rows = [
        [int(aid), version, *row_values(built, i)] for i, aid in enumerate(built["area_ids"])
    ]
    cell_rows = [
        [version, *row_values(built, built["area_index"][aid]), geohash]
        for geohash, aid in built["cell_area"].items()
        if aid in built["area_index"]
    ]
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(AREA_UPSERT, area_rows)
        cur.executemany(CELL_UPSERT, cell_rows)
    return {"area_rows": len(area_rows), "cell_rows": len(cell_rows)}


def score_file(built: dict, version: str, stamp: datetime) -> bytes:
    """The /v1/map/scores body for the cells, each carrying its area's scores."""
    from api import scorefile

    s = built["scores"]
    rows = []
    for geohash, aid in built["cell_area"].items():
        i = built["area_index"].get(aid)
        if i is None:
            continue
        rows.append({"geohash": geohash, **{c: s[c][i] for c in FACTOR_COLUMNS.values()}})
    for row in rows:
        for c in FACTOR_COLUMNS.values():
            if np.isnan(row[c]):
                row[c] = None
    return scorefile.encode(rows, version, stamp)


def write_preview(directory: Path, built: dict, version: str, stamp: datetime, areas: bytes):
    """A static folder the web app can use as NEXT_PUBLIC_STATIC_URL (tiles stay on R2:
    set NEXT_PUBLIC_PMTILES_URL)."""
    import json

    from scripts.publish_static import MANIFEST_FORMAT, entry

    files = {"scores": score_file(built, version, stamp), "areaScores": areas}
    manifest = {
        "format": MANIFEST_FORMAT,
        "weightsVersion": version,
        "generatedAt": stamp.isoformat(timespec="seconds"),
    }
    for kind, data in files.items():
        manifest[kind] = entry(kind, version, data)
        path = directory / manifest[kind]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))


def main(argv: list[str] | None = None) -> None:
    import psycopg
    from dotenv import load_dotenv
    from psycopg.rows import dict_row

    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reach", type=Path, default=OUT_PATH)
    ap.add_argument("--version", default=WEIGHTS_VERSION_V2_2)
    ap.add_argument("--write", action="store_true", help="write DATABASE_URL (production)")
    ap.add_argument("--preview", type=Path, help="also write a static preview folder here")
    args = ap.parse_args(argv)

    areas_url = os.environ.get("AREAS_DATABASE_URL", "").strip() or LOCAL_DATABASE_URL
    db_url = os.environ["DATABASE_URL"]
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat(timespec="seconds")
    with (
        psycopg.connect(areas_url, row_factory=dict_row) as aconn,
        psycopg.connect(db_url, row_factory=dict_row) as conn,
    ):
        aconn.read_only = True
        conn.read_only = True
        built = build(args.reach, aconn, conn)
    out = Path("build/static") / f"area-scores.{args.version}.bin"
    out.parent.mkdir(parents=True, exist_ok=True)
    areas = area_file(built, args.version, generated_at)
    out.write_bytes(areas)
    if args.preview:
        write_preview(args.preview, built, args.version, now, areas)
        print(f"[area_run] preview in {args.preview}", file=sys.stderr)
    review = Path("build/scores") / f"{args.version}.npz"
    review.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(review, area_id=built["area_ids"], **built["scores"])
    print(f"[area_run] wrote {out} and {review}", file=sys.stderr)
    if args.write:
        from api import scorefile

        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            counts = write(conn, built, args.version)
            size = scorefile.store(conn, args.version)
        print(f"[area_run] wrote {counts}; score file {size:,} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
