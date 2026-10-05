"""scoring/scales.py: a cell scored from the metro's stored scales equals what the
cohort engine (score_metro_cohort) gives it."""

import random

import pytest

from scoring.engine import (
    WEIGHTS_VERSION_V2,
    WEIGHTS_VERSION_V2_1,
    robust_normalize,
    score_metro_cohort,
)
from scoring.scales import (
    PRIMARY,
    RATING,
    SECONDARY,
    SECONDARY_RATING,
    Scale,
    apply_scale,
    compute_scales,
    scale_feature_columns,
    scale_from_values,
    scales_from_rows,
    scales_to_rows,
    score_row,
)


def make_rows(n: int, seed: int = 1, rating_missing: float = 0.3) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        row = {"geo_entity_id": f"c{i}"}
        for cat in ("grocery", "gym", "cafe", "restaurant", "bar", "transit"):
            suffix = "800m" if cat == "transit" else "500m"
            count_col = "transit_stop_count_800m" if cat == "transit" else f"{cat}_count_{suffix}"
            nearest_col = "transit_nearest_m" if cat == "transit" else f"{cat}_nearest_m"
            row[count_col] = rng.randint(0, 12) if rng.random() > 0.05 else None
            row[nearest_col] = rng.uniform(10, 4000) if rng.random() > 0.05 else None
        for cat in ("gas_station", "convenience_store"):
            row[f"{cat}_count_500m"] = rng.randint(0, 5)
            row[f"{cat}_nearest_m"] = rng.uniform(20, 3000) if rng.random() > 0.1 else None
        row["school_count_1600m"] = rng.randint(0, 9)
        row["school_nearest_m"] = rng.uniform(50, 2500) if rng.random() > 0.2 else None
        row["school_avg_rating_1600m"] = (
            rng.uniform(5, 95) if rng.random() > rating_missing else None
        )
        row["congestion_proxy_raw"] = rng.uniform(0, 40)
        row["emergency_corridor_facility_raw"] = rng.uniform(0, 30) if rng.random() > 0.2 else None
        row["emergency_corridor_proxy_raw"] = rng.uniform(0, 10)
        row["street_orientation"] = rng.choice(["side_street", "facing_corridor", "unknown"])
        row["airport_drive_time_min"] = rng.uniform(10, 120)
        row["running_trail_count_800m"] = rng.randint(0, 6)
        row["running_trail_nearest_m"] = rng.uniform(30, 5000) if rng.random() > 0.1 else None
        row["strava_segment_popularity_raw"] = None
        row["shopping_raw"] = rng.random() if rng.random() > 0.1 else None
        row["premium_retail_raw"] = rng.uniform(0, 2.5) if rng.random() > 0.3 else None
        row["recreation_raw"] = rng.random() if rng.random() > 0.1 else None
        rows.append(row)
    return rows


def assert_same(expected: dict, got: dict):
    assert set(expected) == set(got)
    for key, value in expected.items():
        assert got[key] == pytest.approx(value, abs=1e-9), key


@pytest.mark.parametrize("version", [WEIGHTS_VERSION_V2_1, WEIGHTS_VERSION_V2])
def test_score_row_from_scales_equals_cohort_scoring(version):
    rows = make_rows(250)
    cohort = score_metro_cohort(rows, version)
    scales = compute_scales(rows, version)
    for row in rows:
        expected = cohort.get(row["geo_entity_id"], {})
        assert_same(expected, score_row(row, version, scales))


def test_strava_rating_present_also_matches():
    rows = make_rows(120, seed=5)
    for i, row in enumerate(rows):
        row["strava_segment_popularity_raw"] = (i * 7) % 50 if i % 3 else None
    cohort = score_metro_cohort(rows, WEIGHTS_VERSION_V2_1)
    scales = compute_scales(rows, WEIGHTS_VERSION_V2_1)
    assert SECONDARY_RATING in scales["recreation_score"]
    for row in rows:
        assert_same(cohort[row["geo_entity_id"]], score_row(row, WEIGHTS_VERSION_V2_1, scales))


def test_degenerate_cohort_scores_neutral_50_like_the_engine():
    rows = [
        {"geo_entity_id": f"c{i}", "grocery_count_500m": 2, "grocery_nearest_m": 100.0}
        for i in range(5)
    ]
    cohort = score_metro_cohort(rows, WEIGHTS_VERSION_V2_1)
    scales = compute_scales(rows, WEIGHTS_VERSION_V2_1)
    assert cohort["c0"]["grocery_score"] == 50.0
    assert score_row(rows[0], WEIGHTS_VERSION_V2_1, scales)["grocery_score"] == 50.0


def test_robust_fallback_to_min_max_when_percentiles_collapse():
    # 100 equal values and two outliers: p2 == p98, so the engine falls back to min-max.
    values = {f"c{i}": 5.0 for i in range(100)} | {"lo": 0.0, "hi": 10.0}
    expected = robust_normalize(values)
    scale = scale_from_values(values.values(), robust=True)
    assert (scale.lo, scale.hi) == (0.0, 10.0)
    for key, v in values.items():
        assert apply_scale(v, scale) == pytest.approx(expected[key])


def test_apply_scale_clamps_points_outside_the_cohort():
    scale = Scale(10.0, 20.0, 5)
    assert apply_scale(5, scale) == 0.0
    assert apply_scale(25, scale) == 100.0
    assert apply_scale(15, scale) == 50.0
    assert apply_scale(1, Scale(3.0, 3.0)) == 50.0


def test_scale_from_values_empty_is_none():
    assert scale_from_values([], True) is None


def test_school_without_rating_scores_none_but_keeps_proximity():
    rows = make_rows(60, rating_missing=1.0)
    scales = compute_scales(rows, WEIGHTS_VERSION_V2_1)
    assert RATING not in scales["school_score"]
    out = score_row(rows[0], WEIGHTS_VERSION_V2_1, scales)
    assert "school_score" not in out
    assert "school_proximity_score" in out


def test_components_present_for_recreation_and_school():
    scales = compute_scales(make_rows(80), WEIGHTS_VERSION_V2_1)
    assert {PRIMARY, SECONDARY} <= set(scales["recreation_score"])
    assert {PRIMARY, RATING} <= set(scales["school_score"])
    assert set(scales) == {
        "grocery_score", "gym_score", "cafe_score", "restaurant_score", "bar_score",
        "shopping_score", "gas_convenience_score", "transit_score", "school_score",
        "road_score", "emergency_corridor_score", "airport_score", "recreation_score",
    }  # fmt: skip


def test_row_serialization_round_trip():
    scales = compute_scales(make_rows(80), WEIGHTS_VERSION_V2_1)
    rows = scales_to_rows(WEIGHTS_VERSION_V2_1, "nyc", scales)
    assert all(r[0] == WEIGHTS_VERSION_V2_1 and r[1] == "nyc" and len(r) == 7 for r in rows)
    back = scales_from_rows(
        {"factor": f, "component": c, "lo": lo, "hi": hi, "n": n} for _, _, f, c, lo, hi, n in rows
    )
    assert back == scales


class Recording(dict):
    """A row that records every key the scoring code looks up."""

    seen: set

    def get(self, key, default=None):
        self.seen.add(key)
        return super().get(key, default)


@pytest.mark.parametrize("version", [WEIGHTS_VERSION_V2_1, WEIGHTS_VERSION_V2])
def test_scale_feature_columns_cover_every_column_the_engine_reads(version):
    Recording.seen = set()
    rows = [Recording(r) for r in make_rows(30)]
    scales = compute_scales(rows, version)
    score_row(rows[0], version, scales)
    columns = set(scale_feature_columns(version))
    assert Recording.seen - {"geo_entity_id"} <= columns
