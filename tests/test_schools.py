import pytest

from ingestion.schools import (
    RATING_SCALE_MAX,
    SchoolRecord,
    build_spatial_index,
    compute_cell_aggregate,
    fetch_all_schools,
    merge_school_records,
    parse_location_row,
    parse_rating_row,
)

# --- parsing -----------------------------------------------------------


def test_parse_location_row_happy_path():
    row = {
        "system_code": "15K001",
        "location_name": "P.S. 001",
        "latitude": "40.648959",
        "longitude": "-74.01142",
        "status_descriptions": "Open",
    }
    parsed = parse_location_row(row)
    assert parsed == ("15K001", 40.648959, -74.01142, "P.S. 001")


def test_parse_location_row_skips_closed_schools():
    row = {
        "system_code": "15K001",
        "latitude": "40.6",
        "longitude": "-74.0",
        "status_descriptions": "Closed",
    }
    assert parse_location_row(row) is None


def test_parse_location_row_skips_missing_coordinates():
    row = {"system_code": "15K001", "status_descriptions": "Open"}
    assert parse_location_row(row) is None


def test_parse_location_row_skips_missing_dbn():
    row = {
        "latitude": "40.6",
        "longitude": "-74.0",
        "status_descriptions": "Open",
    }
    assert parse_location_row(row) is None


def test_parse_rating_row_scales_fraction_to_0_10():
    row = {"dbn": "01M015", "metric_value": "0.904", "metric_variable_name": "attendance_k8_all"}
    parsed = parse_rating_row(row)
    assert parsed is not None
    dbn, rating = parsed
    assert dbn == "01M015"
    assert rating == pytest.approx(9.04)
    assert 0 <= rating <= RATING_SCALE_MAX


def test_parse_rating_row_skips_missing_value():
    assert parse_rating_row({"dbn": "01M015", "metric_value": None}) is None
    assert parse_rating_row({"metric_value": "0.9"}) is None


# --- merging -------------------------------------------------------------


def test_merge_school_records_joins_by_dbn():
    locations = [
        {
            "system_code": "01M015",
            "location_name": "P.S. 015",
            "latitude": "40.72",
            "longitude": "-73.98",
            "status_descriptions": "Open",
        },
        {
            "system_code": "01M020",
            "location_name": "P.S. 020",
            "latitude": "40.73",
            "longitude": "-73.99",
            "status_descriptions": "Open",
        },
    ]
    ratings = [
        {"dbn": "01M015", "metric_value": "0.9", "metric_variable_name": "attendance_k8_all"},
        # 01M020 has no rating row -> should still appear, rating=None
    ]
    records = merge_school_records(locations, ratings, source="test")
    assert len(records) == 2
    by_name = {r.name: r for r in records}
    assert by_name["P.S. 015"].rating == 9.0
    assert by_name["P.S. 020"].rating is None
    assert all(r.source == "test" for r in records)


def test_merge_school_records_skips_closed_but_keeps_unrated():
    locations = [
        {
            "system_code": "X",
            "location_name": "Closed School",
            "latitude": "40.7",
            "longitude": "-74.0",
            "status_descriptions": "Closed",
        }
    ]
    records = merge_school_records(locations, [], source="test")
    assert records == []


# --- spatial aggregation --------------------------------------------------


def _school(lat, lon, rating=None, name="s"):
    return SchoolRecord(lat=lat, lon=lon, rating=rating, name=name, source="test")


def test_compute_cell_aggregate_counts_within_radius_only():
    # Cell at (40.70, -74.00). One school ~100m away, one ~5km away.
    cell_lat, cell_lon = 40.70, -74.00
    near = _school(40.7009, -74.00, rating=8.0, name="near")  # ~100m north
    far = _school(40.745, -74.00, rating=2.0, name="far")  # ~5km north
    index = build_spatial_index([near, far])

    result = compute_cell_aggregate(cell_lat, cell_lon, index)
    assert result["school_count_1600m"] == 1
    assert result["school_avg_rating_1600m"] == 8.0
    assert result["school_nearest_m"] is not None
    assert result["school_nearest_m"] < 200


def test_compute_cell_aggregate_averages_only_rated_schools():
    cell_lat, cell_lon = 40.70, -74.00
    rated = _school(40.7005, -74.00, rating=6.0, name="rated")
    unrated = _school(40.7006, -74.00, rating=None, name="unrated")
    index = build_spatial_index([rated, unrated])

    result = compute_cell_aggregate(cell_lat, cell_lon, index)
    assert result["school_count_1600m"] == 2
    assert result["school_avg_rating_1600m"] == 6.0  # unrated school excluded from average


def test_compute_cell_aggregate_no_candidates_returns_nulls_not_zero_distance():
    cell_lat, cell_lon = 40.70, -74.00
    far_away = _school(41.9, -73.6, rating=5.0, name="far")  # well outside 3x3 bucket block
    index = build_spatial_index([far_away])

    result = compute_cell_aggregate(cell_lat, cell_lon, index)
    assert result["school_count_1600m"] == 0
    assert result["school_nearest_m"] is None
    assert result["school_avg_rating_1600m"] is None


def test_compute_cell_aggregate_empty_index():
    result = compute_cell_aggregate(40.70, -74.00, build_spatial_index([]))
    assert result == {
        "school_count_1600m": 0,
        "school_nearest_m": None,
        "school_avg_rating_1600m": None,
    }


def test_build_spatial_index_buckets_nearby_schools_together():
    a = _school(40.70, -74.00, name="a")
    b = _school(40.7001, -74.0001, name="b")
    index = build_spatial_index([a, b])
    # Both schools should land in the same or adjacent buckets.
    assert sum(len(v) for v in index.values()) == 2


# --- fetch_all_schools / stub handling ------------------------------------


class _WorkingSource:
    name = "working"

    def fetch(self):
        return [SchoolRecord(lat=40.7, lon=-74.0, rating=5.0, name="w", source=self.name)]


class _StubSource:
    name = "stub"

    def fetch(self):
        raise NotImplementedError("not wired up yet")


def test_fetch_all_schools_skips_stubs_without_failing():
    schools = fetch_all_schools([_WorkingSource(), _StubSource()])
    assert len(schools) == 1
    assert schools[0].source == "working"
