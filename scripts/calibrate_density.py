"""Print `v2.2-density` factor scores for reference places, plus region-wide spread.

    python scripts/calibrate_density.py [--reach build/reach/reach.npz]

Reads the reach file and the local areas database (AREAS_DATABASE_URL, default the local
Docker database) to find which area each reference place falls in. Read-only.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np

from ingestion.routing.reach import LOCAL_DATABASE_URL, OUT_PATH
from scoring import density

REFERENCE_PLACES: dict[str, tuple[float, float]] = {
    "Sunnyside, Queens": (40.7445, -73.9200),
    "Upper West Side": (40.7870, -73.9750),
    "Fordham, Bronx": (40.8610, -73.8900),
    "Park Slope, Brooklyn": (40.6712, -73.9813),
    "Hoboken, NJ": (40.7440, -74.0290),
    "Downtown Stamford, CT": (41.0530, -73.5390),
    "Morristown, NJ": (40.7970, -74.4810),
    "Montclair, NJ": (40.8259, -74.2090),
    "Garden City, NY": (40.7260, -73.6350),
    "Downtown Poughkeepsie": (41.7030, -73.9280),
    "New Paltz, NY": (41.7470, -74.0860),
    "Lloyd (Highland), NY": (41.7210, -73.9610),
    "Scarsdale, NY": (41.0050, -73.7840),
    "Levittown, NY": (40.7250, -73.5140),
    "Rural Ulster County": (41.8000, -74.2500),
}

AREA_AT_SQL = """
select id from areas_slim
where st_contains(geom, st_setsrid(st_makepoint(%s, %s), 4326))
limit 1
"""


def main() -> None:
    import psycopg

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reach", type=Path, default=OUT_PATH)
    args = ap.parse_args()

    r = density.Reach.load(args.reach)
    scores = density.score(r)
    keys = list(scores)
    index = {int(a): i for i, a in enumerate(r.area_id)}
    url = os.environ.get("AREAS_DATABASE_URL", LOCAL_DATABASE_URL)
    print(f"{'place':24s} {'mode':5s} " + " ".join(f"{k[:7]:>7s}" for k in keys))
    with psycopg.connect(url) as conn:
        for name, (lat, lon) in REFERENCE_PLACES.items():
            row = conn.execute(AREA_AT_SQL, (lon, lat)).fetchone()
            i = index.get(int(row[0])) if row else None
            if i is None:
                print(f"{name:24s} (no area)")
                continue
            mode = "walk" if r.mode[i] == density.WALK else "drive"
            print(f"{name:24s} {mode:5s} " + " ".join(f"{scores[k][i]:7.0f}" for k in keys))
    print("\nRegion-wide percentiles (p10 / p50 / p90) and share of areas >= 90:")
    for k in keys:
        s = scores[k]
        p10, p50, p90 = np.percentile(s, [10, 50, 90])
        print(f"  {k:15s} {p10:5.0f} {p50:5.0f} {p90:5.0f}   {100 * (s >= 90).mean():4.1f}%")


if __name__ == "__main__":
    main()
