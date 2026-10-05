import pytest

from ingestion import density


def test_travel_mode_threshold():
    assert density.travel_mode(None) is None
    assert density.travel_mode(9999.9) == "drive"
    assert density.travel_mode(10000) == "walk"


def test_block_group_density():
    assert density.block_group_density(100, 0) is None
    assert density.block_group_density(2589, density.SQ_M_PER_SQ_MI) == pytest.approx(2589)


def test_cell_density_is_area_weighted_and_skips_undefined():
    assert density.cell_density([(1.0, 100.0), (3.0, 200.0)]) == pytest.approx(175.0)
    assert density.cell_density([(1.0, None), (2.0, 50.0), (0.0, 999.0)]) == 50.0
    assert density.cell_density([]) is None


def test_parse_pl_block_groups():
    def geo(sumlev, rec, geoid, land):
        parts = [""] * 96
        parts[2], parts[7], parts[9], parts[84] = sumlev, rec, geoid, land
        return "|".join(parts)

    geo_text = "\n".join(
        [geo("050", "0000002", "09001", "5"), geo("150", "0000010", "090010101011", "2589988")]
    )
    data_text = "PLST|CT|000|01|0000010|1234|9\nPLST|CT|000|01|0000002|99|9"
    assert density.parse_pl_block_groups(geo_text, data_text) == {"090010101011": (1234, 2589988.0)}


def test_densities_for_cells_weights_by_intersection():
    pytest.importorskip("shapely")
    from shapely.geometry import box

    polys = [box(0, 0, 1, 1), box(1, 0, 2, 1)]
    rects = [(0.5, 0.0, 1.5, 1.0), (0.1, 0.1, 0.2, 0.2), (5, 5, 6, 6)]
    out = density.densities_for_cells(rects, polys, [100.0, 300.0])
    assert out[0] == pytest.approx(200.0)
    assert out[1] == pytest.approx(100.0)
    assert out[2] is None


def test_geohash_rect_contains_center():
    import pygeohash as pgh

    lat, lon = pgh.decode("dr5ru7")
    min_lon, min_lat, max_lon, max_lat = density.geohash_rect("dr5ru7")
    assert min_lon < lon < max_lon and min_lat < lat < max_lat
