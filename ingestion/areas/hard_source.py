"""Overpass source for the AREAS build: secondary-and-above highways plus
natural=coastline, fetched in a handful of tiles over the covered metro area
and cached gzipped on disk.

NETWORK GUARD: every `fetch_*` function refuses to touch the network unless
the caller passes allow_network=True (the CLI needs an explicit
--allow-network). A tile that is already cached is never re-fetched.

Rails are not walls in v1: `include_rail` (default False) adds railway=rail
to both the query and the parser for experiments.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterable
from pathlib import Path

from shapely.geometry import LineString

from common.coverage import BOUNDING_BOXES
from ingestion.areas.osm_source import Projector
from ingestion.areas.types import RoadWay
from ingestion.roads import MAJOR_CLASS_WEIGHT_THRESHOLD, ROAD_CLASS_WEIGHTS

Bbox = tuple[float, float, float, float]  # south, west, north, east

HARD_HIGHWAYS: frozenset[str] = frozenset(
    h for h, w in ROAD_CLASS_WEIGHTS.items() if w >= MAJOR_CLASS_WEIGHT_THRESHOLD
)
HARD_HIGHWAY_REGEX = "|".join(sorted(HARD_HIGHWAYS))

MARGIN_DEG = 0.05
TILE_QUERY_TIMEOUT_S = 300


class NetworkNotAllowed(RuntimeError):
    """Raised when a fetch would hit the network without allow_network=True."""


def region_bbox(margin: float = MARGIN_DEG) -> Bbox:
    """(south, west, north, east): union of the covered boxes plus a margin."""
    south = min(b[1] for b in BOUNDING_BOXES) - margin
    north = max(b[2] for b in BOUNDING_BOXES) + margin
    west = min(b[3] for b in BOUNDING_BOXES) - margin
    east = max(b[4] for b in BOUNDING_BOXES) + margin
    return (round(south, 4), round(west, 4), round(north, 4), round(east, 4))


def tile_bboxes(bbox: Bbox, rows: int = 3, cols: int = 3) -> list[Bbox]:
    """Splits bbox into rows x cols tiles (6-12 tiles for the metro region),
    ordered south-to-north, west-to-east. Tiles are adjacent, not overlapping;
    ways crossing a boundary come back in both tiles and are de-duplicated."""
    s, w, n, e = bbox
    out: list[Bbox] = []
    for r in range(rows):
        for c in range(cols):
            out.append(
                (
                    round(s + (n - s) * r / rows, 4),
                    round(w + (e - w) * c / cols, 4),
                    round(s + (n - s) * (r + 1) / rows, 4),
                    round(w + (e - w) * (c + 1) / cols, 4),
                )
            )
    return out


def build_tile_query(tile: Bbox, include_rail: bool = False) -> str:
    s, w, n, e = tile
    b = f"({s},{w},{n},{e})"
    rail = f'\n  way["railway"="rail"]{b};' if include_rail else ""
    return f"""[out:json][timeout:{TILE_QUERY_TIMEOUT_S}];
(
  way["highway"~"^({HARD_HIGHWAY_REGEX})$"]{b};
  way["natural"="coastline"]{b};{rail}
);
out geom;
"""


def tile_cache_path(tile: Bbox, cache_dir: Path, include_rail: bool = False) -> Path:
    s, w, n, e = tile
    tag = "_rail" if include_rail else ""
    return Path(cache_dir) / f"areas_hard{tag}_{s}_{w}_{n}_{e}.json.gz"


def load_cached(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _write_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(path)


def fetch_tile(
    tile: Bbox,
    cache_dir: Path,
    *,
    allow_network: bool = False,
    include_rail: bool = False,
    post: Callable[..., dict] | None = None,
) -> dict:
    """Raw Overpass JSON for one tile: from the gz cache if present, else one
    Overpass request (only with allow_network=True). `post(query, timeout=)`
    is injectable so tests can mock the HTTP layer."""
    path = tile_cache_path(tile, cache_dir, include_rail)
    if path.exists():
        return load_cached(path)
    if not allow_network:
        raise NetworkNotAllowed(f"tile {tile} is not cached and allow_network=False")
    if post is None:
        from common.overpass import post_overpass_query

        post = post_overpass_query
    data = post(build_tile_query(tile, include_rail), timeout=TILE_QUERY_TIMEOUT_S)
    _write_cache(path, data)
    return data


def fetch_region(
    bbox: Bbox,
    cache_dir: Path,
    *,
    allow_network: bool = False,
    include_rail: bool = False,
    post: Callable[..., dict] | None = None,
    rows: int = 3,
    cols: int = 3,
) -> dict:
    """All tiles of bbox merged into one Overpass-shaped dict."""
    parts = [
        fetch_tile(t, cache_dir, allow_network=allow_network, include_rail=include_rail, post=post)
        for t in tile_bboxes(bbox, rows, cols)
    ]
    return merge_elements(parts)


def merge_elements(parts: Iterable[dict]) -> dict:
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    for d in parts:
        for el in d.get("elements", []):
            key = (el.get("type", ""), el.get("id", -1))
            if key in seen:
                continue
            seen.add(key)
            out.append(el)
    out.sort(key=lambda el: (el.get("type", ""), el.get("id", 0)))
    return {"elements": out}


def parse_hard(
    data: dict, projector: Projector, include_rail: bool = False
) -> tuple[list[RoadWay], list[list[tuple[float, float]]]]:
    """(roads, coastlines) in projector meters. Roads: secondary-and-above
    non-tunnel ways with node ids (for topological junctions). Coastlines keep
    OSM direction (land on the left)."""
    roads: list[RoadWay] = []
    coast: list[tuple[int, list[tuple[float, float]]]] = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        pts = [projector.fwd(p["lon"], p["lat"]) for p in (el.get("geometry") or []) if p]
        if len(pts) < 2:
            continue
        hw = tags.get("highway")
        is_rail = include_rail and tags.get("railway") == "rail" and not tags.get("service")
        if hw in HARD_HIGHWAYS or is_rail:
            tunnel = tags.get("tunnel")
            if (tunnel and tunnel != "no") or tags.get("area") == "yes":
                continue
            nodes = tuple(el.get("nodes") or [])
            if len(nodes) != len(pts):
                continue
            roads.append(
                RoadWay(
                    id=el["id"],
                    highway=hw or "rail",
                    name=tags.get("name"),
                    nodes=nodes,
                    coords=tuple(pts),
                    bridge=bool(tags.get("bridge") and tags.get("bridge") != "no"),
                )
            )
        elif tags.get("natural") == "coastline":
            coast.append((el["id"], pts))
    roads.sort(key=lambda r: r.id)
    coast.sort(key=lambda c: c[0])
    return roads, [c for _, c in coast]


def street_points(
    data: dict, projector: Projector, spacing_m: float = 100.0
) -> list[tuple[float, float]]:
    """Validation helper: points (meters) every ~spacing_m along non-hard,
    non-bridge, non-tunnel streets. They are on land by construction."""
    out: list[tuple[float, float]] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        hw = tags.get("highway")
        if el.get("type") != "way" or not hw or hw in HARD_HIGHWAYS:
            continue
        if hw not in ROAD_CLASS_WEIGHTS or tags.get("area") == "yes":
            continue
        if (tags.get("tunnel") not in (None, "no")) or (tags.get("bridge") not in (None, "no")):
            continue
        pts = [projector.fwd(p["lon"], p["lat"]) for p in (el.get("geometry") or []) if p]
        if len(pts) < 2:
            continue
        line = LineString(pts)
        d = spacing_m / 2
        while d < line.length:
            q = line.interpolate(d)
            out.append((q.x, q.y))
            d += spacing_m
    return out
