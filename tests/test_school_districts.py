import json
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from shapely.geometry import box, mapping

from ingestion.school_districts import (
    DistrictIndex,
    districts_from_records,
    normalize_within_state,
    parse_rating_row,
)

FIX = Path(__file__).parent / "fixtures"


def _index():
    recs_unsd = [
        (
            {"GEOID": "3600001", "NAME": "A", "STATEFP": "36"},
            mapping(box(-74.0, 40.0, -73.0, 41.0)),
        ),
    ]
    recs_scsd = [  # overlaps A; lower priority
        (
            {"GEOID": "3600099", "NAME": "HS overlay", "STATEFP": "36"},
            mapping(box(-74.0, 40.0, -73.5, 41.0)),
        ),
    ]
    recs_elsd = [
        (
            {"GEOID": "3400002", "NAME": "B", "STATEFP": "34"},
            mapping(box(-75.0, 40.0, -74.0001, 41.0)),
        ),
    ]
    items = (
        districts_from_records(recs_scsd, "scsd")
        + districts_from_records(recs_elsd, "elsd")
        + districts_from_records(recs_unsd, "unsd")
    )
    return DistrictIndex(items)


def test_point_in_polygon_prefers_unified_over_overlay():
    d = _index().assign(lat=40.5, lon=-73.7)  # inside A and the overlay
    assert d is not None and d.geoid == "3600001"


def test_point_in_other_district():
    d = _index().assign(lat=40.5, lon=-74.5)
    assert d.geoid == "3400002"


def test_no_district_is_none_never_nearest():
    # 0.0001 deg outside B and A's gap: nearest polygon is metres away
    assert _index().assign(lat=40.5, lon=-74.00005) is None
    assert _index().assign(lat=45.0, lon=-73.5) is None
    assert DistrictIndex([]).assign(40.5, -73.5) is None


def test_parse_rating_rows_and_missing_stay_none():
    rows = json.loads((FIX / "school_urban_rows.json").read_text())
    parsed = {}
    for r in rows:
        p = parse_rating_row(r)
        if p:
            parsed[p[0]] = p[1]
    assert parsed["3600001"] == 65.0  # subgroup row ignored
    assert parsed["3600002"] == 40.0  # suppressed math ignored
    assert "3600003" not in parsed  # fully suppressed -> no value
    assert parsed["0900001"] == 80.0  # leaid zero-padded


def test_normalize_within_state_percentiles_and_none():
    raw = {
        "3600001": 10.0,
        "3600002": 30.0,
        "3600003": 50.0,
        "3600004": None,
        "3400001": 90.0,
        "3400002": 95.0,
        "0900001": 12.0,
    }
    out = normalize_within_state(raw)
    assert out["3600001"] == 0.0 and out["3600002"] == 50.0 and out["3600003"] == 100.0
    assert out["3600004"] is None
    # NJ's raw values are far higher but its percentiles are on the same 0-100 scale
    assert out["3400001"] == 0.0 and out["3400002"] == 100.0
    assert out["0900001"] == 50.0  # lone district


def test_normalize_ties_use_midrank():
    out = normalize_within_state({"3600001": 5.0, "3600002": 5.0, "3600003": 9.0})
    assert out["3600001"] == out["3600002"] == 25.0
    assert out["3600003"] == 100.0
