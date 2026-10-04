"""Group blocks into neighborhoods without ever crossing a hard barrier.

Hard barriers (secondary and above, rail) are removed from the block
adjacency graph; parks and water are not street blocks at all. Connected
components of what is left are "districts". A small district is one
neighborhood; a bigger one is grown greedily region-by-region. Everything is
ordered by block id (which is spatially sorted) so reruns are identical.
"""

from __future__ import annotations

import math
from collections import defaultdict

from shapely.ops import unary_union

from ingestion.areas.blocks import BlockSet
from ingestion.areas.types import Block, Cluster, ClusterParams


def polsby_popper(geom) -> float:
    if geom.is_empty or geom.length == 0:
        return 0.0
    return 4 * math.pi * geom.area / geom.length**2


def _components(
    nodes: list[int], adj: dict[int, dict[int, tuple[float, float]]]
) -> list[list[int]]:
    seen: set[int] = set()
    comps = []
    for s in nodes:
        if s in seen:
            continue
        stack, comp = [s], []
        seen.add(s)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(sorted(comp))
    return comps


def _grow(
    district: list[int],
    geom: dict[int, object],
    adj: dict[int, dict[int, tuple[float, float]]],
    hard: dict[int, set[int]],
    p: ClusterParams,
) -> list[list[int]]:
    unassigned = set(district)
    out: list[list[int]] = []
    while unassigned:
        seed = min(
            unassigned,
            key=lambda b: (sum(1 for n in adj[b] if n in unassigned), b),
        )
        members = [seed]
        cgeom = geom[seed]
        unassigned.discard(seed)
        while len(members) < p.min_blocks and cgeom.area < p.stop_area_m2:
            best, best_key = None, None
            frontier = sorted({n for m in members for n in adj[m] if n in unassigned})
            for c in frontier:
                if hard[c].intersection(members):
                    continue  # would put a hard road inside the cluster
                if cgeom.area + geom[c].area > p.max_area_m2:
                    continue
                links = [adj[m][c] for m in members if c in adj[m]]
                shared = sum(ln for ln, _ in links)
                min_w = min(w for _, w in links)
                pen = p.tertiary_penalty if min_w >= p.tertiary_weight else 0.0
                union = unary_union([cgeom, geom[c]])
                score = (
                    p.w_compact * polsby_popper(union)
                    + p.w_shared * shared / max(geom[c].length, 1.0)
                    - pen
                )
                key = (score, -c)
                if best_key is None or key > best_key:
                    best, best_key = c, key
            if best is None:
                break
            members.append(best)
            cgeom = unary_union([cgeom, geom[best]])
            unassigned.discard(best)
        out.append(sorted(members))
    return out


def _absorb(
    groups: list[list[int]],
    geom: dict[int, object],
    adj: dict[int, dict[int, tuple[float, float]]],
    hard: dict[int, set[int]],
    below: int,
    max_blocks: int,
    max_area: float,
) -> list[list[int]]:
    groups = [list(g) for g in groups]
    while True:
        owner = {b: i for i, g in enumerate(groups) for b in g}
        order = sorted(
            (i for i, g in enumerate(groups) if len(g) < below),
            key=lambda i: (len(groups[i]), groups[i][0]),
        )
        merged = False
        for i in order:
            shared: dict[int, float] = defaultdict(float)
            for b in groups[i]:
                for n, (ln, _) in adj[b].items():
                    j = owner.get(n)
                    if j is not None and j != i:
                        shared[j] += ln
            area_i = sum(geom[b].area for b in groups[i])
            cands = [
                j
                for j in shared
                if len(groups[i]) + len(groups[j]) <= max_blocks
                and not any(hard[b] & set(groups[j]) for b in groups[i])
                and area_i + sum(geom[b].area for b in groups[j]) <= max_area
            ]
            if not cands:
                continue
            j = min(cands, key=lambda j: (-shared[j], len(groups[j]), groups[j][0]))
            groups[j] = sorted(groups[j] + groups[i])
            groups[i] = []
            merged = True
            break
        groups = [g for g in groups if g]
        if not merged:
            return groups


def cluster_blocks(bs: BlockSet, params: ClusterParams | None = None) -> list[Cluster]:
    p = params or ClusterParams()
    street = {b.id: b for b in bs.blocks if b.kind == "block"}
    geom = {i: b.geom for i, b in street.items()}
    rural = sorted(i for i, g in geom.items() if g.area > p.max_area_m2)
    adj: dict[int, dict[int, tuple[float, float]]] = {i: {} for i in street if i not in rural}
    hard: dict[int, set[int]] = {i: set() for i in adj}
    for e in bs.edges:
        if e.a not in adj or e.b not in adj:
            continue
        if e.weight >= p.hard_weight:
            if e.length >= p.min_hard_contact_m:
                hard[e.a].add(e.b)
                hard[e.b].add(e.a)
        elif e.length >= p.min_contact_m:
            adj[e.a][e.b] = adj[e.b][e.a] = (e.length, e.weight)

    final: list[tuple[list[int], int, str]] = []  # (blocks, district, kind)
    for r in rural:
        final.append(([r], -1, "rural"))
    districts = _components(sorted(adj), adj)
    for d_idx, district in enumerate(districts):
        area = sum(geom[b].area for b in district)
        has_hard_inside = any(hard[b].intersection(district) for b in district)
        if len(district) <= p.max_blocks and area < p.max_area_m2 and not has_hard_inside:
            groups = [district]
        else:
            groups = _grow(district, geom, adj, hard, p)
            groups = _absorb(
                groups, geom, adj, hard, p.soft_absorb_below, p.max_blocks, p.max_area_m2
            )
            groups = _absorb(
                groups, geom, adj, hard, p.absorb_below, p.absorb_max_blocks, p.max_area_m2
            )
        for g in groups:
            final.append((g, d_idx, "neighborhood"))

    final.sort(key=lambda t: t[0][0])
    clusters = []
    for cid, (blocks, d_idx, kind) in enumerate(final):
        g = geom[blocks[0]] if len(blocks) == 1 else unary_union([geom[b] for b in blocks])
        clusters.append(
            Cluster(
                cid,
                tuple(blocks),
                g,
                kind,
                None,
                d_idx,
                {"blocks": len(blocks), "area_m2": g.area, "pp": polsby_popper(g)},
            )
        )
    return clusters


def street_blocks(bs: BlockSet) -> list[Block]:
    return [b for b in bs.blocks if b.kind == "block"]
