"""PNGs of 2x2 mile windows: areas_slim polygons (AREAS_DATABASE_URL) over the cached OSM
roads (hard = thick, tertiary = medium, residential = thin). Output: data/areas/hier_<name>.png

  AREAS_DATABASE_URL=postgresql://postgres:benri@localhost:5433/postgres \\
    .venv/bin/python scripts/render_areas.py
"""

import glob
import gzip
import json
import math
import os
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import psycopg
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MPath

WINDOWS = {
    "park_slope": (40.6710, -73.9777),
    "jersey_city": (40.7178, -74.0431),
    "montclair": (40.8259, -74.2090),
    "huntington": (40.8680, -73.4250),
}
HALF_MI = 1.0


def tile_files(pattern: str, bbox) -> list[str]:
    s, w, n, e = bbox
    out = []
    for f in glob.glob(f"data/cache/{pattern}"):
        m = re.search(r"_(-?[\d.]+)_(-?[\d.]+)_(-?[\d.]+)_(-?[\d.]+)\.json\.gz$", f)
        if not m:
            continue
        ts, tw, tn, te = map(float, m.groups())
        if ts < n and tn > s and tw < e and te > w:
            out.append(f)
    return out


def roads_in(bbox):
    s, w, n, e = bbox
    out = []
    extra = os.environ.get("RENDER_EXTRA_ROADS")  # an Overpass json.gz with all highways
    files = [extra] if extra else []
    for pat in ("areas_hard_[0-9]*", "areas_local_*"):
        files += tile_files(pat + ".json.gz", bbox)
    for f in files:
        if True:
            for el in json.load(gzip.open(f, "rt")).get("elements", []):
                hw = (el.get("tags") or {}).get("highway")
                g = el.get("geometry")
                if el.get("type") != "way" or not hw or not g:
                    continue
                if any(s <= p["lat"] <= n and w <= p["lon"] <= e for p in g if p):
                    out.append((hw, [(p["lon"], p["lat"]) for p in g if p]))
    return out


def polys_in(conn, bbox):
    s, w, n, e = bbox
    cur = conn.execute(
        "select id, area_sq_mi, st_asgeojson(geom, 6) from areas_slim "
        "where geom && st_makeenvelope(%s,%s,%s,%s,4326)",
        (w, s, e, n),
    )
    return [(i, a, json.loads(g)) for i, a, g in cur]


def main(argv: list[str] | None = None) -> None:
    import sys

    windows = dict(WINDOWS)
    for a in argv if argv is not None else sys.argv[1:]:  # name:lat,lon
        n, c = a.split(":")
        windows[n] = tuple(float(x) for x in c.split(","))
        if len(sys.argv) > 1:
            windows = {n: windows[n]}
    url = os.environ["AREAS_DATABASE_URL"]
    Path("data/areas").mkdir(parents=True, exist_ok=True)
    cmap = plt.get_cmap("tab20")
    with psycopg.connect(url) as conn:
        for name, (lat, lon) in windows.items():
            dlat = HALF_MI / 69.0
            dlon = HALF_MI / (69.17 * math.cos(math.radians(lat)))
            bbox = (lat - dlat, lon - dlon, lat + dlat, lon + dlon)
            fig, ax = plt.subplots(figsize=(10, 10), dpi=110)
            areas = polys_in(conn, bbox)
            for i, a, g in areas:
                for poly in g["coordinates"]:
                    verts, codes = [], []
                    for ring in poly:
                        verts += ring
                        codes += (
                            [MPath.MOVETO] + [MPath.LINETO] * (len(ring) - 2) + [MPath.CLOSEPOLY]
                        )
                    ax.add_patch(
                        PathPatch(MPath(verts, codes), fc=cmap(i % 20), alpha=0.45, ec="none")
                    )
                    ax.add_patch(PathPatch(MPath(verts, codes), fc="none", ec="black", lw=1.4))
                c = poly[0][0]
                ax.text(c[0], c[1], f"{a:.2f}", fontsize=6, clip_on=True)
            style = {"residential": (0.3, "#666"), "unclassified": (0.3, "#666"),
                     "living_street": (0.3, "#666"), "tertiary": (0.9, "#c60"),
                     "tertiary_link": (0.9, "#c60")}  # fmt: skip
            for hw, pts in roads_in(bbox):
                lw, col = style.get(hw, (1.8, "#b00") if hw not in ("service",) else (0.2, "#aaa"))
                ax.plot(*zip(*pts, strict=True), lw=lw, color=col, zorder=3)
            ax.set_xlim(bbox[1], bbox[3])
            ax.set_ylim(bbox[0], bbox[2])
            ax.set_aspect(1 / math.cos(math.radians(lat)))
            ax.set_title(f"{name}: {len(areas)} areas (labels: sq mi)")
            out = f"data/areas/hier_{name}.png"
            fig.savefig(out)
            plt.close(fig)
            print(out, len(areas))


if __name__ == "__main__":
    main()
