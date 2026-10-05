"""Read-only validation of on-demand (precision=point) scoring against the stored
v2.1 scores. Prints markdown tables. Writes nothing to the database.

  .venv/bin/python scripts/validate_point_scoring.py cells  --n 300
  .venv/bin/python scripts/validate_point_scoring.py cross  --n 300
  .venv/bin/python scripts/validate_point_scoring.py places --api http://127.0.0.1:8000 --calls 50

cells   random cells scored at their own centroid (a point scored at a cell's centre
        should give the cell's stored score). Three variants: the engine on the stored
        raw row (control: proves the scales reproduce the stored scores), the
        production anchored method, and pure live (no anchoring).
cross   out-of-sample test of the anchoring: cell A is scored at A's centroid but
        anchored on its east neighbour B (as if the point sat in B), compared with A's
        stored score; B's stored score (what the grid would answer) is shown for contrast.
places  ten named places through a running API: grid vs precision=point, and latency.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

import pygeohash as pgh

from api import point_score as ps
from common.db import get_connection
from scoring.engine import WEIGHTS_VERSION_V2_1, all_score_columns
from scoring.point import (
    ALL_ANCHOR,
    DEFAULT_ANCHOR,
    NO_ANCHOR,
    build_point_features,
    execute_live,
    read_live,
)
from scoring.scales import score_row

VERSION = WEIGHTS_VERSION_V2_1
COLUMNS = [c for c in all_score_columns(VERSION)]

NAMED_PLACES = [
    ("Park Slope", 40.672, -73.978),
    ("NoMad", 40.7484, -73.9857),
    ("Astoria", 40.764, -73.923),
    ("Hoboken", 40.744, -74.032),
    ("Montclair", 40.8259, -74.209),
    ("Stamford", 41.0525, -73.539),
    ("White Plains", 41.033, -73.763),
    ("Huntington", 40.868, -73.425),
    ("Princeton", 40.357, -74.667),
    ("Newtown", 41.414, -73.303),
]


def random_cells(conn, n: int, seed: float = 0.42) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("select setseed(%s)", (seed,))
        cur.execute(
            "select ge.id, ge.geohash, ge.metro_area from geo_entities ge "
            "join scores s on s.geo_entity_id = ge.id and s.weights_version = %s "
            "order by random() limit %s",
            (VERSION, n),
        )
        return cur.fetchall()


def cell_rows(conn, geohashes: list[str]) -> dict[str, dict]:
    return ps._fetch_cells(conn, sorted(set(geohashes)))


def stored_scores(conn, ids: list[str]) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(
            "select * from scores where weights_version = %s and geo_entity_id = any(%s)",
            (VERSION, ids),
        )
        return {str(r["geo_entity_id"]): r for r in cur.fetchall()}


def live_for(conn, points: list[tuple]):
    with conn.cursor() as cur:
        execute_live(cur, points, ALL_ANCHOR)
        return read_live(cur)


def diffs_table(title: str, diffs: dict[str, list[float]]) -> None:
    print(f"\n### {title}\n")
    print("| column | n | mean abs | median abs | p90 abs | max abs |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for col, vals in diffs.items():
        if not vals:
            print(f"| {col} | 0 | - | - | - | - |")
            continue
        s = sorted(vals)
        print(
            f"| {col} | {len(s)} | {statistics.fmean(s):.2f} | {statistics.median(s):.2f} | "
            f"{s[int(len(s) * 0.9)]:.2f} | {s[-1]:.2f} |"
        )


def compare(got: dict, stored: dict, diffs: dict[str, list[float]], mismatch: dict[str, int]):
    for col in COLUMNS:
        g, s = got.get(col), stored.get(col)
        if g is None and s is None:
            continue
        if g is None or s is None:
            mismatch[col] = mismatch.get(col, 0) + 1
            continue
        diffs.setdefault(col, []).append(abs(float(g) - float(s)))


def run_cells(n: int) -> None:
    with get_connection() as conn:
        picks = random_cells(conn, n)
        cells = cell_rows(conn, [p["geohash"] for p in picks])
        stored = stored_scores(conn, [str(p["id"]) for p in picks])
        metros = sorted({p["metro_area"] for p in picks})
        for m in metros:
            ps.load_scales(conn, VERSION, m)
        print(
            f"{len(picks)} random cells; metros: "
            + ", ".join(f"{m} ({sum(1 for p in picks if p['metro_area'] == m)})" for m in metros)
        )

        variants: dict[str, tuple[dict, dict]] = {
            k: ({}, {}) for k in ("control", "anchored", "pure")
        }
        anchor_sets = {"anchored": DEFAULT_ANCHOR, "pure": NO_ANCHOR}
        by_metro: dict[str, list[float]] = {}
        batch = 12
        for start in range(0, len(picks), batch):
            chunk = picks[start : start + batch]
            pts = [
                (p["geohash"], cells[p["geohash"]]["latitude"], cells[p["geohash"]]["longitude"])
                for p in chunk
            ]
            live = live_for(conn, pts)
            for i, p in enumerate(chunk):
                c = cells[p["geohash"]]
                scales = ps.load_scales(conn, VERSION, p["metro_area"])
                st = stored[str(p["id"])]
                compare(score_row(c, VERSION, scales), st, *variants["control"])
                for name, anchor in anchor_sets.items():
                    feats = build_point_features(
                        c, c["latitude"], c["longitude"], live, i, anchor
                    ).row
                    got = score_row(feats, VERSION, scales)
                    compare(got, st, *variants[name])
                    if name == "anchored" and "composite_score" in got:
                        by_metro.setdefault(p["metro_area"], []).append(
                            abs(got["composite_score"] - float(st["composite_score"]))
                        )
        diffs_table(
            "Control: engine on the stored raw row with the table-free scales",
            variants["control"][0],
        )
        diffs_table(
            "Production method (anchored live), cell scored at its centroid",
            variants["anchored"][0],
        )
        diffs_table("Pure live (no anchoring), cell scored at its centroid", variants["pure"][0])
        for name, (_, mism) in variants.items():
            if mism:
                print(f"\nnull/non-null mismatches vs stored ({name}): {mism}")
        print("\n### Composite abs diff by metro (anchored)\n")
        print("| metro | n | mean | max |")
        print("| --- | ---: | ---: | ---: |")
        for m, v in sorted(by_metro.items()):
            print(f"| {m} | {len(v)} | {statistics.fmean(v):.2f} | {max(v):.2f} |")
        print("\nscales source / cold load ms:", ps.scales_info())


def run_cross(n: int) -> None:
    with get_connection() as conn:
        picks = random_cells(conn, n, seed=0.17)
        east = {p["geohash"]: pgh.get_adjacent(p["geohash"], "right") for p in picks}
        cells = cell_rows(conn, [*east.keys(), *east.values()])
        ids = {gh: str(c["id"]) for gh, c in cells.items()}
        stored = stored_scores(conn, list(ids.values()))
        usable = [p for p in picks if p["geohash"] in cells and east[p["geohash"]] in cells]
        for m in {cells[p["geohash"]]["metro_area"] for p in usable}:
            ps.load_scales(conn, VERSION, m)
        anchor_sets = {"default": DEFAULT_ANCHOR, "all": ALL_ANCHOR, "none": NO_ANCHOR}
        res = {k: ({}, {}) for k in (*anchor_sets, "neighbour_grid")}
        batch = 12
        for start in range(0, len(usable), batch):
            chunk = usable[start : start + batch]
            pts = []
            for p in chunk:
                a, b = cells[p["geohash"]], cells[east[p["geohash"]]]
                pts.append((b["geohash"], a["latitude"], a["longitude"]))
            live = live_for(conn, pts)
            for i, p in enumerate(chunk):
                a, b = cells[p["geohash"]], cells[east[p["geohash"]]]
                scales = ps.load_scales(conn, VERSION, a["metro_area"])
                truth = stored[ids[p["geohash"]]]
                for name, anchor in anchor_sets.items():
                    feats = build_point_features(
                        b, a["latitude"], a["longitude"], live, i, anchor
                    ).row
                    compare(score_row(feats, VERSION, scales), truth, *res[name])
                compare(stored[ids[east[p["geohash"]]]], truth, *res["neighbour_grid"])
        print(
            f"{len(usable)} cells scored at their own centroid but anchored on the east neighbour"
        )
        diffs_table(
            "Anchor: default set (POI categories, transit, shopping, park)", res["default"][0]
        )
        diffs_table("Anchor: every category", res["all"][0])
        diffs_table(
            "Anchor: none (pure live; neighbour only supplies cell-only fields)", res["none"][0]
        )
        diffs_table(
            "Baseline: the neighbour's stored grid score (what the grid would say)",
            res["neighbour_grid"][0],
        )


def run_places(api: str, calls: int) -> None:
    import httpx

    client = httpx.Client(base_url=api, timeout=30)
    print("| place | grid | point | delta | factors that moved >= 5 |")
    print("| --- | ---: | ---: | ---: | --- |")
    lat_point: list[float] = []
    lat_grid: list[float] = []
    for name, lat, lon in NAMED_PLACES:
        grid = client.get("/v1/score", params={"lat": lat, "lon": lon}).json()
        point = client.get(
            "/v1/score", params={"lat": lat, "lon": lon, "precision": "point"}
        ).json()
        moved = []
        for k, v in point["subScores"].items():
            g = grid["subScores"].get(k)
            if v is not None and g is not None and abs(v - g) >= 5:
                moved.append(f"{k} {g:.0f}->{v:.0f}")
        print(
            f"| {name} | {grid['compositeScore']:.1f} | {point['compositeScore']:.1f} "
            f"({point.get('precision')}) | {point['compositeScore'] - grid['compositeScore']:+.1f} "
            f"| {', '.join(moved) or '-'} |"
        )
    for label, params, bucket in (
        ("grid", {}, lat_grid),
        ("point", {"precision": "point"}, lat_point),
    ):
        for i in range(calls):
            _, lat, lon = NAMED_PLACES[i % len(NAMED_PLACES)]
            # nudge so successive calls are distinct points
            t = time.perf_counter()
            r = client.get("/v1/score", params={"lat": lat + 0.0001 * i, "lon": lon, **params})
            bucket.append((time.perf_counter() - t) * 1000)
            assert r.status_code == 200, r.text
    for label, v in (("grid", lat_grid), ("point", lat_point)):
        v = sorted(v)
        print(
            f"\nlatency /v1/score {label}: p50 {v[len(v) // 2]:.0f} ms, p95 {v[int(len(v) * 0.95)]:.0f} ms, max {v[-1]:.0f} ms ({len(v)} calls)"
        )
    for label, extra in (("grid", {}), ("point", {"precision": "point"})):
        area = []
        for i in range(min(calls, 20)):
            _, lat, lon = NAMED_PLACES[i % len(NAMED_PLACES)]
            t = time.perf_counter()
            client.get("/v1/area", params={"lat": lat, "lon": lon, **extra})
            area.append((time.perf_counter() - t) * 1000)
        area.sort()
        p50, p95 = area[len(area) // 2], area[int(len(area) * 0.95)]
        print(f"latency /v1/area {label}: p50 {p50:.0f} ms, p95 {p95:.0f} ms")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["cells", "cross", "places"])
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--calls", type=int, default=50)
    a = ap.parse_args()
    if a.mode == "cells":
        run_cells(a.n)
    elif a.mode == "cross":
        run_cross(a.n)
    else:
        run_places(a.api, a.calls)


if __name__ == "__main__":
    sys.exit(main())
