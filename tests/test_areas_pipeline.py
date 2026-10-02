"""Whole prototype on the cropped real Manhattan fixture (no network)."""

import json
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from ingestion.areas.blocks import build_blocks
from ingestion.areas.cluster import cluster_blocks
from ingestion.areas.naming import name_clusters
from ingestion.areas.osm_source import SAMPLE_BBOX, parse_layers
from ingestion.areas.validate import compute_metrics

FIXTURE = Path(__file__).parent / "fixtures" / "areas_sample.json"


def test_fixture_pipeline_invariants():
    layers = parse_layers(json.loads(FIXTURE.read_text()), SAMPLE_BBOX)
    bs = build_blocks(layers.roads, layers.water, layers.parks)
    assert bs.stats["blocks"] > 10
    clusters = cluster_blocks(bs)
    naming = name_clusters(clusters, bs.road_edges, layers.places)
    m = compute_metrics(bs, clusters, naming)
    assert m["clusters_crossing_hard_barrier"] == 0
    assert m["every_block_assigned_once"]
    assert m["overlap_area_m2"] < 1.0
    assert m["gap_area_m2"] < 1.0
    assert m["empty_names"] == 0
    assert clusters == sorted(clusters, key=lambda c: c.id)
    # deterministic
    again = cluster_blocks(build_blocks(layers.roads, layers.water, layers.parks))
    assert [c.block_ids for c in again] == [c.block_ids for c in clusters]
