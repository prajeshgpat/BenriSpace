from ingestion import road_segments as rs


def _way(i, tags, n=3):
    return {
        "type": "way", "id": i, "tags": tags,
        "geometry": [{"lat": 40.0 + k * 0.001, "lon": -74.0} for k in range(n)],
    }  # fmt: skip


def test_classify():
    assert rs.classify({"highway": "motorway"}) == "motorway"
    assert rs.classify({"highway": "primary_link"}) == "primary_link"
    assert rs.classify({"highway": "tertiary"}) is None
    assert rs.classify({"highway": "residential"}) is None
    assert rs.classify({"railway": "rail"}) == "rail"
    assert rs.classify({"railway": "subway"}) is None


def test_parse_ways_flags_dedupes_and_drops():
    data = {
        "elements": [
            _way(1, {"highway": "secondary", "name": "Main St"}),
            _way(1, {"highway": "secondary"}),
            _way(2, {"railway": "rail"}),
            _way(3, {"highway": "residential"}),
            _way(4, {"highway": "motorway"}, n=1),
            {"type": "node", "id": 5},
        ]
    }
    ways = rs.parse_ways(data)
    assert [w["osm_id"] for w in ways] == [1, 2]
    assert ways[0]["is_emergency_route"] is True and ways[0]["name"] == "Main St"
    assert ways[1]["highway"] == "rail" and ways[1]["is_emergency_route"] is False


def test_to_wkt_and_query():
    assert (
        rs.to_wkt([(-74.0, 40.0), (-73.9, 40.1)])
        == "LINESTRING(-74.000000 40.000000, -73.900000 40.100000)"
    )
    q = rs.build_query(40, 41, -74, -73)
    assert 'railway"="rail"' in q and "motorway" in q and "(40,-74,41,-73)" in q
