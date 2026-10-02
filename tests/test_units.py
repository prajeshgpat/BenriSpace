import math

import pytest

from common.units import (
    format_distance,
    km_to_mi,
    m_to_ft,
    m_to_mi,
    mi_to_km,
    radius_copy,
)


def test_conversions():
    assert m_to_mi(1609.344) == pytest.approx(1.0)
    assert m_to_ft(1000) == pytest.approx(3280.84, abs=0.01)
    assert km_to_mi(1.609344) == pytest.approx(1.0)
    assert mi_to_km(3) == pytest.approx(4.828, abs=0.001)
    assert mi_to_km(km_to_mi(7.5)) == pytest.approx(7.5)


@pytest.mark.parametrize(
    "meters, expected",
    [
        (0, "0 ft"),
        (10, "50 ft"),  # 32.8 ft
        (7, "0 ft"),  # 23 ft rounds down
        (137, "450 ft"),  # 449.5 ft
        (160, "500 ft"),  # 524.9 ft, still under 0.1 mi
        (161, "0.1 mi"),  # just over 0.1 mi
        (644, "0.4 mi"),
        (1609.344, "1.0 mi"),
        (8046.72, "5.0 mi"),
        (5_000_000, "3,106.9 mi"),
    ],
)
def test_format_distance(meters, expected):
    assert format_distance(meters) == expected


@pytest.mark.parametrize("bad", [None, math.nan, math.inf, -5])
def test_format_distance_none_safe(bad):
    assert format_distance(bad) is None


def test_radius_copy():
    assert radius_copy(500) == "~0.3 mi"
    assert radius_copy(800) == "0.5 mi"
    assert radius_copy(1600) == "1 mi"
    assert radius_copy(3218.688) == "2 mi"
    assert radius_copy(1000) == "0.6 mi"
