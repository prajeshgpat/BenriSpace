"""scoring/area_run.py pure parts: area means, composite, quantizing, the area file."""

import numpy as np

from api import areafile
from api.factors import FACTOR_COLUMNS
from scoring import area_run


def test_area_means_average_cells_and_fall_back_to_the_nearest_cell():
    values = {"a": 10.0, "b": 30.0, "c": 70.0}
    cell_area = {"a": 100, "b": 100, "c": 200}
    out = area_run.area_means(values, cell_area, {100: 0, 200: 1, 300: 2}, 3, ["a", "c", "c"])
    assert list(out) == [20.0, 70.0, 70.0]  # area 300 holds no cell centre: nearest is "c"


def test_composite_uses_v21_weights_over_present_factors():
    scores = {c: np.array([50.0, np.nan]) for c in FACTOR_COLUMNS.values()}
    scores["grocery_score"] = np.array([100.0, 80.0])
    out = area_run.composite(scores)
    assert 50 < out[0] < 100
    assert out[1] == 80.0  # only grocery present


def test_to_int_rounds_half_up_and_keeps_missing():
    assert area_run.to_int(np.array([49.5, 0.4, np.nan, 100.7])) == [50, 0, None, 100]


def test_area_file_round_trips():
    columns = list(FACTOR_COLUMNS.values())
    built = {
        "area_ids": np.array([7, 3]),
        "lat": np.array([40.7, 41.0]),
        "lon": np.array([-74.0, -73.9]),
        "names": {7: ("Lloyd, NY", "hudson_valley"), 3: (None, None)},
        "scores": {c: np.array([32.0, np.nan]) for c in columns},
    }
    header, rows = areafile.decode(area_run.area_file(built, "v2.2-density", "2026-10-05"))
    assert header["version"] == "v2.2-density"
    assert [r.id for r in rows] == [3, 7]
    assert rows[1].name == "Lloyd, NY" and set(rows[1].scores) == {32}
    assert set(rows[0].scores) == {255}
