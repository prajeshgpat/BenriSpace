import io
import zipfile

import pytest

from ingestion.gtfs_transit import (
    AGENCIES,
    RADIUS_M,
    aggregate_cell,
    count_and_nearest,
    fetch_agency_stops,
    fetch_nj_transit_stops,
    parse_gtfs_zip,
    parse_stops_txt,
)

SAMPLE_STOPS_TXT = """stop_id,stop_name,stop_lat,stop_lon
1,Stop A,40.7580,-73.9855
2,Stop B,40.7527,-73.9772
3,Missing Coords,,
4,Bad Coords,not-a-float,also-not-a-float
"""


def test_parse_stops_txt_extracts_coordinates_and_skips_bad_rows():
    stops = parse_stops_txt(SAMPLE_STOPS_TXT)
    assert stops == [(40.7580, -73.9855), (40.7527, -73.9772)]


def test_parse_stops_txt_empty_input():
    assert parse_stops_txt("stop_id,stop_lat,stop_lon\n") == []


def test_parse_gtfs_zip_reads_stops_txt_from_zip_alongside_other_files():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("routes.txt", "route_id,route_short_name\n1,A\n")
        zf.writestr("stops.txt", SAMPLE_STOPS_TXT)
    stops = parse_gtfs_zip(buf.getvalue())
    assert stops == [(40.7580, -73.9855), (40.7527, -73.9772)]


def test_parse_gtfs_zip_missing_stops_txt_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("routes.txt", "route_id\n1\n")
    with pytest.raises(ValueError):
        parse_gtfs_zip(buf.getvalue())


def test_count_and_nearest_counts_within_radius_and_finds_min_distance():
    # One stop essentially at the cell center, one far outside the metro.
    stops = [(40.7580, -73.9855), (40.70, -74.20)]
    count, nearest = count_and_nearest(40.7580, -73.9855, stops, RADIUS_M)
    assert count == 1
    assert nearest is not None
    assert nearest < 1.0


def test_count_and_nearest_no_stops_returns_none_distance():
    count, nearest = count_and_nearest(40.0, -74.0, [], RADIUS_M)
    assert count == 0
    assert nearest is None


def test_aggregate_cell_single_agency_in_range():
    agency_stops = {
        "mta": [(40.7580, -73.9855)],
        "lirr": [(40.90, -74.50)],  # far away, outside radius and not nearest
    }
    result = aggregate_cell(40.7580, -73.9855, agency_stops, RADIUS_M)
    assert result["transit_stop_count_800m"] == 1
    assert result["transit_nearest_m"] < 1.0
    assert result["transit_agencies"] == ["mta"]


def test_aggregate_cell_ties_list_all_agencies_at_min_distance():
    shared_stop = (40.7500, -73.9800)
    agency_stops = {
        "lirr": [shared_stop],
        "metro_north": [shared_stop],
    }
    result = aggregate_cell(40.7500, -73.9800, agency_stops, RADIUS_M)
    assert result["transit_agencies"] == ["lirr", "metro_north"]


def test_aggregate_cell_counts_sum_across_agencies():
    agency_stops = {
        "mta": [(40.7580, -73.9855), (40.7581, -73.9856)],
        "lirr": [(40.7582, -73.9857)],
    }
    result = aggregate_cell(40.7580, -73.9855, agency_stops, RADIUS_M)
    assert result["transit_stop_count_800m"] == 3


def test_aggregate_cell_no_agencies_returns_empty_not_fabricated():
    result = aggregate_cell(40.0, -74.0, {}, RADIUS_M)
    assert result == {
        "transit_stop_count_800m": 0,
        "transit_nearest_m": None,
        "transit_agencies": [],
    }


def test_aggregate_cell_nearest_stop_outside_radius_still_counted_as_nearest():
    # No stop within 800m, but transit_nearest_m should still report the
    # true nearest distance (not None) -- count and nearest are independent.
    agency_stops = {"mta": [(41.0, -74.5)]}
    result = aggregate_cell(40.0, -74.0, agency_stops, RADIUS_M)
    assert result["transit_stop_count_800m"] == 0
    assert result["transit_nearest_m"] > RADIUS_M
    assert result["transit_agencies"] == ["mta"]


def test_agencies_config_has_all_four_with_correct_source_labels():
    names = {a.name: a.ingestion_source for a in AGENCIES}
    assert names == {
        "mta": "gtfs_mta",
        "lirr": "gtfs_lirr",
        "metro_north": "gtfs_metro_north",
        "nj_transit": "gtfs_nj_transit",
    }


def test_nj_transit_stubbed_without_credentials_raises_clear_error():
    # No .env / real credentials in this sandbox -- NJ_TRANSIT_API_KEY and
    # NJ_TRANSIT_API_USERNAME are unset, so this should fail fast with a
    # descriptive error rather than attempting a network call.
    with pytest.raises(RuntimeError, match="NJ_TRANSIT_API_KEY"):
        fetch_nj_transit_stops()


def test_fetch_agency_stops_routes_nj_transit_through_stub():
    nj_transit = next(a for a in AGENCIES if a.name == "nj_transit")
    with pytest.raises(RuntimeError, match="NJ_TRANSIT_API_KEY"):
        fetch_agency_stops(nj_transit)
