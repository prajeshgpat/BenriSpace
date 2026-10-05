"""scripts/build_tiles.py: geohash squares and tippecanoe arguments (no Docker, no DB)."""

import importlib.util
import json
from pathlib import Path

from common.geo import decode, encode

SPEC = importlib.util.spec_from_file_location(
    "build_tiles", Path(__file__).resolve().parents[1] / "scripts" / "build_tiles.py"
)
build_tiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_tiles)


def test_bounds_contain_the_cell_centre_and_match_the_grid():
    for lat, lon in [(40.6782, -73.9442), (41.0534, -73.5387), (40.7128, -74.006)]:
        geohash = encode(lat, lon, 6)
        west, south, east, north = build_tiles.geohash_bounds(geohash)
        assert west <= lon <= east and south <= lat <= north
        centre_lat, centre_lon = decode(geohash)
        assert abs((south + north) / 2 - centre_lat) < 1e-9
        assert abs((west + east) / 2 - centre_lon) < 1e-9
        # a 6-character cell is about 0.0055 deg tall and 0.011 deg wide
        assert 0.005 < north - south < 0.006 and 0.010 < east - west < 0.012


def test_square_is_a_closed_ring_carrying_the_geohash():
    feature = build_tiles.square("dr5ru0")
    ring = feature["geometry"]["coordinates"][0]
    assert feature["properties"] == {"g": "dr5ru0"}
    assert ring[0] == ring[-1] and len(ring) == 5


def test_tippecanoe_layers_cover_the_zoom_ranges_the_web_expects():
    files = {name: Path(f"/w/{name}.ndjson") for name in ("cells", "parents", "areas")}
    args = build_tiles.tippecanoe_args(files, "out.pmtiles")
    layers = {json.loads(a[2:])["layer"]: json.loads(a[2:]) for a in args if a.startswith("-L")}
    assert (layers["parents"]["minzoom"], layers["parents"]["maxzoom"]) == (5, 9)
    assert (layers["cells"]["minzoom"], layers["cells"]["maxzoom"]) == (10, 13)
    assert layers["areas"]["minzoom"] == 9
    assert "--no-feature-limit" in args and "out.pmtiles" in args
