import json
from pathlib import Path

import pytest

from ingestion.emergency_facilities import (
    annotate_segments_with_factor,
    compute_emergency_features,
    compute_facility_features,
    dedupe_facilities,
    index_facilities,
    parse_facilities,
    segment_facility_factor,
)
from ingestion.roads import classify_cell, index_segments

FIXTURE = Path(__file__).parent / "fixtures" / "emergency_manhattan_overpass.json"
LAT, LON = 40.75, -73.98
M_LAT = 1 / 111_320.0  # degrees per metre of latitude


def fac(dlat_m=0.0, weight=1.0):
    return {"lat": LAT + dlat_m * M_LAT, "lon": LON, "weight": weight}


def seg(highway, dlat_m=0.0):
    return {"highway": highway, "lanes": None, "lat": LAT + dlat_m * M_LAT, "lon": LON}


def raw(segments, facilities, cell=(LAT, LON)):
    fi = index_facilities(facilities)
    ri = index_segments(annotate_segments_with_factor(segments, fi))
    return compute_emergency_features(cell[0], cell[1], ri, fi)


def test_factor_capped_at_three():
    facs = [fac(0, 1.0) for _ in range(10)]
    assert segment_facility_factor(LAT, LON, index_facilities(facs)) == 3.0


def test_no_facility_factor_one_term_zero_nearest_none():
    assert segment_facility_factor(LAT, LON, {}) == 1.0
    f = compute_facility_features(LAT, LON, [])
    assert f["facility_term"] == 0 and f["emergency_facility_nearest_m"] is None
    assert f["emergency_facility_count_1600m"] == 0
    out = raw([seg("primary", 100)], [])
    assert out["emergency_corridor_facility_raw"] == pytest.approx(4.0 / (1 + 100 / 150), abs=0.01)
    assert out["emergency_facility_nearest_m"] is None


def test_police_weighs_less_than_fire():
    assert raw([], [fac(100, 0.5)])["emergency_corridor_facility_raw"] < raw([], [fac(100, 1.0)])["emergency_corridor_facility_raw"]
    roads = [seg("primary", 50)]
    assert raw(roads, [fac(300, 0.5)])["emergency_corridor_facility_raw"] < raw(roads, [fac(300, 1.0)])["emergency_corridor_facility_raw"]


def test_hospital_emergency_yes_weight():
    els = [
        {"type": "node", "lat": 1, "lon": 1, "tags": {"amenity": "hospital", "emergency": "yes"}},
        {"type": "node", "lat": 2, "lon": 2, "tags": {"amenity": "hospital"}},
        {"type": "node", "lat": 3, "lon": 3, "tags": {"amenity": "police"}},
        {"type": "node", "lat": 4, "lon": 4, "tags": {"emergency": "ambulance_station"}},
        {"type": "node", "lat": 5, "lon": 5, "tags": {"amenity": "cafe"}},
    ]
    assert [f["weight"] for f in parse_facilities(els)] == [1.0, 0.6, 0.5, 1.0]


def test_far_facility_adds_nothing():
    roads = [seg("primary", 100)]
    base = raw(roads, [])["emergency_corridor_facility_raw"]
    out = raw(roads, [fac(2500, 1.0)])
    assert out["emergency_corridor_facility_raw"] == base
    assert out["emergency_facility_count_1600m"] == 0
    assert 2400 < out["emergency_facility_nearest_m"] < 2600  # nearest is unbounded


def test_minor_street_never_contributes():
    for hw in ("residential", "tertiary", "service"):
        assert raw([seg(hw, 50)], [fac(100)])["emergency_corridor_facility_raw"] == pytest.approx(1.0 / (1 + 100 / 150), abs=0.01)  # facility term only


def test_major_road_near_facility_penalised_more():
    near = raw([seg("primary", 50)], [fac(100)])["emergency_corridor_facility_raw"]
    nofac_segment = raw([seg("primary", 50)], [fac(1900)])["emergency_corridor_facility_raw"]
    assert near > nofac_segment


def test_way_with_center_handled():
    els = [{"type": "way", "center": {"lat": LAT, "lon": LON}, "tags": {"amenity": "fire_station"}},
           {"type": "relation", "tags": {"amenity": "fire_station"}}]  # no center -> skipped
    got = parse_facilities(els)
    assert got == [{"lat": LAT, "lon": LON, "weight": 1.0}]


def test_dedupe_and_determinism():
    facs = [fac(0), fac(10), fac(500)]
    assert len(dedupe_facilities(facs)) == 2
    assert dedupe_facilities(facs) == dedupe_facilities(list(reversed(facs)))
    roads = [seg("primary", 80), seg("secondary", 200)]
    assert raw(roads, facs) == raw(roads, facs)


def test_old_column_unchanged_and_omitted_without_facilities():
    ri = index_segments([seg("primary", 100)])
    legacy = classify_cell(LAT, LON, ri)
    assert "emergency_corridor_facility_raw" not in legacy
    with_fac = classify_cell(LAT, LON, index_segments(annotate_segments_with_factor([seg("primary", 100)], index_facilities([fac(50)]))), index_facilities([fac(50)]))
    assert with_fac["emergency_corridor_proxy_raw"] == legacy["emergency_corridor_proxy_raw"]
    assert with_fac["emergency_corridor_facility_raw"] > legacy["emergency_corridor_proxy_raw"]


def test_real_manhattan_fixture():
    facs = dedupe_facilities(parse_facilities(json.loads(FIXTURE.read_text())["elements"]))
    assert 15 <= len(facs) <= 27
    f = compute_facility_features(40.755, -73.98, index_facilities(facs))
    assert f["emergency_facility_count_1600m"] > 5
    assert f["emergency_facility_nearest_m"] < 1000
