"""Run the neighborhood-polygon prototype on the sample bbox (offline; no DB).

    python scripts/prototype_areas.py [--png]

Fetches Overpass once (cached under data/cache/), writes
data/prototype/{blocks,neighborhoods}.geojson + metrics.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.areas.blocks import build_blocks
from ingestion.areas.cluster import cluster_blocks
from ingestion.areas.naming import name_clusters
from ingestion.areas.osm_source import SAMPLE_BBOX, fetch_layers
from ingestion.areas.types import ClusterParams
from ingestion.areas.validate import compute_metrics, judge, render_png, write_outputs


def run(bbox=SAMPLE_BBOX, params: ClusterParams | None = None, png: bool = False) -> dict:
    t0 = time.monotonic()
    layers = fetch_layers(bbox, ROOT / "data" / "cache")
    t_fetch = time.monotonic()
    proj = layers.projector
    s, w, n, e = bbox
    x0, y0 = proj.fwd(w, s)
    x1, y1 = proj.fwd(e, n)
    bs = build_blocks(layers.roads, layers.water, layers.parks, (x0, y0, x1, y1), params)
    t_blocks = time.monotonic()
    clusters = cluster_blocks(bs, params)
    t_cluster = time.monotonic()
    naming = name_clusters(clusters, bs.road_edges, layers.places)
    metrics = compute_metrics(bs, clusters, naming, params)
    t_end = time.monotonic()
    metrics["runtime_s"] = {
        "load_parse": round(t_fetch - t0, 1),
        "blocks": round(t_blocks - t_fetch, 1),
        "cluster": round(t_cluster - t_blocks, 1),
        "name_validate": round(t_end - t_cluster, 1),
        "total_excl_png": round(t_end - t0, 1),
    }
    out = ROOT / "data" / "prototype"
    write_outputs(bs, clusters, proj, metrics, out)
    if png:
        render_png(bs, clusters, out / "preview.png")
        for key, (lon, lat) in {
            "wsp": (-73.9973, 40.7308),
            "bcp": (-74.0165, 40.7115),
            "bkh": (-73.9940, 40.6970),
        }.items():
            x, y = proj.fwd(lon, lat)
            render_png(bs, clusters, out / f"preview_{key}.png", (x - 700, y - 700, x + 700, y + 700))
    return {"metrics": metrics, "verdict": judge(metrics)}


def make_fixture(half_m: float = 300.0, center=(-73.9973, 40.7308)) -> Path:
    """Crops the cached Overpass response to a ~600 m window (for tests)."""
    import gzip

    from ingestion.areas.osm_source import Projector, cache_path

    s, w, n, e = SAMPLE_BBOX
    proj = Projector((s + n) / 2, (w + e) / 2)
    cx, cy = proj.fwd(*center)

    def inside(p) -> bool:
        if not p:
            return False
        x, y = proj.fwd(p["lon"], p["lat"])
        return abs(x - cx) <= half_m and abs(y - cy) <= half_m

    with gzip.open(cache_path(SAMPLE_BBOX, ROOT / "data" / "cache"), "rt") as f:
        data = json.load(f)

    def trim(el):
        geom = el.get("geometry") or []
        idx = [i for i, p in enumerate(geom) if inside(p)]
        if not idx:
            return None
        lo, hi = max(idx[0] - 1, 0), min(idx[-1] + 2, len(geom))
        el = dict(el, geometry=geom[lo:hi])
        if "nodes" in el:
            el["nodes"] = el["nodes"][lo:hi]
        if "bounds" in el:
            del el["bounds"]
        return el

    out = []
    for el in data["elements"]:
        if el["type"] == "node":
            if inside(el):
                out.append(el)
        elif el["type"] == "way":
            t = trim(el)
            if t:
                out.append(t)
        elif el["type"] == "relation":
            members = [m2 for m in el.get("members", []) if m.get("geometry") for m2 in [trim(m)] if m2]
            if members:
                out.append({k: v for k, v in dict(el, members=members).items() if k != "bounds"})
    dest = ROOT / "tests" / "fixtures" / "areas_sample.json"
    dest.write_text(json.dumps({"elements": out}, separators=(",", ":")))
    return dest


if __name__ == "__main__":
    if "--fixture" in sys.argv:
        d = make_fixture()
        print(d, d.stat().st_size)
        sys.exit(0)
    res = run(png="--png" in sys.argv)
    print(json.dumps(res["metrics"], indent=2, default=str))
    for k, v in res["verdict"].items():
        print(("PASS " if v else "FAIL ") + k)
