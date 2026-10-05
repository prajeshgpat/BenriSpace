"""Population density under a polygon, from feature_store.pop_density_per_sq_mi.

Cells are geohash6 rectangles; a polygon's density is the mean of the cells' density
weighted by the overlap area with each cell (cells with NULL density are ignored; a
polygon touching no cell falls back to the nearest cell centre, else 0 = sparse).
The cell table is read once, read-only, from DATABASE_URL and cached as an .npz so
builds are repeatable offline.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import shapely
from shapely.strtree import STRtree

from ingestion.areas.faces import geohash_bounds
from ingestion.areas.osm_source import Projector

CACHE = Path("data/cache/areas_density_cells.npz")


def load_cells(refresh: bool = False, path: Path = CACHE):
    """(geohashes, density) arrays; density NaN where unknown."""
    if path.exists() and not refresh:
        z = np.load(path, allow_pickle=False)
        return z["gh"].astype(str), z["d"]
    from common.db import get_connection

    with get_connection() as conn, conn.cursor() as cur:  # read-only
        cur.execute(
            "select ge.geohash, fs.pop_density_per_sq_mi as d from geo_entities ge "
            "join feature_store fs on fs.geo_entity_id = ge.id"
        )
        rows = cur.fetchall()
    gh = np.array([r["geohash"] for r in rows])
    d = np.array([np.nan if r["d"] is None else float(r["d"]) for r in rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, gh=gh, d=d)
    return gh, d


class DensityField:
    def __init__(self, geohashes, density, proj: Projector):
        boxes, ctr = [], []
        for g in geohashes:
            a, b, lo, hi = geohash_bounds(str(g))
            (x0, y0), (x1, y1) = proj.fwd(lo, a), proj.fwd(hi, b)
            boxes.append(shapely.box(x0, y0, x1, y1))
            ctr.append(((x0 + x1) / 2, (y0 + y1) / 2))
        self.boxes = np.array(boxes, dtype=object)
        self.density = np.asarray(density, dtype=float)
        self.ctr = np.array(ctr)
        self.tree = STRtree(self.boxes)
        self.known = ~np.isnan(self.density)
        self.proj = proj

    def of_many(self, polys) -> np.ndarray:
        """Density (people / sq mi) of each polygon (projector metres)."""
        polys = np.array(list(polys), dtype=object)
        out = np.zeros(len(polys))
        if not len(polys):
            return out
        pi, bi = self.tree.query(polys, predicate="intersects")
        ok = self.known[bi]
        pi, bi = pi[ok], bi[ok]
        if len(pi):
            ov = shapely.area(shapely.intersection(polys[pi], self.boxes[bi]))
            num = np.bincount(pi, weights=ov * self.density[bi], minlength=len(polys))
            den = np.bincount(pi, weights=ov, minlength=len(polys))
            has = den > 0
            out[has] = num[has] / den[has]
        else:
            has = np.zeros(len(polys), dtype=bool)
        miss = np.flatnonzero(~has)
        if len(miss) and self.known.any():
            k = np.flatnonzero(self.known)
            pts = shapely.get_coordinates(shapely.point_on_surface(polys[miss]))
            # nearest known cell centre, only when it is close (< 1.5 km)
            for m, (x, y) in zip(miss, pts, strict=True):
                d2 = (self.ctr[k, 0] - x) ** 2 + (self.ctr[k, 1] - y) ** 2
                j = int(np.argmin(d2))
                out[m] = self.density[k[j]] if d2[j] < 1500.0**2 else 0.0
        return out
