"""Fast exact nearest / within-radius queries for ingestion (scipy cKDTree + numpy).

Replaces the pure-Python bucket scans. Candidates come from a cKDTree built on an
equirectangular projection (x = lon * cos(lat0) * R, y = lat * R); every returned candidate
is then re-checked with the exact haversine formula, so results equal brute force.

Why the projection cannot lose a point: projected distance differs from the true distance by
a factor between a = min(1, cos(lat0)/cos(lat)) and b = max(1, cos(lat0)/cos(lat)) over the
latitudes involved. Searching the tree with radius r*b therefore contains every point whose
true distance is <= r, and the k-th projected neighbour at dp implies the true k nearest all
lie within projected dp*b/a. Needs the `ingestion` extra (scipy, numpy); NOT in the Lambda
bundle.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree

from common.geo import EARTH_RADIUS_M

_LAT_PAD_DEG = 0.5  # query cells sit near their points; pad the latitude span for safety
_EPS = 1e-9


def haversine_m_np(lat1, lon1, lat2, lon2):
    """Vectorised twin of common.geo.haversine_m (same formula, same constants)."""
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    d_phi = np.radians(lat2 - lat1)
    d_lambda = np.radians(lon2 - lon1)
    a = np.sin(d_phi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


class PointIndex:
    """Immutable index over (lat, lon) points."""

    def __init__(self, lats, lons):
        self.lats = np.asarray(lats, dtype=float)
        self.lons = np.asarray(lons, dtype=float)
        self.n = len(self.lats)
        if self.n == 0:
            self.lat0 = 0.0
            self.cos0 = 1.0
            self.tree = None
            self.a = self.b = 1.0
            return
        self.lat0 = float(self.lats.mean())
        self.cos0 = math.cos(math.radians(self.lat0))
        lo = max(0.0, float(np.abs(self.lats).min()) - _LAT_PAD_DEG)
        hi = min(89.0, float(np.abs(self.lats).max()) + _LAT_PAD_DEG)
        ratios = (self.cos0 / math.cos(math.radians(lo)), self.cos0 / math.cos(math.radians(hi)))
        self.a = min(1.0, *ratios)
        self.b = max(1.0, *ratios)
        self.tree = cKDTree(self._project(self.lats, self.lons))

    def _project(self, lats, lons):
        return np.column_stack(
            (
                np.asarray(lons, dtype=float) * self.cos0 * math.radians(1) * EARTH_RADIUS_M,
                np.asarray(lats, dtype=float) * math.radians(1) * EARTH_RADIUS_M,
            )
        )

    def pairs(self, clats, clons, radius_m: float, k: int = 1):
        """Exact candidate pairs, sorted by (cell, distance).

        Returns (cell_idx, point_idx, dist_m) containing every point within radius_m of a cell
        and its true k nearest points (possibly a few extra). Empty arrays if no points."""
        clats = np.asarray(clats, dtype=float)
        clons = np.asarray(clons, dtype=float)
        if self.n == 0 or len(clats) == 0:
            e = np.empty(0, dtype=np.int64)
            return e, e, np.empty(0)
        q = self._project(clats, clons)
        k = max(1, min(k, self.n))
        radii = np.full(len(clats), radius_m * self.b * (1 + _EPS))
        if k == 1:
            dk, _ = self.tree.query(q, k=1)
        else:
            dk = self.tree.query(q, k=k)[0][:, -1]
        radii = np.maximum(radii, dk * (self.b / self.a) * (1 + _EPS) + 1e-6)
        lists = self.tree.query_ball_point(q, radii, return_sorted=False)
        lens = np.fromiter((len(x) for x in lists), dtype=np.int64, count=len(lists))
        ci = np.repeat(np.arange(len(clats)), lens)
        pi = (
            np.fromiter((j for x in lists for j in x), dtype=np.int64, count=int(lens.sum()))
            if lens.sum()
            else np.empty(0, dtype=np.int64)
        )
        d = haversine_m_np(clats[ci], clons[ci], self.lats[pi], self.lons[pi])
        order = np.lexsort((d, ci))
        return ci[order], pi[order], d[order]

    def candidates(self, clats, clons, radii_m):
        """(cell_idx, point_idx) for every point within each cell's own radius (a superset:
        the caller re-checks exact distances). radii_m is one value per cell."""
        clats = np.asarray(clats, dtype=float)
        clons = np.asarray(clons, dtype=float)
        if self.n == 0 or len(clats) == 0:
            e = np.empty(0, dtype=np.int64)
            return e, e
        radii = np.asarray(radii_m, dtype=float) * self.b * (1 + _EPS) + 1e-6
        lists = self.tree.query_ball_point(self._project(clats, clons), radii, return_sorted=False)
        lens = np.fromiter((len(x) for x in lists), dtype=np.int64, count=len(lists))
        ci = np.repeat(np.arange(len(clats)), lens)
        pi = np.fromiter((j for x in lists for j in x), dtype=np.int64, count=int(lens.sum()))
        return ci, pi

    def nearest_distance(self, clats, clons):
        """True (haversine) distance in metres from each cell to its nearest indexed point,
        inf when the index is empty."""
        clats = np.asarray(clats, dtype=float)
        clons = np.asarray(clons, dtype=float)
        if self.n == 0:
            return np.full(len(clats), np.inf)
        _, idx = self.tree.query(self._project(clats, clons), k=1)
        return haversine_m_np(clats, clons, self.lats[idx], self.lons[idx])

    def nearest_and_count(self, clats, clons, radius_m: float):
        """Per cell: (count of points with d <= radius_m, nearest distance or NaN)."""
        n = len(np.asarray(clats))
        counts = np.zeros(n, dtype=np.int64)
        nearest = np.full(n, np.nan)
        ci, _, d = self.pairs(clats, clons, radius_m, k=1)
        if len(ci) == 0:
            return counts, nearest
        first = np.r_[True, ci[1:] != ci[:-1]]
        nearest[ci[first]] = d[first]
        within = d <= radius_m
        counts += np.bincount(ci[within], minlength=n)
        return counts, nearest


def split_by_cell(ci, n_cells: int):
    """Slice boundaries for the (cell-sorted) pair arrays: cell i is [bounds[i]:bounds[i+1]]."""
    return np.searchsorted(ci, np.arange(n_cells + 1))
