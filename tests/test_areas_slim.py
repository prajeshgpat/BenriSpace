"""Slim area storage: configurable caps, geometry slimming, row building, API lookup."""

import json
from types import SimpleNamespace

import pytest
from shapely.geometry import MultiPolygon, Polygon

from api import slim_areas
from ingestion.areas import limits, slim


@pytest.fixture
def restore_limits():
    saved = {
        "max_area_sq_mi": limits.MAX_AREA_SQ_MI,
        "max_extent_mi": limits.MAX_EXTENT_MI,
        "target_tile_mi": limits.TARGET_TILE_MI,
        "min_sliver_sq_mi": limits.MIN_SLIVER_SQ_MI,
    }
    yield
    limits.configure(**saved)


def test_configure_overrides_and_derives_metric_caps(restore_limits):
    caps = limits.configure(
        max_area_sq_mi=0.1, max_extent_mi=0.6, target_tile_mi=0.3, min_sliver_sq_mi=0.005
    )
    assert caps["max_area_sq_mi"] == 0.1
    assert limits.MAX_AREA_M2 == pytest.approx(0.1 * limits.SQ_M_PER_SQ_MI)
    assert limits.MAX_EXTENT_M == pytest.approx(0.6 * limits.M_PER_MI)


def test_configure_keeps_unset_values_and_rejects_bad_ones(restore_limits):
    limits.configure(max_area_sq_mi=0.5)
    assert limits.MAX_EXTENT_MI == 1.4
    with pytest.raises(ValueError):
        limits.configure(max_area_sq_mi=-1)
    with pytest.raises(ValueError):
        limits.configure(min_sliver_sq_mi=10)


def test_defaults_unchanged():
    assert (limits.MAX_AREA_SQ_MI, limits.MAX_EXTENT_MI) == (0.8, 1.4)
    assert (limits.TARGET_TILE_MI, limits.MIN_SLIVER_SQ_MI) == (0.75, 0.02)


def test_slim_geometry_drops_collinear_vertices_and_snaps():
    ring = [(0, 0), (0.0005, 0.0000001), (0.001, 0), (0.001, 0.001), (0, 0.001), (0, 0)]
    g = slim.slim_geometry(Polygon(ring))
    assert isinstance(g, MultiPolygon) and g.is_valid
    assert len(g.geoms[0].exterior.coords) == 5  # the near-collinear midpoint is gone
    for x, y in g.geoms[0].exterior.coords:
        assert round(x, 5) == pytest.approx(x, abs=1e-12)


def test_slim_row_shape():
    face = SimpleNamespace(
        geometry=Polygon([(-74, 40.7), (-73.999, 40.7), (-73.999, 40.701), (-74, 40.701)]),
        area_sq_m=limits.SQ_M_PER_SQ_MI * 0.05,
        extent_m=limits.M_PER_MI * 0.2,
        compactness=0.7,
        bounded_by=("A St", "B Ave"),
    )
    row = slim.slim_row(3, face, "v", "nyc", "Park Slope, Brooklyn")
    assert row[0] == 3 and row[2] == "nyc" and row[7] == ["A St", "B Ave"]
    assert row[4] == pytest.approx(0.05) and row[5] == pytest.approx(0.2)
    assert isinstance(row[3], bytes) and row[8] == "Park Slope, Brooklyn"


def test_writer_refuses_without_url_and_empty_build(monkeypatch):
    monkeypatch.delenv("AREAS_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        slim.areas_database_url()
    with pytest.raises(ValueError):
        slim.write_areas_slim(object(), [], "v", lambda f: None)


def test_slim_areas_enabled_flag(monkeypatch):
    monkeypatch.delenv("AREAS_TABLE", raising=False)
    assert not slim_areas.enabled()
    monkeypatch.setenv("AREAS_TABLE", "areas_slim")
    assert slim_areas.enabled()


def test_row_to_area_converts_units_and_geojson():
    gj = {"type": "MultiPolygon", "coordinates": []}
    area = slim_areas.row_to_area(
        {
            "id": 7,
            "area_sq_mi": 0.05,
            "extent_mi": 0.2,
            "bounded_by": None,
            "neighborhood": "X",
            "geojson": json.dumps(gj),
        }
    )
    assert area["area_sq_m"] == pytest.approx(0.05 * 2_589_988.11)
    assert area["geometry"] == gj and area["bounded_by"] == [] and area["neighborhood"] == "X"


def test_simplified_select_matches_insert_column_order_and_tolerance():
    sql = slim.simplified_select_sql(3e-05)
    assert sql.startswith("select id, build_version, metro_area, st_asbinary(")
    assert "st_simplifypreservetopology(geom, 3e-05)" in sql and "st_reduceprecision" in sql
    assert sql.endswith(
        "area_sq_mi, extent_mi, compactness, bounded_by, neighborhood from areas_slim order by id"
    )
    assert slim.PROD_SIMPLIFY_DEG == 3e-05
