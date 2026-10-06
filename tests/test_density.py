"""v2.2 density scoring on hand-made reach data (no network, no database)."""

import numpy as np
import pytest

from ingestion.routing.reach import NEAR_CATEGORIES, TALLY_CATEGORIES
from scoring import density


def make_reach(tallies, sq_mi, mode, walk_pairs=(), drive_pairs=(), walk_near=None):
    n = len(sq_mi)
    tally = np.zeros((n, len(TALLY_CATEGORIES)), dtype=np.uint16)
    for i, row in enumerate(tallies):
        for cat, count in row.items():
            tally[i, TALLY_CATEGORIES.index(cat)] = count

    def pairs(items):
        items = list(items)
        return (
            np.array([p[0] for p in items], dtype=np.int32),
            np.array([p[1] for p in items], dtype=np.int32),
            np.array([p[2] for p in items], dtype=np.float32),
        )

    ws, wd, wm = pairs(walk_pairs)
    ds, dd, dm = pairs(drive_pairs)
    near = np.full((n, len(NEAR_CATEGORIES)), np.nan, dtype=np.float32)
    for (i, cat), minutes in (walk_near or {}).items():
        near[i, NEAR_CATEGORIES.index(cat)] = minutes
    return density.Reach(
        area_id=np.arange(n),
        area_sq_mi=np.asarray(sq_mi, dtype=np.float64),
        mode=np.asarray(mode, dtype=np.uint8),
        tally=tally,
        tally_categories=TALLY_CATEGORIES,
        near_categories=NEAR_CATEGORIES,
        walk_src=ws, walk_dst=wd, walk_min=wm,
        drive_src=ds, drive_dst=dd, drive_min=dm,
        walk_near=near,
        drive_near=np.full_like(near, np.nan),
    )  # fmt: skip


def test_more_bars_per_sq_mi_scores_higher_whatever_the_polygon_size():
    r = make_reach(
        [{"bar": 5}, {"bar": 2}, {"bar": 1}],
        sq_mi=[1.0, 1.0, 0.1],  # the third is a tiny polygon: 10 bars per sq mi on its own
        mode=[1, 1, 0],
    )
    bar = density.score(r)["bar"]
    assert bar[0] > bar[1]
    assert bar[2] > bar[0]  # density, not raw count


def test_neighbours_count_less_the_further_they_are():
    near = make_reach(
        [{}, {"restaurant": 20}], sq_mi=[0.5, 0.5], mode=[0, 0], walk_pairs=[(0, 1, 4.0)]
    )
    far = make_reach(
        [{}, {"restaurant": 20}], sq_mi=[0.5, 0.5], mode=[0, 0], walk_pairs=[(0, 1, 15.0)]
    )
    out_of_reach = make_reach(
        [{}, {"restaurant": 20}], sq_mi=[0.5, 0.5], mode=[0, 0], walk_pairs=[(0, 1, 22.0)]
    )
    a, b, c = (density.score(x)["restaurant"][0] for x in (near, far, out_of_reach))
    assert a > b > c == 0


def test_a_suburb_scores_for_a_dense_cluster_a_short_drive_away():
    def suburb(minutes):
        # Area 0: a suburb with no restaurants; area 1: a dense cluster `minutes` away by car.
        return make_reach(
            [{}, {"restaurant": 30}], [0.6, 0.3], [1, 0], drive_pairs=[(0, 1, minutes)]
        )

    cluster = density.score(suburb(4.0))["restaurant"][1]
    near, mid, far = (density.score(suburb(m))["restaurant"][0] for m in (4.0, 10.0, 16.0))
    assert near == pytest.approx(density.DRIVE_CREDIT * cluster)  # full credit within 5 min
    assert near > mid > far == 0
    walkable = make_reach([{}, {"restaurant": 30}], [0.6, 0.3], [0, 0])
    assert density.score(walkable)["restaurant"][0] == 0  # walk-mode areas get no drive credit


def test_transit_values_a_train_station_over_a_bus_stop():
    r = make_reach(
        [{}, {}],
        [0.5, 0.5],
        [0, 0],
        walk_near={(0, "rail"): 8.0, (1, "bus"): 2.0},
    )
    transit = density.score(r)["transit"]
    assert transit[0] == pytest.approx(100.0)
    assert transit[1] == pytest.approx(100.0 * density.BUS_CREDIT)


def test_curve_and_scale_shapes():
    curve = density.Curve(5.0, 20.0)
    assert list(curve(np.array([0.0, 5.0, 12.5, 20.0, np.nan]))) == [1.0, 1.0, 0.5, 0.0, 0.0]
    scale = density.DensityScale(full=15.0, soft=1.5)
    low, mid, high = scale(np.array([2.0, 5.0, 40.0]))
    assert 0 < low < mid < high == 100.0
    assert (mid - low) > (scale(np.array([28.0]))[0] - scale(np.array([25.0]))[0])
