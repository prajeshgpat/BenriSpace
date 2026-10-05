"""Overpass source for the LOWER road classes used to subdivide big hard-road faces:
highway=tertiary|tertiary_link|unclassified|residential|living_street (no service
roads, no tunnels, no bridges: bridges would add false crossings when noded).

Tiling reuses hard_source.tile_bboxes (the same 3x3 tiles). Each tile is first
split once into quadrants (depth 1) because residential data for a whole metro tile is
far too big for the public server; a sub-tile that fails (timeout, runtime error remark,
HTTP error) is split into quadrants again, up to MAX_DEPTH. Every fetched (sub)tile is
cached gzipped; a split parent leaves a `.split` marker so re-runs do not retry it.
Requests are sequential with a pause. Nothing touches the network without allow_network.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from ingestion.areas.hard_source import (
    Bbox,
    NetworkNotAllowed,
    load_cached,
    region_bbox,
    tile_bboxes,
)

LOWER_HIGHWAYS = ("tertiary", "tertiary_link", "unclassified", "residential", "living_street")
LOWER_REGEX = "|".join(LOWER_HIGHWAYS)
TERTIARY = frozenset({"tertiary", "tertiary_link"})
QUERY_TIMEOUT_S = 240
START_DEPTH = 1
MAX_DEPTH = 4
PAUSE_S = 5.0
FAST_FAIL_S = 60.0
MAX_BUSY_TRIES = 40
BUSY_WAIT_S = 120.0


def build_query(tile: Bbox) -> str:
    s, w, n, e = tile
    return (
        f"[out:json][timeout:{QUERY_TIMEOUT_S}][maxsize:2147483648];\n"
        f'way["highway"~"^({LOWER_REGEX})$"][!"tunnel"][!"bridge"]["area"!="yes"]'
        f"({s},{w},{n},{e});\nout geom;\n"
    )


def cache_path(tile: Bbox, cache_dir: Path) -> Path:
    s, w, n, e = tile
    return Path(cache_dir) / f"areas_local_{s}_{w}_{n}_{e}.json.gz"


def quadrants(tile: Bbox) -> list[Bbox]:
    s, w, n, e = tile
    ms, mw = round((s + n) / 2, 5), round((w + e) / 2, 5)
    return [(s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)]


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(path)


def initial_tiles(bbox: Bbox | None = None, depth: int = START_DEPTH) -> list[Bbox]:
    tiles = tile_bboxes(bbox or region_bbox())
    for _ in range(depth):
        tiles = [q for t in tiles for q in quadrants(t)]
    return tiles


def _server_ok(post) -> bool:
    """Probe: a tiny query succeeds only when the server is really serving."""
    try:
        post(build_query((40.6700, -73.9800, 40.6702, -73.9798)), timeout=40)
        return True
    except Exception:  # noqa: BLE001 - any failure means not serving
        return False


def ensure_tile(
    tile: Bbox,
    cache_dir: Path,
    *,
    allow_network: bool,
    post: Callable[..., dict] | None = None,
    depth: int = START_DEPTH,
    log: Callable[[str], None] = lambda m: print(m, file=sys.stderr),
) -> list[Path]:
    """Cache files covering `tile` (fetching missing ones; splits on failure)."""
    path = cache_path(tile, cache_dir)
    marker = path.with_suffix(".split")
    if path.exists():
        return [path]
    if not marker.exists():
        if not allow_network:
            raise NetworkNotAllowed(f"tile {tile} is not cached and allow_network=False")
        if post is None:
            from common.overpass import post_overpass_query

            post = post_overpass_query
        busy_tries = 0
        while True:
            t0 = time.monotonic()
            try:
                data = post(build_query(tile), timeout=QUERY_TIMEOUT_S + 30)
                remark = str(data.get("remark", ""))
                if "error" in remark.lower() or "timed out" in remark.lower():
                    raise RuntimeError(remark)
                _write(path, data)
                log(
                    f"fetched {tile}: {len(data.get('elements', []))} ways "
                    f"{path.stat().st_size / 1e6:.1f} MB gz in {time.monotonic() - t0:.0f}s"
                )
                time.sleep(PAUSE_S)
                return [path]
            except Exception as exc:
                elapsed = time.monotonic() - t0
                if elapsed >= FAST_FAIL_S and not _server_ok(post):
                    elapsed = 0.0  # a slow failure while the server is down is not a size problem
                if elapsed < FAST_FAIL_S and busy_tries < MAX_BUSY_TRIES:
                    # the server is busy/down (fast failure), not a size problem: wait
                    busy_tries += 1
                    log(f"tile {tile}: server busy ({exc!r}); wait {BUSY_WAIT_S}s")
                    time.sleep(BUSY_WAIT_S)
                    continue
                if elapsed < FAST_FAIL_S or depth >= MAX_DEPTH:
                    raise
                log(f"tile {tile} failed after {elapsed:.0f}s ({exc!r}); splitting")
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("split")
                time.sleep(PAUSE_S)
                break
    out: list[Path] = []
    for q in quadrants(tile):
        out.extend(
            ensure_tile(
                q, cache_dir, allow_network=allow_network, post=post, depth=depth + 1, log=log
            )
        )
    return out


def ensure_region(
    cache_dir: Path,
    *,
    allow_network: bool = False,
    bbox: Bbox | None = None,
    only: Callable[[Bbox], bool] | None = None,
) -> list[Path]:
    files: list[Path] = []
    for t in initial_tiles(bbox):
        if only is not None and not only(t):
            continue
        files.extend(ensure_tile(t, cache_dir, allow_network=allow_network))
    return files


def iter_ways(paths: list[Path]) -> Iterator[dict]:
    """Ways of the cached files, one file in memory at a time, de-duplicated by id."""
    seen: set[int] = set()
    for p in paths:
        for el in load_cached(p).get("elements", []):
            if el.get("type") == "way" and el["id"] not in seen:
                seen.add(el["id"])
                yield el


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Fetch lower-class roads (Overpass, sequential).")
    ap.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    ap.add_argument("--allow-network", action="store_true")
    a = ap.parse_args()
    t0 = time.monotonic()
    fs = ensure_region(a.cache_dir, allow_network=a.allow_network)
    mb = sum(p.stat().st_size for p in fs) / 1e6
    print(f"{len(fs)} cache files, {mb:.0f} MB gz, {time.monotonic() - t0:.0f}s")
