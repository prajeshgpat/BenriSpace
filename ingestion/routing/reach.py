"""Polygon reach: the routed inputs for density scoring, computed per road-bounded area.

    python -m ingestion.routing.pbf          # once: walk / drive networks from the extracts
    python -m ingestion.routing.reach        # origins, tallies, pair minutes, nearest minutes
    python -m ingestion.routing.reach --sync-places   # first copy production's places locally

Reads `areas_slim`, `places`, `routing_hubs` (rail) and the grid's population density from
AREAS_DATABASE_URL (the local database by default; nothing is written to any database) and
saves everything to `build/reach/reach.npz`:

  origin      each area's starting point: the population-weighted centre of the grid cells
              inside it when that lands inside the polygon, else a point on its surface
  mode        walk (0) where the population density at the origin is >= 10,000 per sq mi,
              else drive (1), as everywhere else (common.routing.CAR_DENSITY_PER_SQ_MI)
  tally       places of each TALLY_CATEGORIES category inside each polygon
  pairs       routed minutes from each area's origin to every other origin within the cap:
              walk for every area, drive for drive-mode areas
  nearest     routed minutes from each origin to the nearest place of each NEAR_CATEGORIES
              category (rail = GTFS rail stations; bus = transit stops that are not rail),
              walk and drive

These are internal scoring inputs: tallies and densities are never shown to users. Units are
miles, sq mi, mph and minutes. Needs the `routing` extra.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from common.routing import CAR_DENSITY_PER_SQ_MI, WALK_MPH
from ingestion.routing.network import MI_PER_DEG_LAT, NetworkData, to_pandana
from ingestion.routing.pbf import DEFAULT_OUT_DIR as NETWORK_DIR
from ingestion.routing.pbf import keep_connected, load_network

OUT_PATH = Path("build/reach/reach.npz")
LOCAL_DATABASE_URL = "postgresql://postgres:benri@localhost:5433/postgres"

MODES = ("walk", "drive")
# Search caps (minutes). Scoring curves end inside these, so they can be tuned without a rerun.
PAIR_CAP_MIN = {"walk": 25.0, "drive": 20.0}
NEAR_CAP_MIN = {"walk": 40.0, "drive": 30.0}
# Fastest plausible straight-line speed per mode, to pick candidate pairs before routing.
MAX_STRAIGHT_MPH = {"walk": WALK_MPH, "drive": 55.0}
# Getting from the origin to the nearest network node: on foot, or slowly by car.
ACCESS_MPH = {"walk": WALK_MPH, "drive": 15.0}
MAX_ACCESS_MI = 0.6  # an origin farther than this from any road is "off the network"
UNREACHABLE = np.float32(np.nan)

TALLY_CATEGORIES: tuple[str, ...] = (
    "restaurant", "cafe", "bar", "shopping", "grocery", "gym", "gas_station",
    "convenience_store", "park", "school",
)  # fmt: skip
NEAR_CATEGORIES: tuple[str, ...] = (
    "grocery", "gym", "gas_station", "convenience_store", "restaurant", "cafe", "bar",
    "shopping", "park", "school", "rail", "bus",
)  # fmt: skip
RAIL_MATCH_MI = 0.06  # a transit place this close to a GTFS rail station is that station

ORIGINS_SQL = """
with cells as (
    select ge.latitude::float8 as lat, ge.longitude::float8 as lon,
           coalesce(f.pop_density_per_sq_mi, 0)::float8 as pd
    from geo_entities ge join feature_store f on f.geo_entity_id = ge.id
    where length(ge.geohash) = 6
), weighted as (
    select a.id,
           sum(c.pd * c.lat) / nullif(sum(c.pd), 0) as wlat,
           sum(c.pd * c.lon) / nullif(sum(c.pd), 0) as wlon
    from areas_slim a
    join cells c on st_contains(a.geom, st_setsrid(st_makepoint(c.lon, c.lat), 4326))
    group by a.id
), surface as (
    select a.id, a.area_sq_mi::float8 as area_sq_mi, a.geom, st_pointonsurface(a.geom) as pos
    from areas_slim a
)
select s.id, s.area_sq_mi,
       case when w.wlat is not null
                 and st_contains(s.geom, st_setsrid(st_makepoint(w.wlon, w.wlat), 4326))
            then w.wlat else st_y(s.pos) end as lat,
       case when w.wlat is not null
                 and st_contains(s.geom, st_setsrid(st_makepoint(w.wlon, w.wlat), 4326))
            then w.wlon else st_x(s.pos) end as lon
from surface s left join weighted w on w.id = s.id
order by s.id
"""
CELLS_SQL = """
select ge.latitude::float8 as lat, ge.longitude::float8 as lon,
       coalesce(f.pop_density_per_sq_mi, 0)::float8 as pd
from geo_entities ge join feature_store f on f.geo_entity_id = ge.id
where length(ge.geohash) = 6
"""
TALLY_SQL = """
select a.id, p.category, count(*) as n
from places p
join areas_slim a on st_contains(a.geom, st_setsrid(st_makepoint(p.longitude, p.latitude), 4326))
where p.category = any(%s)
group by 1, 2
"""
PLACES_SQL = (
    "select category, latitude::float8 as lat, longitude::float8 as lon from places "
    "where category = any(%s)"
)
RAIL_SQL = "select latitude as lat, longitude as lon from routing_hubs where kind = 'rail'"


@dataclass
class Origins:
    area_id: np.ndarray  # int64
    area_sq_mi: np.ndarray  # float64
    lat: np.ndarray
    lon: np.ndarray
    pop_density: np.ndarray  # people per sq mi at the origin's grid cell
    mode: np.ndarray  # uint8: 0 walk, 1 drive

    def __len__(self) -> int:
        return len(self.area_id)


def to_miles_xy(lat: np.ndarray, lon: np.ndarray, ref_lat: float) -> np.ndarray:
    """Planar (x, y) in miles around ref_lat: good to well under 1 % across the region."""
    return np.column_stack(
        [lon * MI_PER_DEG_LAT * math.cos(math.radians(ref_lat)), lat * MI_PER_DEG_LAT]
    )


def load_origins(conn) -> Origins:
    from scipy.spatial import cKDTree

    with conn.cursor() as cur:
        cur.execute(ORIGINS_SQL)
        rows = cur.fetchall()
        cur.execute(CELLS_SQL)
        cells = cur.fetchall()
    lat = np.array([r["lat"] for r in rows])
    lon = np.array([r["lon"] for r in rows])
    ref = float(np.mean(lat))
    cell_xy = to_miles_xy(
        np.array([c["lat"] for c in cells]), np.array([c["lon"] for c in cells]), ref
    )
    _, nearest_cell = cKDTree(cell_xy).query(to_miles_xy(lat, lon, ref))
    density = np.array([cells[i]["pd"] for i in nearest_cell])
    return Origins(
        area_id=np.array([r["id"] for r in rows], dtype=np.int64),
        area_sq_mi=np.array([r["area_sq_mi"] or 0.0 for r in rows]),
        lat=lat,
        lon=lon,
        pop_density=density,
        mode=np.where(density >= CAR_DENSITY_PER_SQ_MI, 0, 1).astype(np.uint8),
    )


def load_tally(conn, origins: Origins) -> np.ndarray:
    """[area, category] place counts inside each polygon (uint16)."""
    index = {int(a): i for i, a in enumerate(origins.area_id)}
    tally = np.zeros((len(origins), len(TALLY_CATEGORIES)), dtype=np.uint16)
    with conn.cursor() as cur:
        cur.execute(TALLY_SQL, (list(TALLY_CATEGORIES),))
        for r in cur:
            i = index.get(int(r["id"]))
            if i is not None:
                tally[i, TALLY_CATEGORIES.index(r["category"])] = min(int(r["n"]), 65535)
    return tally


def load_points(conn) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{near category: (lat, lon)}. Transit places split into rail (GTFS stations) and bus."""
    from scipy.spatial import cKDTree

    wanted = [c for c in NEAR_CATEGORIES if c not in ("rail", "bus")] + ["transit"]
    with conn.cursor() as cur:
        cur.execute(PLACES_SQL, (wanted,))
        places = cur.fetchall()
        cur.execute(RAIL_SQL)
        rail = cur.fetchall()
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for cat in NEAR_CATEGORIES:
        if cat in ("rail", "bus"):
            continue
        pts = [(p["lat"], p["lon"]) for p in places if p["category"] == cat]
        out[cat] = (np.array([p[0] for p in pts]), np.array([p[1] for p in pts]))
    rail_lat = np.array([float(r["lat"]) for r in rail])
    rail_lon = np.array([float(r["lon"]) for r in rail])
    out["rail"] = (rail_lat, rail_lon)
    stops = [(p["lat"], p["lon"]) for p in places if p["category"] == "transit"]
    s_lat = np.array([s[0] for s in stops])
    s_lon = np.array([s[1] for s in stops])
    if len(rail_lat) and len(s_lat):
        ref = float(np.mean(rail_lat))
        d, _ = cKDTree(to_miles_xy(rail_lat, rail_lon, ref)).query(to_miles_xy(s_lat, s_lon, ref))
        bus = d > RAIL_MATCH_MI
        s_lat, s_lon = s_lat[bus], s_lon[bus]
    out["bus"] = (s_lat, s_lon)
    return out


def snap(net, lat: np.ndarray, lon: np.ndarray, mode: str):
    """(node_ids, access minutes, on_network) for points on a Pandana network."""
    import pandas as pd

    nodes = np.asarray(net.get_node_ids(pd.Series(lon), pd.Series(lat)))
    nx_ = net.nodes_df["x"].reindex(nodes).to_numpy()
    ny_ = net.nodes_df["y"].reindex(nodes).to_numpy()
    dy = (ny_ - lat) * MI_PER_DEG_LAT
    dx = (nx_ - lon) * MI_PER_DEG_LAT * np.cos(np.radians(lat))
    miles = np.hypot(dx, dy)
    return nodes, miles / ACCESS_MPH[mode] * 60.0, miles <= MAX_ACCESS_MI


def candidate_pairs(
    origins: Origins, mode: str, sources: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """(src, dst) index pairs whose straight-line distance could be travelled within the cap."""
    from scipy.spatial import cKDTree

    ref = float(np.mean(origins.lat))
    xy = to_miles_xy(origins.lat, origins.lon, ref)
    radius = PAIR_CAP_MIN[mode] / 60.0 * MAX_STRAIGHT_MPH[mode]
    tree = cKDTree(xy)
    src: list[np.ndarray] = []
    dst: list[np.ndarray] = []
    for i, hits in zip(sources, tree.query_ball_point(xy[sources], radius), strict=True):
        hits = np.asarray(hits, dtype=np.int32)
        hits = hits[hits != i]
        src.append(np.full(len(hits), i, dtype=np.int32))
        dst.append(hits)
    if not src:
        return np.empty(0, np.int32), np.empty(0, np.int32)
    return np.concatenate(src), np.concatenate(dst)


def pair_minutes(net, nodes, access, on_net, src, dst, mode: str, chunk: int = 2_000_000):
    """Routed minutes for each (src, dst) pair, NaN when unreachable or over the cap."""
    out = np.empty(len(src), dtype=np.float32)
    for a in range(0, len(src), chunk):
        s, d = src[a : a + chunk], dst[a : a + chunk]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lengths = net.shortest_path_lengths(nodes[s], nodes[d], imp_name="minutes")
        net_min = np.asarray(lengths, dtype=np.float64)
        total = net_min + access[s] + access[d]
        ok = on_net[s] & on_net[d] & (net_min < 1e6) & (total <= PAIR_CAP_MIN[mode])
        out[a : a + chunk] = np.where(ok, total, np.nan)
    return out


def nearest_minutes(net, nodes, access, on_net, points, mode: str) -> np.ndarray:
    """[origin, NEAR_CATEGORIES] routed minutes to the nearest place of each category."""
    import pandas as pd

    cap = NEAR_CAP_MIN[mode]
    out = np.full((len(nodes), len(NEAR_CATEGORIES)), np.nan, dtype=np.float32)
    for j, cat in enumerate(NEAR_CATEGORIES):
        lat, lon = points[cat]
        if not len(lat):
            continue
        net.set_pois(cat, cap, 1, pd.Series(lon), pd.Series(lat))
        res = net.nearest_pois(cap, cat, num_pois=1)
        mins = res[1].reindex(nodes).to_numpy(dtype=np.float64) + access
        out[:, j] = np.where(on_net & (mins <= cap), mins, np.nan)
    return out


PLACES_COLUMNS = ("source", "source_id", "category", "name", "brand", "latitude", "longitude")


def sync_places(source_url: str, local_url: str) -> int:
    """Replaces the local `places` table with the source database's (read-only there), so the
    reach is computed from the same places production serves. Returns rows copied."""
    import psycopg

    cols = ", ".join(PLACES_COLUMNS)
    with psycopg.connect(source_url) as src, psycopg.connect(local_url) as dst:
        src.read_only = True
        with dst.transaction(), dst.cursor() as out:
            out.execute("delete from places")
            with (
                src.cursor().copy(f"copy (select {cols} from places) to stdout") as reader,
                out.copy(f"copy places ({cols}) from stdin") as writer,
            ):
                for block in reader:
                    writer.write(block)
            out.execute("select count(*) from places")
            return int(out.fetchone()[0])


def run(conn, network_dir: Path = NETWORK_DIR, out_path: Path = OUT_PATH) -> dict:
    t0 = time.time()
    origins = load_origins(conn)
    tally = load_tally(conn, origins)
    points = load_points(conn)
    print(f"[reach] {len(origins):,} areas, inputs {time.time() - t0:.0f}s", file=sys.stderr)
    arrays: dict[str, np.ndarray] = {
        "area_id": origins.area_id,
        "area_sq_mi": origins.area_sq_mi,
        "lat": origins.lat,
        "lon": origins.lon,
        "pop_density": origins.pop_density,
        "mode": origins.mode,
        "tally": tally,
        "tally_categories": np.array(TALLY_CATEGORIES),
        "near_categories": np.array(NEAR_CATEGORIES),
    }
    summary: dict = {"areas": len(origins), "walk_areas": int((origins.mode == 0).sum())}
    for mode in MODES:
        t1 = time.time()
        data: NetworkData = keep_connected(load_network(network_dir / f"{mode}.npz"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # pandana warns per unconnected pair; NaN covers it
            net = to_pandana(data)
        print(
            f"[reach] {mode} network {data.n_nodes:,} nodes built in {time.time() - t1:.0f}s",
            file=sys.stderr,
        )
        nodes, access, on_net = snap(net, origins.lat, origins.lon, mode)
        sources = np.arange(len(origins)) if mode == "walk" else np.flatnonzero(origins.mode == 1)
        t1 = time.time()
        src, dst = candidate_pairs(origins, mode, sources)
        minutes = pair_minutes(net, nodes, access, on_net, src, dst, mode)
        keep = ~np.isnan(minutes)
        arrays[f"{mode}_src"], arrays[f"{mode}_dst"] = src[keep], dst[keep]
        arrays[f"{mode}_min"] = minutes[keep]
        print(
            f"[reach] {mode} pairs {keep.sum():,} of {len(src):,} candidates "
            f"in {time.time() - t1:.0f}s",
            file=sys.stderr,
        )
        t1 = time.time()
        arrays[f"{mode}_near"] = nearest_minutes(net, nodes, access, on_net, points, mode)
        print(f"[reach] {mode} nearest in {time.time() - t1:.0f}s", file=sys.stderr)
        summary[f"{mode}_pairs"] = int(keep.sum())
        summary[f"{mode}_off_network"] = int((~on_net).sum())
        del net
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, **arrays)
    summary["seconds"] = round(time.time() - t0)
    return summary


def main(argv: list[str] | None = None) -> None:
    import json

    import psycopg
    from psycopg.rows import dict_row

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--networks", type=Path, default=NETWORK_DIR)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument(
        "--sync-places", action="store_true", help="copy DATABASE_URL's places locally first"
    )
    args = ap.parse_args(argv)
    url = os.environ.get("AREAS_DATABASE_URL", LOCAL_DATABASE_URL)
    if args.sync_places:
        from dotenv import load_dotenv

        load_dotenv()
        copied = sync_places(os.environ["DATABASE_URL"], url)
        print(f"[reach] copied {copied:,} places from DATABASE_URL", file=sys.stderr)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.read_only = True
        print(json.dumps(run(conn, args.networks, args.out), indent=2))


if __name__ == "__main__":
    main()
