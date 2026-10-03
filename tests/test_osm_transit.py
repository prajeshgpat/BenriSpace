import httpx

from ingestion import gtfs_transit, osm_transit
from ingestion.gtfs_transit import aggregate_cell, merge_osm_into_agency_stops
from ingestion.osm_transit import OsmStop, dedupe_osm_stops, parse_stops, stops_to_places

RESP = {
    "elements": [
        {"type": "node", "id": 1, "lat": 40.80, "lon": -74.20, "tags": {"railway": "station", "name": "Bay Street"}},
        {"type": "node", "id": 2, "lat": 40.81, "lon": -74.21, "tags": {"highway": "bus_stop", "ref": "12345"}},
        {"type": "node", "id": 3, "lat": 40.82, "lon": -74.22, "tags": {"highway": "bus_stop"}},
        {"type": "node", "id": 4, "lat": 40.83, "lon": -74.23, "tags": {"highway": "bus_stop", "name": "  Main   St "}},
        {"type": "way", "id": 5, "center": {"lat": 40.0, "lon": -74.0}, "tags": {"railway": "station"}},
        {"type": "node", "id": 1, "lat": 40.80, "lon": -74.20, "tags": {"railway": "station", "name": "Bay Street"}},
        {"type": "node", "id": 6, "tags": {"railway": "halt", "name": "No Loc"}},
    ]
}


def test_parse_stops():
    stops = parse_stops(RESP)
    assert [s.osm_id for s in stops] == ["node/1", "node/2", "node/4"]
    assert stops[1].name is None and stops[1].ref == "12345"
    assert stops[2].name == "Main St"


def test_query_has_expected_filters_and_no_entrances():
    q = osm_transit.build_query(40.0, 41.0, -75.0, -74.0)
    assert '"railway"="station"' in q and '"highway"="bus_stop"' in q
    assert "subway_entrance" not in q and "40.0,-75.0,41.0,-74.0" in q


def test_dedupe_against_gtfs_and_self():
    gtfs = [(40.8000, -74.2000)]
    stops = [
        OsmStop(40.80010, -74.2000, "Bay Street", "node/1"),  # ~11 m from GTFS: dropped
        OsmStop(40.8100, -74.2100, "Main St", "node/2"),
        OsmStop(40.81010, -74.2100, "main st", "node/3"),  # same name, 11 m: dropped
        OsmStop(40.81010, -74.2100, "Other", "node/4"),  # different name: kept
        OsmStop(40.8200, -74.2200, "Main St", "node/5"),  # same name, far: kept
        OsmStop(40.8300, -74.2300, None, "node/6", "9"),
        OsmStop(40.83005, -74.2300, None, "node/7", "9"),  # same ref nearby: dropped
        OsmStop(40.83005, -74.2300, None, "node/8", "10"),  # other ref: kept
    ]
    kept = dedupe_osm_stops(stops, gtfs)
    assert [s.osm_id for s in kept] == ["node/2", "node/4", "node/5", "node/6", "node/8"]


def test_aggregate_with_osm_and_gtfs():
    agency_stops = {"mta": [(40.8000, -74.2000)]}
    osm = [OsmStop(40.80005, -74.2000, "dup", "node/1"), OsmStop(40.8100, -74.2000, "Far", "node/2")]
    kept = merge_osm_into_agency_stops(agency_stops, osm)
    assert [s.osm_id for s in kept] == ["node/2"]
    # Cell near the OSM-only stop: osm is nearest.
    r = aggregate_cell(40.8095, -74.2000, agency_stops)
    assert r["transit_agencies"] == ["osm"]
    assert r["transit_stop_count_800m"] == 1
    # Cell at the GTFS stop: counted once, not inflated by the dropped dup.
    r = aggregate_cell(40.8000, -74.2000, agency_stops)
    assert r["transit_agencies"] == ["mta"]
    assert r["transit_stop_count_800m"] == 1


def test_merge_without_survivors_adds_no_agency():
    agency_stops = {"mta": [(40.8, -74.2)]}
    assert merge_osm_into_agency_stops(agency_stops, []) == []
    assert "osm" not in agency_stops


def test_places_named_only_with_distinct_source():
    places = stops_to_places(parse_stops(RESP))
    assert [(p.source, p.source_id, p.category, p.name) for p in places] == [
        ("osmtransit", "node/1", "transit", "Bay Street"),
        ("osmtransit", "node/4", "transit", "Main St"),
    ]
    # replace_places('osm') deletes source='osm' or 'osm:%' -- never 'osmtransit'.
    assert not places[0].source.startswith("osm:") and places[0].source != "osm"


def test_osm_failure_isolated(monkeypatch):
    logged = []
    monkeypatch.setattr(gtfs_transit, "log_ingestion_run", lambda *a, **k: logged.append((a, k)) or 1)

    def boom():
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(osm_transit, "fetch_all_stops", boom)
    assert gtfs_transit.fetch_osm_stops_isolated() is None
    assert logged[-1][1]["status"] == "failed"
