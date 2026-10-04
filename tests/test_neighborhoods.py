"""Neighborhood names: Overpass parsing, labeling rules, geometry centroid,
the API fields and tolerance of a missing column (no network, no database)."""

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import improve, main, mapdata, similar
from api.areas import build_area_response
from api.lookup import build_score_response, with_neighborhood
from common import db
from ingestion.neighborhoods import (
    build_overpass_query,
    build_town_index,
    geometry_centroid,
    label_point,
    parse_places,
    strip_suffix,
    towns_from_records,
)

# --- parsing ---------------------------------------------------------------


def node(lat, lon, place, name="X", **extra):
    tags = {"place": place, **({"name": name} if name else {}), **extra}
    return {"type": "node", "id": 1, "lat": lat, "lon": lon, "tags": tags}


def test_parse_places_keeps_named_known_types():
    data = {
        "elements": [
            node(40.67, -73.98, "neighbourhood", "Park Slope"),
            node(40.7, -74.0, "island", "Skip"),
            node(40.7, -74.0, "suburb", None),
            {"type": "node", "id": 2, "tags": {"place": "town", "name": "NoCoords"}},
            node(40.8, -74.2, "quarter", "  Montclair  "),
            node(40.8, -74.2, "town", "Dropped"),
        ]
    }
    assert parse_places(data) == [
        (40.67, -73.98, "Park Slope", "neighbourhood"),
        (40.8, -74.2, "Montclair", "quarter"),
    ]


def test_query_mentions_all_types_and_bbox():
    q = build_overpass_query(40.1, 40.2, -74.3, -74.2)
    assert "neighbourhood|suburb|quarter" in q
    assert "(40.1,-74.3,40.2,-74.2)" in q


# --- labeling --------------------------------------------------------------


def box(lon0, lat0, lon1, lat1):
    return {
        "type": "Polygon",
        "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]],
    }


def rec(name, geom, state="34", county="003", lsad="43", namelsad=None):
    return (
        {
            "NAME": name,
            "NAMELSAD": namelsad or name,
            "STATEFP": state,
            "COUNTYFP": county,
            "LSAD": lsad,
        },
        geom,
    )


def hood(lat, lon, name, ptype="neighbourhood"):
    return (lat, lon, name, ptype)


# Synthetic world: Hudson river gap between NJ (west) and Manhattan (east);
# Brooklyn south of Manhattan; a CT town east of NJ/NY... all disjoint boxes.
MANHATTAN = rec(
    "Manhattan", box(-74.00, 40.70, -73.95, 40.80), "36", "061", "21", "Manhattan borough"
)
BROOKLYN = rec("Brooklyn", box(-74.00, 40.60, -73.90, 40.69), "36", "047", "21", "Brooklyn borough")
HOBOKEN = rec("Hoboken", box(-74.05, 40.70, -74.02, 40.80), "34", "017", "25", "Hoboken city")
MONTCLAIR = rec(
    "Montclair", box(-74.30, 40.80, -74.20, 40.90), "34", "013", "44", "Montclair township"
)
WEST_ORANGE = rec("West Orange", box(-74.40, 40.80, -74.31, 40.90), "34", "013", "44")
STAMFORD = rec("Stamford", box(-73.60, 41.00, -73.50, 41.10), "09", "001", "43", "Stamford town")
GREENWICH = rec("Greenwich", box(-73.70, 41.00, -73.61, 41.10), "09", "001", "43")
WATER = rec(
    "County subdivisions not defined",
    box(-74.02, 40.70, -74.00, 40.80),
    "36",
    "061",
    "00",
    "County subdivisions not defined",
)
PRINCETON = rec(
    "Princeton", box(-74.72, 40.30, -74.61, 40.39), "34", "021", "00"
)  # LSAD 00 is real
RECORDS = [
    PRINCETON,
    MANHATTAN,
    BROOKLYN,
    HOBOKEN,
    MONTCLAIR,
    WEST_ORANGE,
    STAMFORD,
    GREENWICH,
    WATER,
]


def label(lat, lon, *nodes, records=RECORDS):
    return label_point(lat, lon, build_town_index(records, list(nodes)))


def test_nyc_neighbourhood_gets_borough_parent():
    assert label(40.65, -73.95, hood(40.652, -73.951, "Park Slope")) == "Park Slope, Brooklyn"


def test_nyc_without_node_falls_back_to_borough():
    assert label(40.75, -73.97) == "Manhattan"
    # node farther than 1.2 mi is ignored
    assert label(40.75, -73.97, hood(40.79, -73.97, "Far")) == "Manhattan"


def test_nyc_node_must_be_in_same_borough():
    # Closest node is across the borough line in Brooklyn; Manhattan ignores it.
    near_other = hood(40.689, -73.97, "Boerum Hill")
    assert label(40.701, -73.97, near_other) == "Manhattan"
    assert label(40.701, -73.97, near_other, hood(40.71, -73.97, "Chelsea")) == "Chelsea, Manhattan"
    assert label(40.688, -73.97, near_other) == "Boerum Hill, Brooklyn"


def test_nyc_never_takes_new_jersey_parent_or_name():
    # Hoboken has the closer node, but it is across the river in NJ.
    nj = hood(40.75, -74.021, "Hoboken Hill")
    assert label(40.75, -73.999, nj) == "Manhattan"


def test_city_with_many_nodes_uses_neighbourhoods():
    nodes = [hood(40.70 + 0.01 * i, -74.035, f"Hood{i}") for i in range(5)]
    assert label(40.712, -74.035, *nodes) == "Hood1, Hoboken"
    assert label(40.712, -74.035, *nodes, hood(40.712, -74.034, "Hoboken", "suburb")) == (
        "Hood1, Hoboken"
    )  # a node named like the city is not a neighbourhood
    # beyond 1.2 mi from every node: City, ST
    assert label(40.755, -74.035, *nodes[:4]) == "Hoboken, NJ"
    assert label(40.755, -74.035, *nodes) == "Hood4, Hoboken"


def test_few_nodes_stay_plain_town():
    nodes = [hood(40.84, -74.25 + 0.001 * i, f"Hood{i}", "suburb") for i in range(4)]
    assert label(40.84, -74.25, *nodes) == "Montclair, NJ"
    assert (
        label(40.84, -74.25, *nodes, hood(40.84, -74.26, "Hood9", "quarter")) == "Hood0, Montclair"
    )


def test_city_uses_only_nodes_inside_same_town():
    inside = [hood(40.84 + 0.001 * i, -74.29, f"In{i}") for i in range(5)]
    # Montclair point next to the West Orange border; the strays are West Orange nodes.
    strays = [hood(40.85, -74.305, f"Stray{i}") for i in range(6)]
    assert label(40.85, -74.295, *strays) == "Montclair, NJ"
    assert label(40.85, -74.295, *strays, *inside) == "In4, Montclair"


def test_plain_town_ignores_hamlet_and_outside_nodes():
    assert label(41.05, -73.55, hood(41.05, -73.5501, "Springdale", "suburb")) == "Stamford, CT"
    assert label(41.05, -73.65, hood(41.05, -73.59, "Springdale")) == "Greenwich, CT"
    assert label(40.85, -74.25) == "Montclair, NJ"


def test_state_comes_from_polygon_not_geography():
    # Greenwich (CT) borders NY-style coordinates; state is the polygon's.
    assert label(41.05, -73.65) == "Greenwich, CT"
    assert label(40.75, -74.035) == "Hoboken, NJ"


def test_edge_and_water_fallback():
    # ~0.25 mi east of Montclair's edge (-74.20), in no polygon
    assert label(40.85, -74.1962) == "Montclair, NJ"
    # ~3 mi from any polygon
    assert label(40.85, -74.14) is None
    # In the river: the undefined-subdivision polygon is ignored; the nearest
    # real town within half a mile wins.
    assert label(40.75, -74.0145) == "Hoboken, NJ"


def test_nothing_is_none_not_coordinates():
    assert label(40.671, -73.9777, records=[]) is None
    out = label(40.65, -73.95, hood(40.652, -73.951, "Park Slope"))
    assert out and not any(ch.isdigit() for ch in out)


def test_strip_suffix_keeps_proper_names():
    assert strip_suffix("Hoboken city") == "Hoboken"
    assert strip_suffix("Montclair township") == "Montclair"
    assert strip_suffix("Newtown town") == "Newtown"
    assert strip_suffix("Manhattan borough") == "Manhattan"
    assert strip_suffix("Fort Lee village") == "Fort Lee"
    assert strip_suffix("West Orange") == "West Orange"
    assert strip_suffix("Union City") == "Union"  # NAME (not NAMELSAD) is preferred below
    towns = towns_from_records(
        [rec("Union City", box(0, 0, 1, 1), "34", "017", "25", "Union City city")]
    )
    assert towns[0][0].name == "Union City"
    only_lsad = towns_from_records(
        [({"NAMELSAD": "Newtown town", "STATEFP": "09", "LSAD": "43"}, box(0, 0, 1, 1))]
    )
    assert only_lsad[0][0].name == "Newtown"


def test_towns_from_records_drops_water_and_other_states():
    towns = towns_from_records(RECORDS + [rec("Philly", box(0, 0, 1, 1), "42")])
    assert [t.name for t, _ in towns] == [
        "Princeton",
        "Manhattan",
        "Brooklyn",
        "Hoboken",
        "Montclair",
        "West Orange",
        "Stamford",
        "Greenwich",
    ]
    assert towns[1][0].borough == "Manhattan"
    assert towns[3][0].borough is None and towns[3][0].state == "NJ"


# --- area centroid ---------------------------------------------------------


def test_geometry_centroid_polygon_and_multipolygon():
    square = [[-74.0, 40.0], [-73.98, 40.0], [-73.98, 40.02], [-74.0, 40.02], [-74.0, 40.0]]
    lat, lon = geometry_centroid({"type": "Polygon", "coordinates": [square]})
    assert (lat, lon) == (pytest.approx(40.01), pytest.approx(-73.99))
    multi = {"type": "MultiPolygon", "coordinates": [[square]]}
    assert geometry_centroid(multi) == (pytest.approx(40.01), pytest.approx(-73.99))
    assert geometry_centroid({"type": "Point", "coordinates": [0, 0]}) is None
    assert geometry_centroid(None) is None


# --- DB tolerance ----------------------------------------------------------


class Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.sqls.append(sql)
        if "neighborhood" in sql and not self.conn.has_column:
            raise psycopg.errors.UndefinedColumn("no neighborhood")
        self.rows = self.conn.rows

    def __iter__(self):
        return iter(self.rows)


class Conn:
    def __init__(self, has_column, rows):
        self.has_column, self.rows, self.sqls, self.rollbacks = has_column, rows, [], 0

    def cursor(self):
        return Cursor(self)

    def rollback(self):
        self.rollbacks += 1


def test_area_candidates_before_0008_default_neighborhood_to_none():
    conn = Conn(False, [{"id": 1, "extent_m": 9.0}])
    assert db.get_area_candidates(conn, 40.0, -74.0) == [
        {"id": 1, "extent_m": 9.0, "neighborhood": None}
    ]
    assert conn.rollbacks == 1 and len(conn.sqls) == 2


def test_area_candidates_with_column_keeps_value():
    conn = Conn(True, [{"id": 1, "extent_m": 5.0, "neighborhood": "Park Slope, Brooklyn"}])
    assert db.get_area_candidates(conn, 40.0, -74.0)[0]["neighborhood"] == "Park Slope, Brooklyn"


def test_neighborhoods_by_geohash_tolerates_missing_column():
    conn = Conn(False, [])
    assert db.get_neighborhoods_by_geohash(conn, ["dr5ru0"]) == {}
    assert conn.rollbacks == 1
    assert db.get_neighborhoods_by_geohash(conn, []) == {}
    ok = Conn(True, [{"geohash": "dr5ru0", "neighborhood": "Soho, Manhattan"}])
    assert db.get_neighborhoods_by_geohash(ok, ["dr5ru0"]) == {"dr5ru0": "Soho, Manhattan"}


def test_with_neighborhood_looks_up_by_geohash(monkeypatch):
    monkeypatch.setattr(
        "api.lookup.get_neighborhoods_by_geohash", lambda c, g: {"dr5ru0": "Soho, Manhattan"}
    )
    assert with_neighborhood(None, {"geohash": "dr5ru0"})["neighborhood"] == "Soho, Manhattan"
    assert with_neighborhood(None, {"geohash": "zzzzzz"})["neighborhood"] is None
    assert with_neighborhood(None, None) is None


# --- API fields ------------------------------------------------------------


def score_row():
    from datetime import datetime

    from scoring.engine import CATEGORY_SPECS

    row = {s.score_column: 50.0 for s in CATEGORY_SPECS}
    row.update(composite_score=60.0, weights_version="v", computed_at=datetime(2026, 1, 1))  # noqa: DTZ001
    return row


def test_score_response_carries_neighborhood():
    ge = {"id": uuid4(), "latitude": 40.7, "longitude": -74.0, "formatted_address": None}
    assert build_score_response(ge, score_row()).neighborhood is None
    named = build_score_response({**ge, "neighborhood": "Soho, Manhattan"}, score_row())
    assert named.model_dump(by_alias=True)["neighborhood"] == "Soho, Manhattan"


def test_area_response_prefers_area_label_then_cell():
    ge = {"id": uuid4(), "latitude": 40.7, "longitude": -74.0, "neighborhood": "Cell Hood, NJ"}
    agg = {**score_row(), "cell_count": 2}
    area = {"id": 1, "geometry": {}, "area_sq_m": 1e6, "bounded_by": ["A St"]}
    assert (
        build_area_response(area, agg, ge, 40.7, -74.0, None, "v").neighborhood == "Cell Hood, NJ"
    )
    own = {**area, "neighborhood": "Park Slope, Brooklyn"}
    assert build_area_response(own, agg, ge, 40.7, -74.0, None, "v").neighborhood == (
        "Park Slope, Brooklyn"
    )
    assert (
        build_area_response(
            area, agg, {**ge, "neighborhood": None}, 40.7, -74.0, None, "v"
        ).neighborhood
        is None
    )


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_map_top_results_have_neighborhood(monkeypatch):
    rows = [
        {"geohash": "dr5ru0", "latitude": 40.7, "longitude": -74.0, "metro_area": "nyc",
         "score": 80.0, **score_row()},
        {"geohash": "dr5ru1", "latitude": 40.9, "longitude": -74.0, "metro_area": "nyc",
         "score": 70.0, **score_row()},
    ]  # fmt: skip
    monkeypatch.setattr(main, "get_connection", lambda: FakeConn())
    monkeypatch.setattr(mapdata, "get_map_top_candidates", lambda *a: rows)
    monkeypatch.setattr(mapdata, "neighborhood_map", lambda c, g: {"dr5ru0": "Soho, Manhattan"})
    body = TestClient(main.app).get("/v1/map/top", params={"limit": 2}).json()
    assert [r["neighborhood"] for r in body["results"]] == ["Soho, Manhattan", None]


def test_improve_names_better_area_and_tip(monkeypatch):
    from common.units import M_PER_MI

    lat, lon = 40.758, -73.9855
    dlat = 0.4 * M_PER_MI / 111_320.0
    agg = {f"{k}_score": 90.0 for k in ("gym", "cafe", "restaurant", "bar", "transit", "school")}
    agg.update(grocery_score=41.0, composite_score=70.0, weights_version="v")
    cells = [{"geohash": "dr5ru9", "latitude": lat + dlat, "longitude": lon,
              "composite_score": 75.0, "grocery_score": 66.0}]  # fmt: skip
    monkeypatch.setattr(main, "get_connection", lambda: FakeConn())
    monkeypatch.setattr(main, "_resolve_area", lambda la, lo: ({"id": 1}, agg, {}, {}))
    monkeypatch.setattr(main, "get_scored_cells_in_bbox", lambda c, *a: cells)
    monkeypatch.setattr(improve, "places_for_factor", lambda *a: [])
    monkeypatch.setattr(
        improve, "neighborhood_map", lambda c, g: {"dr5ru9": "Park Slope, Brooklyn"}
    )
    body = TestClient(main.app).get("/v1/improve", params={"lat": lat, "lon": lon}).json()
    s = body["suggestions"][0]
    assert s["betterArea"]["neighborhood"] == "Park Slope, Brooklyn"
    assert "Park Slope, about 0.4 mi north, scores 66 on grocery." in s["tip"]
    assert "geohash" not in s["betterArea"]
    assert body["bestNearby"]["neighborhood"] == "Park Slope, Brooklyn"


def test_similar_results_have_neighborhood(monkeypatch):
    from scoring.embeddings import EMBEDDING_COLUMNS

    base = {c: 50.0 for c in EMBEDDING_COLUMNS}
    cand = {**base, "geohash": "dr5ru9", "latitude": 40.9, "longitude": -73.9, "dist": 1.0,
            "composite_score": 70.0}  # fmt: skip
    monkeypatch.setattr(main, "get_connection", lambda: FakeConn())
    monkeypatch.setattr(
        main, "get_geo_entity_by_geohash", lambda c, g: {"id": "g", "metro_area": "nyc"}
    )
    monkeypatch.setattr(main, "fetch_target", lambda c, i, v: base)
    monkeypatch.setattr(main, "fetch_neighbours", lambda *a: [cand])
    monkeypatch.setattr(similar, "area_label", lambda c, la, lo: "Area bounded by A and B")
    monkeypatch.setattr(similar, "neighborhood_map", lambda c, g: {"dr5ru9": "Montclair, NJ"})
    r = TestClient(main.app).get("/v1/similar", params={"lat": 40.758, "lon": -73.9855}).json()
    assert r["results"][0]["neighborhood"] == "Montclair, NJ"
    assert r["results"][0]["areaLabel"] == "Area bounded by A and B"


def test_hood_containing_city_name_uses_state_parent(monkeypatch):
    import ingestion.neighborhoods as nb

    town = type(
        "T", (), {"name": "Jersey City", "state": "NJ", "borough": None, "nodes": [0] * 9}
    )()

    class Idx:
        def town_at(self, lat, lon):
            return town

    monkeypatch.setattr(nb, "_nearest_node", lambda t, lat, lon, parent: "Downtown Jersey City")
    assert nb.label_point(40.7, -74.04, Idx()) == "Downtown Jersey City, NJ"
