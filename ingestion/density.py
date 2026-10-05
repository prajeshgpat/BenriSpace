"""Population density per grid cell and the default travel mode (docs/SCORING.md Part B 1.1).

Sources (public, no API key; api.census.gov now rejects keyless requests):
- 2020 Census PL 94-171 redistricting files per state (population P0010001 and AREALAND of
  every block group, summary level 150):
  https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/
- TIGER/Line 2020 block-group polygons:
  https://www2.census.gov/geo/tiger/TIGER2020/BG/tl_2020_{fips}_bg.zip

density(block group) = population / land square miles. A cell's density is the average of the
block-group densities weighted by the area of each block group inside the cell's geohash
rectangle (shapely STRtree intersection). Cells touching no block group (water, outside
NY/NJ/CT, e.g. the Pennsylvania part of the NJ box) get NULL density and NULL travel mode.
travel_mode is 'drive' below 10,000 people / sq mi, else 'walk' (owner decision 2026-10-04).

Writes feature_store.pop_density_per_sq_mi and feature_store.travel_mode (migration 0012,
NOT yet applied). Needs the `ingestion` extra (shapely, pyshp).
"""

from __future__ import annotations

import io
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

import httpx

CACHE_DIR = Path("data/cache/density")
USER_AGENT = "BenriSpace-ingestion/1.0 (+https://benrispace.com)"
REQUEST_TIMEOUT_S = 300
STATES = {"36": ("New_York", "ny"), "34": ("New_Jersey", "nj"), "09": ("Connecticut", "ct")}
PL_URL = (
    "https://www2.census.gov/programs-surveys/decennial/2020/data/"
    "01-Redistricting_File--PL_94-171/{name}/{abbr}2020.pl.zip"
)
BG_URL = "https://www2.census.gov/geo/tiger/TIGER2020/BG/tl_2020_{fips}_bg.zip"

SQ_M_PER_SQ_MI = 2_589_988.110336
WALK_DENSITY_PER_SQ_MI = 10_000.0

# Pipe-delimited PL layout (0-based): geo file SUMLEV, LOGRECNO, GEOID, AREALAND; data file 1
GEO_SUMLEV, GEO_LOGRECNO, GEO_GEOID, GEO_AREALAND = 2, 7, 9, 84
DATA_LOGRECNO, DATA_TOTAL_POP = 4, 5
BLOCK_GROUP_SUMLEV = "150"


def travel_mode(density: float | None) -> str | None:
    """'walk' at or above 10,000 people / sq mi, else 'drive'; None when unknown."""
    if density is None:
        return None
    return "walk" if density >= WALK_DENSITY_PER_SQ_MI else "drive"


def block_group_density(population: int, land_sq_m: float) -> float | None:
    """People per square mile of land; None for waterless-of-land groups (ALAND 0)."""
    if land_sq_m <= 0:
        return None
    return population / (land_sq_m / SQ_M_PER_SQ_MI)


def parse_pl_block_groups(geo_text: str, data_text: str) -> dict[str, tuple[int, float]]:
    """{block-group GEOID: (population, land_sq_m)} from one state's PL geo + data-1 files."""
    groups: dict[str, tuple[str, float]] = {}
    for line in geo_text.splitlines():
        parts = line.split("|")
        if len(parts) <= GEO_AREALAND or parts[GEO_SUMLEV] != BLOCK_GROUP_SUMLEV:
            continue
        groups[parts[GEO_LOGRECNO]] = (parts[GEO_GEOID], float(parts[GEO_AREALAND] or 0))
    out: dict[str, tuple[int, float]] = {}
    for line in data_text.splitlines():
        parts = line.split("|")
        if len(parts) <= DATA_TOTAL_POP or parts[DATA_LOGRECNO] not in groups:
            continue
        geoid, land = groups[parts[DATA_LOGRECNO]]
        out[geoid] = (int(parts[DATA_TOTAL_POP]), land)
    return out


def cell_density(
    weights_and_densities: Iterable[tuple[float, float | None]],
) -> float | None:
    """Area-weighted mean density over (intersection_area, density) pairs, ignoring groups
    with no defined density. None if nothing contributes."""
    total_w = total = 0.0
    for area, density in weights_and_densities:
        if density is None or area <= 0:
            continue
        total_w += area
        total += area * density
    return total / total_w if total_w > 0 else None


def geohash_rect(geohash: str) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat) of a geohash cell."""
    import pygeohash as pgh

    lat, lon, lat_err, lon_err = pgh.decode_exactly(geohash)
    return lon - lon_err, lat - lat_err, lon + lon_err, lat + lat_err


def densities_for_cells(
    rects: list[tuple[float, float, float, float]],
    polygons: list,
    densities: list[float | None],
) -> list[float | None]:
    """Area-weighted density for each cell rectangle (shapely STRtree + exact intersection).
    Areas are computed in degrees squared; within one cell cos(lat) is a constant factor, so
    the weights are proportional to true areas."""
    import numpy as np
    import shapely
    from shapely import STRtree

    tree = STRtree(polygons)
    boxes = shapely.box(*np.array(rects, dtype=float).T)
    cell_idx, poly_idx = tree.query(boxes, predicate="intersects")
    inter = shapely.area(shapely.intersection(boxes[cell_idx], np.array(polygons)[poly_idx]))
    per_cell: dict[int, list[tuple[float, float | None]]] = {}
    for c, p, a in zip(cell_idx.tolist(), poly_idx.tolist(), inter.tolist(), strict=True):
        per_cell.setdefault(c, []).append((a, densities[p]))
    return [cell_density(per_cell.get(i, ())) for i in range(len(rects))]


# --------------------------------------------------------------------------
# Download / load (network I/O, not unit tested)
# --------------------------------------------------------------------------


def download_cached(url: str, cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / url.rsplit("/", 1)[-1]
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream(
        "GET",
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_S,
        follow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    tmp.rename(dest)
    return dest


def load_state_block_groups(fips: str) -> tuple[list, list[float | None]]:
    """(polygons, densities) for one state's block groups."""
    import shapefile  # pyshp
    from shapely.geometry import shape

    name, abbr = STATES[fips]
    with zipfile.ZipFile(download_cached(PL_URL.format(name=name, abbr=abbr))) as zf:
        geo = zf.read(f"{abbr}geo2020.pl").decode("latin-1")
        data = zf.read(f"{abbr}000012020.pl").decode("latin-1")
    pop_land = parse_pl_block_groups(geo, data)

    with zipfile.ZipFile(download_cached(BG_URL.format(fips=fips))) as zf:
        names = {n.rsplit(".", 1)[-1]: n for n in zf.namelist()}
        reader = shapefile.Reader(
            shp=io.BytesIO(zf.read(names["shp"])),
            dbf=io.BytesIO(zf.read(names["dbf"])),
            shx=io.BytesIO(zf.read(names["shx"])),
        )
        polygons, densities = [], []
        for rec, shp in zip(reader.records(), reader.shapes(), strict=True):
            geoid = rec["GEOID"]
            if geoid not in pop_land:
                continue
            pop, land = pop_land[geoid]
            polygons.append(shape(shp.__geo_interface__))
            densities.append(block_group_density(pop, land))
    return polygons, densities


def load_all_block_groups() -> tuple[list, list[float | None]]:
    polygons: list = []
    densities: list[float | None] = []
    for fips in STATES:
        p, d = load_state_block_groups(fips)
        print(f"density: state {fips}: {len(p)} block groups", file=sys.stderr)
        polygons.extend(p)
        densities.extend(d)
    return polygons, densities


def compute_for_geohashes(geohashes: list[str]) -> list[tuple[float | None, str | None]]:
    """[(pop_density_per_sq_mi, travel_mode)] aligned with the geohashes."""
    polygons, densities = load_all_block_groups()
    dens = densities_for_cells([geohash_rect(g) for g in geohashes], polygons, densities)
    return [(None if d is None else round(d, 1), travel_mode(d)) for d in dens]


UPSERT_SQL = """
    insert into feature_store (geo_entity_id, pop_density_per_sq_mi, travel_mode)
    values (%s, %s, %s)
    on conflict (geo_entity_id) do update
        set pop_density_per_sq_mi = excluded.pop_density_per_sq_mi,
            travel_mode = excluded.travel_mode
"""


def run() -> None:
    from common.db import get_connection, iter_geo_entities
    from common.ingestion_log import ingestion_job

    with get_connection() as conn, ingestion_job("population_density") as ctx:
        cells = list(iter_geo_entities(conn))
        results = compute_for_geohashes([c["geohash"] for c in cells])
        rows = [(c["id"], d, m) for c, (d, m) in zip(cells, results, strict=True)]
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
        conn.commit()
        ctx.rows_affected = len(rows)
    walk = sum(1 for _, _, m in rows if m == "walk")
    print(f"density: {len(rows)} cells ({walk} walk).", file=sys.stderr)


if __name__ == "__main__":
    run()
