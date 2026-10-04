"""Internal quality metrics + GeoJSON export + preview for the area prototype."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from shapely.geometry import mapping
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from ingestion.areas.blocks import BlockSet
from ingestion.areas.types import Cluster, ClusterParams


def compute_metrics(
    bs: BlockSet, clusters: list[Cluster], naming: dict, params: ClusterParams | None = None
) -> dict:
    p = params or ClusterParams()
    nb = [c for c in clusters if c.kind == "neighborhood"]
    sizes = [c.stats["blocks"] for c in nb]
    hist: dict[str, int] = {}
    for s in sizes:
        k = str(s) if s < 15 else "15+"
        hist[k] = hist.get(k, 0) + 1
    pps = [c.stats["pp"] for c in nb]

    hard = [e for e in bs.road_edges if e.weight >= p.hard_weight and not e.bridge]
    htree = STRtree([e.geom for e in hard])
    crossing = 0
    for c in clusters:
        if c.kind != "neighborhood":
            continue
        inner = c.geom.buffer(-2.0)
        if not inner.is_empty and len(htree.query(inner, predicate="intersects")) > 0:
            crossing += 1

    street = [b for b in bs.blocks if b.kind == "block"]
    street_union = unary_union([b.geom for b in street])
    cluster_union = unary_union([c.geom for c in clusters])
    ctree = STRtree([c.geom for c in clusters])
    overlap = 0.0
    for i, c in enumerate(clusters):
        for j in ctree.query(c.geom, predicate="intersects"):
            if j > i:
                overlap += c.geom.intersection(clusters[j].geom).area
    covered = sorted(b for c in clusters for b in c.block_ids)
    in_range = sum(1 for s in sizes if 5 <= s <= 10)
    return {
        "faces": bs.stats,
        "block_count": len(street),
        "park_count": sum(b.kind == "park" for b in bs.blocks),
        "cluster_count": len(clusters),
        "neighborhood_count": len(nb),
        "rural_count": len(clusters) - len(nb),
        "blocks_per_cluster_hist": dict(
            sorted(hist.items(), key=lambda kv: int(kv[0].rstrip("+")))
        ),
        "pct_clusters_5_to_10_blocks": 100.0 * in_range / max(len(nb), 1),
        "median_polsby_popper": statistics.median(pps) if pps else 0.0,
        "clusters_crossing_hard_barrier": crossing,
        "overlap_area_m2": overlap,
        "gap_area_m2": street_union.difference(cluster_union).area,
        "excess_area_m2": cluster_union.difference(street_union).area,
        "every_block_assigned_once": covered == sorted(b.id for b in street),
        "empty_names": naming["empty_names"],
        "duplicate_name_rate_initial_pct": 100 * naming["duplicate_rate_initial"],
        "duplicate_name_rate_after_third_street_pct": 100 * naming["duplicate_rate_final"],
        "median_cluster_area_m2": statistics.median([c.area for c in nb]) if nb else 0,
    }


def judge(m: dict) -> dict[str, bool]:
    return {
        ">=80% clusters with 5-10 blocks": m["pct_clusters_5_to_10_blocks"] >= 80,
        "0 clusters crossing hard barriers": m["clusters_crossing_hard_barrier"] == 0,
        "median Polsby-Popper >= 0.35": m["median_polsby_popper"] >= 0.35,
        "names never empty": m["empty_names"] == 0,
        "<=2% duplicate names (initial)": m["duplicate_name_rate_initial_pct"] <= 2,
        "<=2% duplicate names (after 3rd street)": m["duplicate_name_rate_after_third_street_pct"]
        <= 2,
    }


def to_geojson(items, projector, props_fn) -> dict:
    def inv(x, y, z=None):
        return projector.inv(x, y)

    feats = []
    for it in items:
        g = transform(inv, it.geom.simplify(0.3))
        feats.append({"type": "Feature", "geometry": mapping(g), "properties": props_fn(it)})
    return {"type": "FeatureCollection", "features": feats}


def write_outputs(
    bs: BlockSet, clusters: list[Cluster], projector, metrics: dict, out: Path
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cluster_of = {b: c.id for c in clusters for b in c.block_ids}
    blocks = to_geojson(
        bs.blocks,
        projector,
        lambda b: {
            "id": b.id,
            "kind": b.kind,
            "area_m2": round(b.area),
            "cluster": cluster_of.get(b.id),
        },
    )
    hoods = to_geojson(
        clusters,
        projector,
        lambda c: {
            "id": c.id,
            "kind": c.kind,
            "title": c.name.title,
            "subtitle": c.name.subtitle,
            "streets": list(c.name.streets),
            "blocks": c.stats["blocks"],
            "area_m2": round(c.area),
            "polsby_popper": round(c.stats["pp"], 3),
        },
    )
    (out / "blocks.geojson").write_text(json.dumps(blocks))
    (out / "neighborhoods.geojson").write_text(json.dumps(hoods))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))


def render_png(bs: BlockSet, clusters: list[Cluster], path: Path, view=None, label=True) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath

    def patch(geom, **kw):
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        verts, codes = [], []
        for pg in polys:
            for ring in [pg.exterior, *pg.interiors]:
                xy = list(ring.coords)
                verts += xy
                codes += [MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 2) + [MPath.CLOSEPOLY]
        return PathPatch(MPath(verts, codes), **kw)

    fig, ax = plt.subplots(figsize=(16, 16), dpi=110)
    cmap = plt.get_cmap("tab20")
    for c in clusters:
        ax.add_patch(patch(c.geom, fc=cmap(c.id % 20), ec="black", lw=1.6, alpha=0.5))
    for b in bs.blocks:
        if b.kind == "block":
            ax.add_patch(patch(b.geom, fc="none", ec="#555555", lw=0.4))
        elif b.kind == "park":
            ax.add_patch(patch(b.geom, fc="#1a9850", ec="#0b5d2a", lw=0.8, alpha=0.8))
    if label and view is not None:
        for c in clusters:
            x, y = c.geom.representative_point().coords[0]
            if view[0] <= x <= view[2] and view[1] <= y <= view[3]:
                ax.text(x, y, f"{c.name.title}\n[{c.stats['blocks']}]", fontsize=7, ha="center")
    for e in bs.road_edges:
        if e.weight >= 3.0:
            xs, ys = e.geom.xy
            ax.plot(xs, ys, color="red", lw=0.8)
    ax.set_aspect("equal")
    if view:
        ax.set_xlim(view[0], view[2])
        ax.set_ylim(view[1], view[3])
    else:
        ax.autoscale()
    ax.axis("off")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
