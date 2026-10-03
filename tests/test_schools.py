import json
from pathlib import Path

import pytest

from ingestion.schools import (
    SchoolRecord,
    build_spatial_index,
    compute_cell_aggregate,
    district_fields,
    parse_nces_row,
)

FIX = Path(__file__).parent / "fixtures"


def _schools():
    rows = json.loads((FIX / "school_nces_rows.json").read_text())
    return [r for r in map(parse_nces_row, rows) if r is not None]


def test_parse_nces_keeps_only_metro_states_in_bbox():
    names = [s.name for s in _schools()]
    assert names == ["PS 1", "NJ Elem"]  # CA, upstate-out-of-bbox, no-coords dropped


def test_count_and_nearest_within_radius():
    index = build_spatial_index(_schools())
    agg = compute_cell_aggregate(40.7500, -73.9900, index)
    assert agg["school_count_1600m"] == 1
    assert agg["school_nearest_m"] == 0.0


def test_count_and_nearest_far_school_not_counted():
    far = [SchoolRecord(40.7500, -73.9700, "x", "t")]  # ~1.7 km east
    agg = compute_cell_aggregate(40.7500, -73.9900, build_spatial_index(far))
    assert agg["school_count_1600m"] == 0
    assert 1500 < agg["school_nearest_m"] < 2000


def test_no_candidates_gives_none_not_fabricated():
    agg = compute_cell_aggregate(41.0, -74.0, build_spatial_index(_schools()))
    assert agg == {"school_count_1600m": 0, "school_nearest_m": None}


def test_district_fields_unrated_or_missing_district_is_null():
    pytest.importorskip("shapely")
    from ingestion.school_districts import District

    d = District("3600001", "Test SD", "unsd", "36")
    got = district_fields(d, {"3600001": 72.5}, "src")
    assert got["school_district_rating"] == got["school_avg_rating_1600m"] == 72.5
    assert got["school_rating_source"] == "src"
    unrated = district_fields(d, {"3600001": None}, "src")
    assert unrated["school_district_rating"] is None and unrated["school_rating_source"] is None
    none = district_fields(None, {}, "src")
    assert none["school_district_geoid"] is None and none["school_district_rating"] is None


def test_unwrap_shapefile_zip_extracts_nested_zip(tmp_path):
    import zipfile

    from ingestion.schools import _unwrap_shapefile_zip

    outer = tmp_path / "EDGE.zip"
    with zipfile.ZipFile(outer, "w") as zf:
        zf.writestr("Shapefile_SCH.zip", b"inner-bytes")
        zf.writestr("EDGE.TXT", b"x")
    inner = _unwrap_shapefile_zip(outer)
    assert inner.name == "Shapefile_SCH.zip" and inner.read_bytes() == b"inner-bytes"

    flat = tmp_path / "flat.zip"
    with zipfile.ZipFile(flat, "w") as zf:
        zf.writestr("a.shp", b"x")
    assert _unwrap_shapefile_zip(flat) == flat


def test_schools_to_places_uses_ncessch_or_coords_and_skips_blank():
    from common.places import Place
    from ingestion.schools import schools_to_places

    schools = [
        SchoolRecord(40.7, -74.0, "  PS   1 ", "nces_edge", "360001"),
        SchoolRecord(40.71234567, -74.01, "No Id", "nces_edge"),
        SchoolRecord(40.8, -74.0, "   ", "nces_edge", "9"),
    ]
    assert schools_to_places(schools) == [
        Place("nces", "360001", "school", "PS 1", 40.7, -74.0),
        Place("nces", "40.71235,-74.01000", "school", "No Id", 40.71234567, -74.01),
    ]


def test_parse_nces_row_carries_ncessch():
    row = {"STATE": "NY", "LAT": 40.7, "LON": -74.0, "NAME": "X", "NCESSCH": "123"}
    assert parse_nces_row(row).source_id == "123"
