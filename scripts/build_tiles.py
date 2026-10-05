"""Build the map's vector tiles: one PMTiles archive with three layers.

    cells    geohash-6 grid squares     z10-z13   property g (the geohash)
    parents  geohash-5 squares          z5-z9     property g
    areas    neighbourhood polygons     z9-z13    properties id, name, metro

The tiles carry geometry and ids only. Scores are not in them: the browser
joins `g` to the compact score file (GET /v1/map/scores) and colours cells with
feature-state, so a filter change recolours the map with no tile or API
request. Rebuild only when the grid or the area polygons change, not when
scores change.

Usage:
    python scripts/build_tiles.py --out build/tiles
    python scripts/build_tiles.py --database-url postgresql://postgres:benri@localhost:5433/postgres

Needs Docker with the image built from scripts/tiles/Dockerfile (done
automatically the first time) or a local `tippecanoe` on PATH (--local).
Read-only against the database. Upload the result to R2 (docs/ARCHITECTURE.md,
"Vector tiles").
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg

BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
IMAGE = "benri-tippecanoe"
DEFAULT_URL = "postgresql://postgres:benri@localhost:5433/postgres"
CELL_SQL = (
    "select distinct ge.geohash from geo_entities ge "
    "join scores s on s.geo_entity_id = ge.id "
    "where s.weights_version = %s and length(ge.geohash) = 6 order by 1"
)
AREA_SQL = (
    "select id, neighborhood, metro_area, st_asgeojson(geom, 5) as geometry "
    "from areas_slim order by id"
)


def geohash_bounds(geohash: str) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a geohash cell."""
    lat = [-90.0, 90.0]
    lon = [-180.0, 180.0]
    even = True
    for char in geohash:
        bits = BASE32.index(char)
        for shift in (4, 3, 2, 1, 0):
            span = lon if even else lat
            mid = (span[0] + span[1]) / 2
            span[0 if (bits >> shift) & 1 else 1] = mid
            even = not even
    return lon[0], lat[0], lon[1], lat[1]


def square(geohash: str) -> dict:
    w, s, e, n = geohash_bounds(geohash)
    ring = [[w, s], [e, s], [e, n], [w, n], [w, s]]
    return {
        "type": "Feature",
        "properties": {"g": geohash},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def write_lines(path: Path, features) -> int:
    count = 0
    with path.open("w") as handle:
        for feature in features:
            handle.write(json.dumps(feature, separators=(",", ":")) + "\n")
            count += 1
    return count


def layer_arg(name: str, path: Path, minzoom: int, maxzoom: int, container: str = "") -> str:
    spec = {
        "file": f"{container}{path.name}",
        "layer": name,
        "minzoom": minzoom,
        "maxzoom": maxzoom,
    }
    return json.dumps(spec, separators=(",", ":"))


def tippecanoe_args(files: dict[str, Path], out_name: str, container: str = "") -> list[str]:
    return [
        "-o", out_name, "--force", "--quiet",
        "--quiet",
        "--read-parallel",
        "--no-tile-size-limit", "--no-feature-limit",
        "--detect-shared-borders", "--simplification=4",
        f"-L{layer_arg('parents', files['parents'], 5, 9, container)}",
        f"-L{layer_arg('cells', files['cells'], 10, 13, container)}",
        f"-L{layer_arg('areas', files['areas'], 9, 13, container)}",
    ]  # fmt: skip


def run_tippecanoe(work: Path, files: dict[str, Path], out_name: str, local: bool) -> None:
    if local:
        command = ["tippecanoe", *tippecanoe_args(files, out_name)]
        subprocess.run(command, cwd=work, check=True)
        return
    docker = shutil.which("docker") or str(Path.home() / ".local/bin/docker")
    have = subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True, check=False)
    if have.returncode != 0:
        context = Path(__file__).parent / "tiles"
        subprocess.run([docker, "build", "-t", IMAGE, str(context)], check=True)
    command = [docker, "run", "--rm", "-v", f"{work.resolve()}:/data", IMAGE]
    subprocess.run([*command, *tippecanoe_args(files, out_name)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="build/tiles", help="output directory")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_URL))
    parser.add_argument("--weights-version", default=os.environ.get("SCORING_WEIGHTS_VERSION", ""))
    parser.add_argument("--name", default="benrispace.pmtiles")
    parser.add_argument("--local", action="store_true", help="use tippecanoe from PATH, not Docker")
    parser.add_argument("--keep-work", action="store_true", help="keep the NDJSON inputs")
    args = parser.parse_args()

    out = Path(args.out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(args.database_url, autocommit=True) as conn:
        conn.read_only = True
        version = args.weights_version
        if not version:
            row = conn.execute(
                "select weights_version from scores order by computed_at desc limit 1"
            ).fetchone()
            if row is None:
                print("no scores in the database", file=sys.stderr)
                return 1
            version = row[0]
        cells = [r[0] for r in conn.execute(CELL_SQL, (version,))]
        areas = conn.execute(AREA_SQL).fetchall()

    parents = sorted({c[:5] for c in cells})
    files = {name: work / f"{name}.ndjson" for name in ("cells", "parents", "areas")}
    n_cells = write_lines(files["cells"], (square(c) for c in cells))
    n_parents = write_lines(files["parents"], (square(p) for p in parents))
    n_areas = write_lines(
        files["areas"],
        (
            {
                "type": "Feature",
                "properties": {"id": a[0], "name": a[1] or "", "metro": a[2] or ""},
                "geometry": json.loads(a[3]),
            }
            for a in areas
        ),
    )
    print(f"weights {version}: {n_cells} cells, {n_parents} parents, {n_areas} areas")

    run_tippecanoe(work, files, args.name, args.local)
    target = work / args.name
    final = out / args.name
    shutil.move(target, final)
    if not args.keep_work:
        shutil.rmtree(work)
    print(f"wrote {final} ({final.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
