import pytest

pytest.importorskip("shapely")

from ingestion.areas.blocks import build_blocks, split_ways
from ingestion.areas.cluster import cluster_blocks
from ingestion.areas.naming import abbreviate, make_title, name_clusters
from ingestion.areas.types import RoadWay


def test_abbreviate():
    assert abbreviate("West 4th Street") == "W 4th St"
    assert abbreviate("7th Avenue South") == "7th Ave S"
    assert abbreviate("Court Street") == "Court St"
    assert abbreviate("West Street") == "West St"
    assert abbreviate("Broadway") == "Broadway"


def rect(wid0, x0, y0, w, h, names):
    """Closed rectangle of 4 ways: names = (south, east, north, west)."""
    pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    out = []
    for k in range(4):
        a, b = pts[k], pts[(k + 1) % 4]
        nodes = tuple(int(p[0]) * 100_000 + int(p[1]) for p in (a, b))
        out.append(RoadWay(wid0 + k, "residential", names[k], nodes, (a, b)))
    return out


def run(roads, places=None):
    bs = build_blocks(roads)
    clusters = cluster_blocks(bs)
    stats = name_clusters(clusters, bs.road_edges, places)
    return clusters, stats


def test_title_is_longest_street_plus_perpendicular():
    roads = rect(
        1, 0, 0, 120, 80, ("West 4th Street", "7th Avenue South", "West 5th Street", "8th Avenue")
    )
    (c,), stats = run(roads)
    assert c.name.title == "W 4th St & 7th Ave S"
    assert c.name.subtitle == ""
    assert stats["empty_names"] == 0


def test_subtitle_from_place_point():
    roads = rect(1, 0, 0, 120, 80, ("Main Street", "Oak Avenue", "Main Street", "Oak Avenue"))
    (c,), _ = run(roads, places=[("Greenwich Village", 60, 40)])
    assert c.name.subtitle == "Greenwich Village"


def test_duplicates_get_third_street():
    a = rect(1, 0, 0, 120, 80, ("Main Street", "Pine Avenue", "Main Street", "Oak Avenue"))
    b = rect(10, 1000, 0, 120, 80, ("Main Street", "Quay Avenue", "Main Street", "Oak Avenue"))
    clusters, stats = run(a + b)
    titles = [c.name.title for c in clusters]
    assert stats["duplicate_rate_initial"] == 1.0
    assert len(set(titles)) == 2
    assert all(t.count("&") == 2 for t in titles)


def test_unnamed_area_never_empty():
    roads = rect(1, 0, 0, 120, 80, (None, None, None, None))
    (c,), stats = run(roads)
    assert c.name.title == "Area 0" and stats["empty_names"] == 0


def test_make_title_single_street():
    assert make_title([("Main St", 100.0, 0.0)]) == "Main St"
    assert make_title([]) == ""


def test_split_ways_cuts_at_shared_nodes():
    w1 = RoadWay(1, "residential", "A", (1, 2, 3), ((0, 0), (1, 0), (2, 0)))
    w2 = RoadWay(2, "residential", "B", (2, 4), ((1, 0), (1, 1)))
    assert len(split_ways([w1, w2])) == 3
