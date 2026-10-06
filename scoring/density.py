"""Density scoring per road-bounded area (`v2.2-density`): routed reach in, 0-100 factors out.

Inputs are `build/reach/reach.npz` (ingestion/routing/reach.py). Every score is on ONE absolute
scale for the whole region, so a place is never graded against its own sub-region. Densities,
tallies and minutes are internal: only the 0-100 factor scores leave this module.

Reach weight
    A neighbouring area counts by its WALKING time from this area's origin: fully up to
    REACH_FULL_MIN, falling linearly to 0 at REACH_ZERO_MIN. Density is a neighbourhood
    measure; driving neighbours would add tens of sq mi of mostly empty land and dilute every
    suburb towards zero (New Paltz: 80 restaurants per sq mi on its own, 1.3 with a 15-minute
    drive). Car access enters through proximity and the optional drive term below.

Effective density (places per sq mi)
    (own tally + sum of weight x neighbour tally) / (own sq mi + sum of weight x neighbour sq mi)
    Neighbours' area enters with the same weight as their places, so a tiny polygon cannot
    spike on one bar and a polygon next to a park is only diluted a little.

Drive to a cluster (drive-mode areas, factors with `drive_cluster`)
    A suburb near a dense cluster by car scores for it: the best neighbouring area's own
    (walkable) density score, at full value within REACH_FULL_MIN["drive"] minutes, losing
    points linearly to 0 at REACH_ZERO_MIN["drive"], and worth at most DRIVE_CREDIT so living
    in the cluster still beats driving to it. The area's score is the better of the two.

Density score  100 x log(1 + D / SOFT) / log(1 + FULL / SOFT), capped at 100: going from 2 to 5
               per sq mi counts far more than from 25 to 28.
Proximity      100 within full minutes, linear to 0 at zero minutes, to the nearest place.

Factors
    restaurant, cafe, bar, shopping   100 % density
    grocery, gym, gas & convenience   70 % proximity, 30 % density
    transit                           train station proximity; a bus stop counts at most
                                      BUS_CREDIT. No density (one neighbourhood rarely has
                                      several stations).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WALK, DRIVE = 0, 1

REACH_FULL_MIN = {"walk": 5.0, "drive": 5.0}
REACH_ZERO_MIN = {"walk": 20.0, "drive": 15.0}
DRIVE_CREDIT = 0.8
BUS_CREDIT = 0.5


@dataclass(frozen=True)
class Curve:
    full: float  # minutes at or under which the score is 100
    zero: float  # minutes at or over which it is 0

    def __call__(self, minutes: np.ndarray) -> np.ndarray:
        m = np.asarray(minutes, dtype=np.float64)
        out = np.clip((self.zero - m) / (self.zero - self.full), 0.0, 1.0)
        return np.where(np.isnan(m), 0.0, out)


@dataclass(frozen=True)
class DensityScale:
    full: float  # places per sq mi that score 100
    soft: float  # where the log curve bends; lower = early places count more

    def __call__(self, density: np.ndarray) -> np.ndarray:
        d = np.maximum(np.asarray(density, dtype=np.float64), 0.0)
        return np.minimum(100.0, 100.0 * np.log1p(d / self.soft) / np.log1p(self.full / self.soft))


@dataclass(frozen=True)
class Factor:
    key: str
    categories: tuple[str, ...]  # tally / nearest categories pooled into this factor
    density: DensityScale | None
    drive_cluster: bool = False
    proximity_weight: float = 0.0  # share of the score from proximity (rest is density)
    walk_curve: Curve | None = None
    drive_curve: Curve | None = None


# Starting values; set from the calibration run against reference places.
FACTORS: tuple[Factor, ...] = (
    Factor("restaurant", ("restaurant",), DensityScale(full=60.0, soft=4.0), drive_cluster=True),
    Factor("cafe", ("cafe",), DensityScale(full=20.0, soft=2.0), drive_cluster=True),
    Factor("bar", ("bar",), DensityScale(full=15.0, soft=1.5), drive_cluster=True),
    Factor("shopping", ("shopping",), DensityScale(full=60.0, soft=4.0), drive_cluster=True),
    Factor(
        "grocery", ("grocery",), DensityScale(full=8.0, soft=1.0), proximity_weight=0.7,
        walk_curve=Curve(5.0, 25.0), drive_curve=Curve(5.0, 20.0),
    ),
    Factor(
        "gym", ("gym",), DensityScale(full=6.0, soft=1.0), proximity_weight=0.7,
        walk_curve=Curve(7.0, 30.0), drive_curve=Curve(7.0, 25.0),
    ),
    Factor(
        "gasConvenience", ("gas_station", "convenience_store"),
        DensityScale(full=12.0, soft=1.5), proximity_weight=0.7,
        walk_curve=Curve(5.0, 20.0), drive_curve=Curve(3.0, 15.0),
    ),
)  # fmt: skip
RAIL_WALK = Curve(10.0, 30.0)
RAIL_DRIVE = Curve(5.0, 20.0)  # park-and-ride, drive-mode areas only
BUS_WALK = Curve(5.0, 15.0)


@dataclass
class Reach:
    """The arrays of reach.npz, by name."""

    area_id: np.ndarray
    area_sq_mi: np.ndarray
    mode: np.ndarray
    tally: np.ndarray
    tally_categories: tuple[str, ...]
    near_categories: tuple[str, ...]
    walk_src: np.ndarray
    walk_dst: np.ndarray
    walk_min: np.ndarray
    drive_src: np.ndarray
    drive_dst: np.ndarray
    drive_min: np.ndarray
    walk_near: np.ndarray
    drive_near: np.ndarray

    @classmethod
    def load(cls, path) -> Reach:
        with np.load(path) as z:
            kw = {k: z[k] for k in z.files if k in cls.__dataclass_fields__}
        kw["tally_categories"] = tuple(str(c) for c in kw["tally_categories"])
        kw["near_categories"] = tuple(str(c) for c in kw["near_categories"])
        return cls(**kw)


def reach_weight(minutes: np.ndarray, mode: str) -> np.ndarray:
    return Curve(REACH_FULL_MIN[mode], REACH_ZERO_MIN[mode])(minutes)


def neighbour_weights(r: Reach, mode: str = "walk") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(src, dst, weight) of each area's neighbours by walking or driving time."""
    src = getattr(r, f"{mode}_src").astype(np.int64)
    dst = getattr(r, f"{mode}_dst").astype(np.int64)
    w = reach_weight(getattr(r, f"{mode}_min"), mode)
    keep = w > 0
    return src[keep], dst[keep], w[keep]


def effective_density(r: Reach, categories: tuple[str, ...], weights) -> np.ndarray:
    """Places per sq mi over each area and its weighted neighbours."""
    src, dst, w = weights
    cols = [r.tally_categories.index(c) for c in categories]
    own = r.tally[:, cols].sum(axis=1).astype(np.float64)
    count = own + np.bincount(src, weights=w * own[dst], minlength=len(own))
    area = r.area_sq_mi + np.bincount(src, weights=w * r.area_sq_mi[dst], minlength=len(own))
    return np.where(area > 0, count / np.maximum(area, 1e-9), 0.0)


def drive_to_cluster(r: Reach, walk_scores: np.ndarray) -> np.ndarray:
    """0-100 per area: the best neighbour's walkable score, discounted by drive minutes."""
    src = r.drive_src.astype(np.int64)
    dst = r.drive_dst.astype(np.int64)
    value = walk_scores[dst] * reach_weight(r.drive_min, "drive")
    best = np.zeros(len(walk_scores))
    np.maximum.at(best, src, value)
    return DRIVE_CREDIT * best


def nearest_minutes(r: Reach, categories: tuple[str, ...], mode: str) -> np.ndarray:
    near = r.walk_near if mode == "walk" else r.drive_near
    cols = [r.near_categories.index(c) for c in categories]
    sub = near[:, cols].astype(np.float64)
    all_nan = np.isnan(sub).all(axis=1)
    out = np.full(len(sub), np.nan)
    out[~all_nan] = np.nanmin(sub[~all_nan], axis=1)
    return out


def proximity(r: Reach, categories: tuple[str, ...], walk: Curve, drive: Curve) -> np.ndarray:
    """0-1: walking everywhere; in drive-mode areas the better of walking and capped driving."""
    on_foot = walk(nearest_minutes(r, categories, "walk"))
    by_car = DRIVE_CREDIT * drive(nearest_minutes(r, categories, "drive"))
    return np.where(r.mode == DRIVE, np.maximum(on_foot, by_car), on_foot)


def transit_score(r: Reach) -> np.ndarray:
    rail = proximity(r, ("rail",), RAIL_WALK, RAIL_DRIVE)
    bus = BUS_WALK(nearest_minutes(r, ("bus",), "walk"))
    return 100.0 * np.maximum(rail, BUS_CREDIT * bus)


def score(r: Reach) -> dict[str, np.ndarray]:
    """{factor key: 0-100 per area} for the density-scored factors and transit."""
    walk_w = neighbour_weights(r, "walk")
    out: dict[str, np.ndarray] = {}
    for f in FACTORS:
        dens = f.density(effective_density(r, f.categories, walk_w)) if f.density else 0.0
        if f.drive_cluster:
            by_car = drive_to_cluster(r, dens)
            dens = np.where(r.mode == DRIVE, np.maximum(dens, by_car), dens)
        if f.proximity_weight:
            prox = 100.0 * proximity(r, f.categories, f.walk_curve, f.drive_curve)
            out[f.key] = f.proximity_weight * prox + (1 - f.proximity_weight) * dens
        else:
            out[f.key] = np.asarray(dens, dtype=np.float64)
    out["transit"] = transit_score(r)
    return out
