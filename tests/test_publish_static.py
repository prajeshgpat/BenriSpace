"""scripts/publish_static.py pure parts and the areaScores codec (no network, no database)."""

import gzip
import importlib.util
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api import areafile, scorefile
from api.scorefile import FACTOR_KEYS

SPEC = importlib.util.spec_from_file_location(
    "publish_static", Path(__file__).resolve().parents[1] / "scripts" / "publish_static.py"
)
publish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish)

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
SHA = "ab" * 32


def scores(seed: int) -> tuple[int, ...]:
    return tuple((seed * 7 + j * 3) % 101 if j != 4 else 255 for j in range(len(FACTOR_KEYS)))


def test_object_keys_are_content_addressed():
    assert publish.object_key("scores", "v2.1", SHA) == "scores/v2.1.abababababab.bin"
    assert publish.object_key("areaScores", "v2.1", SHA) == "areas/v2.1.abababababab.bin"
    assert publish.object_key("tiles", "v2.1", SHA) == "tiles/benrispace.abababababab.pmtiles"
    with pytest.raises(ValueError):
        publish.object_key("nope", "v", SHA)


def test_entry_hashes_uncompressed_bytes():
    data = b"hello world"
    e = publish.entry("scores", "v1", data)
    assert e["bytes"] == 11 and e["sha256"] == publish.sha256_hex(data)
    assert e["path"] == f"scores/v1.{e['sha256'][:12]}.bin"


def test_put_args_gzips_bin_and_leaves_pmtiles_raw():
    body, extra = publish.put_args("scores/x.bin", b"abc" * 100)
    assert gzip.decompress(body) == b"abc" * 100
    assert extra["ContentEncoding"] == "gzip"
    assert extra["ContentType"] == "application/octet-stream"
    assert extra["CacheControl"] == "public, max-age=31536000, immutable"
    raw, extra = publish.put_args("tiles/benrispace.x.pmtiles", b"PMTiles")
    assert raw == b"PMTiles" and "ContentEncoding" not in extra
    assert extra["ContentType"] == "application/vnd.pmtiles"
    # deterministic: the same bytes always give the same wire body
    assert publish.put_args("scores/x.bin", b"z")[0] == publish.put_args("scores/x.bin", b"z")[0]


def test_merge_keeps_entries_that_are_not_republished():
    old = {
        "format": 1,
        "weightsVersion": "v2.1-handtuned",
        "scores": {"path": "scores/old.bin", "bytes": 1, "sha256": "a"},
        "areaScores": {"path": "areas/old.bin", "bytes": 2, "sha256": "b"},
        "tiles": {"path": "tiles/old.pmtiles", "bytes": 3, "sha256": "c"},
    }
    new_scores = {"path": "scores/new.bin", "bytes": 9, "sha256": "d"}
    merged = publish.merge_manifest(old, {"scores": new_scores}, "v2.1-handtuned", NOW)
    assert merged["scores"] == new_scores
    assert merged["areaScores"] == old["areaScores"] and merged["tiles"] == old["tiles"]
    assert merged["generatedAt"] == "2026-10-05T00:00:00+00:00" and merged["format"] == 1


def test_merge_drops_stale_version_scores_but_keeps_tiles():
    old = {
        "format": 1,
        "weightsVersion": "v2",
        "scores": {"path": "s", "bytes": 1, "sha256": "a"},
        "areaScores": {"path": "a", "bytes": 1, "sha256": "b"},
        "tiles": {"path": "t", "bytes": 1, "sha256": "c"},
    }
    new = {"path": "n", "bytes": 1, "sha256": "d"}
    merged = publish.merge_manifest(old, {"scores": new}, "v2.1-handtuned", NOW)
    assert "areaScores" not in merged and merged["tiles"] == old["tiles"]
    assert publish.merge_manifest(None, {"scores": new}, "v", NOW)["scores"] == new


def test_prune_keeps_referenced_and_recent_objects():
    manifest = {"scores": {"path": "scores/keep.bin"}, "tiles": {"path": "tiles/keep.pmtiles"}}
    old, fresh = NOW - timedelta(days=30), NOW - timedelta(days=1)
    objects = [
        ("scores/keep.bin", old),
        ("scores/stale.bin", old),
        ("scores/new.bin", fresh),
        ("areas/stale.bin", old),
        ("tiles/keep.pmtiles", old),
        ("manifest.json", old),
    ]
    got = publish.prune_candidates(objects, manifest, NOW)
    assert got == ["areas/stale.bin", "scores/stale.bin"]
    # no manifest at all: every old immutable-looking object is unreferenced
    assert "scores/keep.bin" in publish.prune_candidates(objects, None, NOW)


def test_cors_rule_matches_the_contract():
    rule = publish.CORS_RULES["CORSRules"][0]
    assert rule["AllowedMethods"] == ["GET", "HEAD"] and rule["MaxAgeSeconds"] == 86400
    assert "http://localhost:3000" in rule["AllowedOrigins"]
    assert {"Range", "If-Match", "If-None-Match"} == set(rule["AllowedHeaders"])


def test_area_file_round_trip():
    rows = [
        areafile.AreaRow(30, 40.71234, -74.00567, "Soho", "nyc", scores(3)),
        areafile.AreaRow(2, 41.0, -73.5, None, None, scores(9)),
        areafile.AreaRow(11, 40.5, -74.25, "Soho", "northern_nj", scores(1)),
    ]
    data = areafile.encode(rows, "v2.1-handtuned", "2026-10-05T00:00:00+00:00")
    (hlen,) = struct.unpack_from("<I", data, 0)
    assert (4 + hlen) % 4 == 0
    header, back = areafile.decode(data + b"\0" * 7)  # trailing padding is ignored
    assert header["kind"] == "areaScores" and header["count"] == 3
    assert header["factors"] == list(FACTOR_KEYS)
    assert header["names"] == ["Soho"] and header["metros"] == ["northern_nj", "nyc"]
    assert [r.id for r in back] == [2, 11, 30]  # ascending
    by_id = {r.id: r for r in back}
    assert by_id[30].lat == pytest.approx(40.71234) and by_id[30].lon == pytest.approx(-74.00567)
    assert by_id[30].name == "Soho" and by_id[30].metro == "nyc"
    assert by_id[2].name is None and by_id[2].metro is None
    assert by_id[11].scores == scores(1) and by_id[2].scores[4] == 255
    assert len(data) == 4 + hlen + 3 * (4 + 4 + 4 + 2 + 1 + len(FACTOR_KEYS))


def test_area_file_rejects_wrong_score_width_and_foreign_files():
    with pytest.raises(ValueError):
        areafile.encode([areafile.AreaRow(1, 0, 0, None, None, (1, 2))], "v", "t")
    with pytest.raises(ValueError):
        areafile.decode(scorefile.encode([], "v", None))
