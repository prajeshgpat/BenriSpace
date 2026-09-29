import httpx
import pytest

from common.geo import haversine_m
from ingestion import trails as trails_mod
from ingestion.grid import BOUNDING_BOXES
from ingestion.trails import (
    TILE_STEP_DEG,
    TRAIL_RADIUS_M,
    StravaRateLimiter,
    build_bucket_index,
    build_explore_bounds_param,
    build_overpass_trail_query,
    build_strava_segment_points,
    candidates_near,
    compute_cell_osm_trail_features,
    compute_cell_strava_features,
    compute_segment_popularity_raw,
    fetch_explore_segments,
    fetch_segment_detail,
    generate_explore_tiles,
    is_trail_way,
    nearest_and_count,
    nearest_and_count_indexed,
    parse_explore_response,
    parse_segment_detail_response,
    parse_trail_elements,
    refresh_access_token,
    select_detail_call_budget,
    select_segments_for_detail,
    strava_configured,
)

CELL_LAT, CELL_LON = 40.7549, -73.9840  # near midtown Manhattan


# --------------------------------------------------------------------------
# OSM tag classification
# --------------------------------------------------------------------------


def test_is_trail_way_accepts_path_footway_track():
    assert is_trail_way({"highway": "path"}) is True
    assert is_trail_way({"highway": "footway"}) is True
    assert is_trail_way({"highway": "track"}) is True


def test_is_trail_way_accepts_leisure_track():
    assert is_trail_way({"leisure": "track"}) is True


def test_is_trail_way_rejects_foot_no():
    assert is_trail_way({"highway": "path", "foot": "no"}) is False
    assert is_trail_way({"highway": "track", "foot": "no"}) is False


def test_is_trail_way_rejects_unrelated_tags():
    assert is_trail_way({"highway": "residential"}) is False
    assert is_trail_way({"shop": "supermarket"}) is False
    assert is_trail_way({}) is False


# --------------------------------------------------------------------------
# Overpass query / response parsing
# --------------------------------------------------------------------------


def test_build_overpass_trail_query_contains_expected_filters():
    query = build_overpass_trail_query(40.0, 41.0, -74.0, -73.0)
    assert "path|footway|track" in query
    assert 'foot"!="no"' in query
    assert 'leisure"="track"' in query
    assert "out geom;" in query
    assert "40.0,-74.0,41.0,-73.0" in query


def test_parse_trail_elements_segments_a_multi_node_way():
    elements = [
        {
            "type": "way",
            "tags": {"highway": "path"},
            "geometry": [
                {"lat": 40.700, "lon": -73.900},
                {"lat": 40.701, "lon": -73.901},
                {"lat": 40.702, "lon": -73.902},
            ],
        }
    ]
    segments = parse_trail_elements(elements)
    assert len(segments) == 2  # 3 nodes -> 2 consecutive-pair segments
    assert segments[0]["tag"] == "path"
    assert segments[0]["lat"] == pytest.approx((40.700 + 40.701) / 2)


def test_parse_trail_elements_skips_non_trail_ways():
    elements = [
        {
            "type": "way",
            "tags": {"highway": "residential"},
            "geometry": [{"lat": 40.7, "lon": -73.9}, {"lat": 40.701, "lon": -73.901}],
        },
        {
            "type": "way",
            "tags": {"highway": "path", "foot": "no"},
            "geometry": [{"lat": 40.7, "lon": -73.9}, {"lat": 40.701, "lon": -73.901}],
        },
        {"type": "node", "tags": {"highway": "path"}, "lat": 40.7, "lon": -73.9},
    ]
    assert parse_trail_elements(elements) == []


def test_parse_trail_elements_skips_single_node_way():
    elements = [
        {
            "type": "way",
            "tags": {"highway": "path"},
            "geometry": [{"lat": 40.7, "lon": -73.9}],
        }
    ]
    assert parse_trail_elements(elements) == []


# --------------------------------------------------------------------------
# Bucket index / nearest+count (mirrors ingestion/osm_poi.py's approach)
# --------------------------------------------------------------------------


def test_nearest_and_count_empty_is_zero_and_none():
    assert nearest_and_count(CELL_LAT, CELL_LON, []) == (0, None)


def test_nearest_and_count_basic():
    points = [
        {"lat": CELL_LAT + 0.001, "lon": CELL_LON, "tag": "path"},  # ~111m
        {"lat": CELL_LAT + 0.05, "lon": CELL_LON, "tag": "track"},  # far
    ]
    count, nearest = nearest_and_count(CELL_LAT, CELL_LON, points, radius_m=TRAIL_RADIUS_M)
    assert count == 1
    assert nearest == pytest.approx(haversine_m(CELL_LAT, CELL_LON, points[0]["lat"], points[0]["lon"]))


def test_indexed_matches_brute_force():
    import random

    random.seed(42)
    points = [
        {"lat": CELL_LAT + random.uniform(-0.02, 0.02), "lon": CELL_LON + random.uniform(-0.02, 0.02), "tag": "path"}
        for _ in range(200)
    ]
    index = build_bucket_index(points)
    for _ in range(20):
        qlat = CELL_LAT + random.uniform(-0.01, 0.01)
        qlon = CELL_LON + random.uniform(-0.01, 0.01)
        brute = nearest_and_count(qlat, qlon, points)
        indexed = nearest_and_count_indexed(qlat, qlon, points, index)
        assert indexed == brute


def test_candidates_near_finds_neighboring_bucket():
    points = [{"lat": CELL_LAT + 0.014, "lon": CELL_LON, "tag": "path"}]
    index = build_bucket_index(points)
    candidates = candidates_near(index, CELL_LAT, CELL_LON)
    assert points[0] in candidates


def test_compute_cell_osm_trail_features_shape():
    points = [{"lat": CELL_LAT + 0.001, "lon": CELL_LON, "tag": "path"}]
    index = build_bucket_index(points)
    features = compute_cell_osm_trail_features(CELL_LAT, CELL_LON, points, index)
    assert features["running_trail_count_800m"] == 1
    assert features["running_trail_nearest_m"] > 0

    empty_features = compute_cell_osm_trail_features(CELL_LAT, CELL_LON, [], build_bucket_index([]))
    assert empty_features == {"running_trail_count_800m": 0, "running_trail_nearest_m": None}


def test_compute_cell_osm_trail_features_without_index_matches_with_index():
    points = [{"lat": CELL_LAT + 0.003, "lon": CELL_LON, "tag": "path"}]
    with_index = compute_cell_osm_trail_features(CELL_LAT, CELL_LON, points, build_bucket_index(points))
    without_index = compute_cell_osm_trail_features(CELL_LAT, CELL_LON, points, None)
    assert with_index == without_index


# --------------------------------------------------------------------------
# Strava tiling
# --------------------------------------------------------------------------


def test_generate_explore_tiles_covers_all_metro_areas():
    tiles = generate_explore_tiles()
    metro_areas = {t[0] for t in tiles}
    assert metro_areas == {m for m, *_ in BOUNDING_BOXES}
    assert len(tiles) > 0


def test_generate_explore_tiles_stay_within_parent_bbox():
    boxes_by_metro = {m: (min_lat, max_lat, min_lon, max_lon) for m, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES}
    for metro_area, min_lat, max_lat, min_lon, max_lon in generate_explore_tiles():
        p_min_lat, p_max_lat, p_min_lon, p_max_lon = boxes_by_metro[metro_area]
        assert p_min_lat <= min_lat < max_lat <= p_max_lat
        assert p_min_lon <= min_lon < max_lon <= p_max_lon


def test_generate_explore_tiles_count_is_well_under_daily_budget():
    # Documents the arithmetic from the module docstring: at TILE_STEP_DEG,
    # tiling the actual v1 metro bounding boxes produces 227 tiles -- well
    # under STRAVA_DAILY_CALL_BUDGET, leaving room for detail calls.
    tiles = generate_explore_tiles()
    assert len(tiles) == 227
    assert len(tiles) < trails_mod.STRAVA_DAILY_CALL_BUDGET


def test_smaller_tile_step_would_produce_more_tiles():
    coarse = generate_explore_tiles(step_deg=TILE_STEP_DEG)
    fine = generate_explore_tiles(step_deg=TILE_STEP_DEG / 2)
    assert len(fine) > len(coarse)


def test_build_explore_bounds_param_format():
    assert build_explore_bounds_param(40.0, -74.0, 41.0, -73.0) == "40.0,-74.0,41.0,-73.0"


# --------------------------------------------------------------------------
# Strava response parsing
# --------------------------------------------------------------------------


def test_parse_explore_response_extracts_stubs():
    data = {
        "segments": [
            {
                "id": 123,
                "name": "Central Park Loop",
                "start_latlng": [40.77, -73.97],
                "end_latlng": [40.78, -73.96],
                "avg_grade": 1.2,
            },
            {"id": 456, "name": "missing latlng"},  # dropped
        ]
    }
    stubs = parse_explore_response(data)
    assert len(stubs) == 1
    assert stubs[0]["id"] == 123
    assert stubs[0]["start_latlng"] == [40.77, -73.97]


def test_parse_explore_response_empty():
    assert parse_explore_response({}) == []
    assert parse_explore_response({"segments": []}) == []


def test_parse_segment_detail_response_extracts_popularity_fields():
    data = {"id": 123, "athlete_count": 500, "effort_count": 12000, "star_count": 40, "name": "x"}
    parsed = parse_segment_detail_response(data)
    assert parsed == {"id": 123, "athlete_count": 500, "effort_count": 12000, "star_count": 40}


def test_parse_segment_detail_response_defaults_missing_counts_to_zero():
    parsed = parse_segment_detail_response({"id": 1})
    assert parsed == {"id": 1, "athlete_count": 0, "effort_count": 0, "star_count": 0}


def test_compute_segment_popularity_raw_formula():
    assert compute_segment_popularity_raw(100, 1000, 10) == pytest.approx(100 + 0.05 * 1000 + 10)
    assert compute_segment_popularity_raw(0, 0, 0) == 0.0


def test_compute_segment_popularity_raw_monotonic_in_each_input():
    base = compute_segment_popularity_raw(100, 100, 1)
    assert compute_segment_popularity_raw(200, 100, 1) > base
    assert compute_segment_popularity_raw(100, 200, 1) > base
    assert compute_segment_popularity_raw(100, 100, 2) > base


# --------------------------------------------------------------------------
# Detail-call budget selection
# --------------------------------------------------------------------------


def test_select_detail_call_budget_respects_daily_budget():
    budget = select_detail_call_budget(explore_calls_made=227, daily_budget=900, max_detail_calls=700)
    assert budget == 673  # 900 - 227


def test_select_detail_call_budget_respects_hard_cap():
    budget = select_detail_call_budget(explore_calls_made=0, daily_budget=900, max_detail_calls=50)
    assert budget == 50


def test_select_detail_call_budget_never_negative():
    budget = select_detail_call_budget(explore_calls_made=5000, daily_budget=900, max_detail_calls=700)
    assert budget == 0


def test_select_segments_for_detail_dedupes_and_caps():
    tiles = [
        [{"id": 1}, {"id": 2}, {"id": 3}],
        [{"id": 2}, {"id": 4}],
    ]
    selected = select_segments_for_detail(tiles, max_calls=3)
    assert len(selected) == 3
    assert len(set(selected)) == 3


def test_select_segments_for_detail_breadth_first_across_tiles():
    # rank-0 from every tile should be picked before rank-1 of any tile.
    tiles = [
        [{"id": 1}, {"id": 10}],
        [{"id": 2}, {"id": 20}],
        [{"id": 3}, {"id": 30}],
    ]
    selected = select_segments_for_detail(tiles, max_calls=3)
    assert selected == [1, 2, 3]


def test_select_segments_for_detail_zero_budget():
    assert select_segments_for_detail([[{"id": 1}]], max_calls=0) == []


# --------------------------------------------------------------------------
# Strava per-cell aggregation
# --------------------------------------------------------------------------


def test_build_strava_segment_points_uses_midpoint():
    segments = [
        {"start_latlng": [40.0, -74.0], "end_latlng": [40.02, -74.02], "popularity_raw": 12.5},
        {"start_latlng": None, "end_latlng": [1, 1], "popularity_raw": 1.0},  # dropped
    ]
    points = build_strava_segment_points(segments)
    assert len(points) == 1
    assert points[0]["lat"] == pytest.approx(40.01)
    assert points[0]["lon"] == pytest.approx(-74.01)
    assert points[0]["popularity_raw"] == 12.5


def test_compute_cell_strava_features_none_when_nothing_nearby():
    points = [{"lat": CELL_LAT + 1.0, "lon": CELL_LON, "popularity_raw": 50.0}]  # far away
    index = build_bucket_index(points)
    assert compute_cell_strava_features(CELL_LAT, CELL_LON, points, index) is None


def test_compute_cell_strava_features_sums_within_radius():
    points = [
        {"lat": CELL_LAT + 0.001, "lon": CELL_LON, "popularity_raw": 10.0},
        {"lat": CELL_LAT + 0.001, "lon": CELL_LON + 0.0005, "popularity_raw": 5.0},
        {"lat": CELL_LAT + 0.5, "lon": CELL_LON, "popularity_raw": 999.0},  # far, excluded
    ]
    index = build_bucket_index(points)
    result = compute_cell_strava_features(CELL_LAT, CELL_LON, points, index)
    assert result["strava_segment_count_800m"] == 2
    assert result["strava_segment_popularity_raw"] == pytest.approx(15.0)


def test_compute_cell_strava_features_without_index():
    points = [{"lat": CELL_LAT, "lon": CELL_LON, "popularity_raw": 3.0}]
    result = compute_cell_strava_features(CELL_LAT, CELL_LON, points, index=None)
    assert result["strava_segment_count_800m"] == 1


# --------------------------------------------------------------------------
# strava_configured() -- graceful-skip predicate
# --------------------------------------------------------------------------


def test_strava_configured_false_when_any_unset(monkeypatch):
    monkeypatch.setattr(trails_mod.config, "STRAVA_CLIENT_ID", None)
    monkeypatch.setattr(trails_mod.config, "STRAVA_CLIENT_SECRET", "secret")
    monkeypatch.setattr(trails_mod.config, "STRAVA_REFRESH_TOKEN", "token")
    assert strava_configured() is False


def test_strava_configured_true_when_all_set(monkeypatch):
    monkeypatch.setattr(trails_mod.config, "STRAVA_CLIENT_ID", "id")
    monkeypatch.setattr(trails_mod.config, "STRAVA_CLIENT_SECRET", "secret")
    monkeypatch.setattr(trails_mod.config, "STRAVA_REFRESH_TOKEN", "token")
    assert strava_configured() is True


# --------------------------------------------------------------------------
# StravaRateLimiter
# --------------------------------------------------------------------------


class _FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limiter_does_not_sleep_under_limit():
    clock = _FakeClock()
    limiter = StravaRateLimiter(limit=5, window_s=900, sleep_fn=clock.sleep, time_fn=clock.time)
    for _ in range(5):
        limiter.wait()
        clock.now += 1  # small time between calls
    assert clock.sleeps == []


def test_rate_limiter_sleeps_once_limit_exceeded():
    clock = _FakeClock()
    limiter = StravaRateLimiter(limit=3, window_s=900, sleep_fn=clock.sleep, time_fn=clock.time)
    for _ in range(3):
        limiter.wait()
        clock.now += 1
    limiter.wait()  # 4th call should trigger a sleep
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] > 0


def test_rate_limiter_resets_after_window_passes():
    clock = _FakeClock()
    limiter = StravaRateLimiter(limit=2, window_s=100, sleep_fn=clock.sleep, time_fn=clock.time)
    limiter.wait()
    clock.now += 200  # well past the window
    limiter.wait()
    limiter.wait()
    assert clock.sleeps == []  # old calls aged out, never hit the limit


# --------------------------------------------------------------------------
# HTTP glue -- mocked httpx (same pattern as tests/test_airports.py)
# --------------------------------------------------------------------------


def test_refresh_access_token_sends_documented_request_shape():
    captured = {}

    class FakeClient:
        def post(self, url, data, timeout):
            captured["url"] = url
            captured["data"] = data
            return httpx.Response(
                200,
                json={"access_token": "abc123", "expires_at": 999, "refresh_token": "new_refresh"},
                request=httpx.Request("POST", url),
            )

    token = refresh_access_token(FakeClient(), "client_id_val", "client_secret_val", "refresh_val")
    assert token == "abc123"
    assert captured["url"] == trails_mod.STRAVA_TOKEN_URL
    assert captured["data"] == {
        "client_id": "client_id_val",
        "client_secret": "client_secret_val",
        "grant_type": "refresh_token",
        "refresh_token": "refresh_val",
    }


def test_refresh_access_token_raises_on_missing_access_token():
    class FakeClient:
        def post(self, url, data, timeout):
            return httpx.Response(200, json={"error": "invalid_grant"}, request=httpx.Request("POST", url))

    with pytest.raises(RuntimeError):
        refresh_access_token(FakeClient(), "id", "secret", "token")


def test_refresh_access_token_raises_on_http_error():
    class FakeClient:
        def post(self, url, data, timeout):
            return httpx.Response(401, json={"message": "Unauthorized"}, request=httpx.Request("POST", url))

    with pytest.raises(httpx.HTTPStatusError):
        refresh_access_token(FakeClient(), "id", "secret", "token")


def test_fetch_explore_segments_sends_bounds_and_auth_header():
    captured = {}

    class FakeClient:
        def get(self, url, params, headers, timeout):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return httpx.Response(
                200,
                json={"segments": [{"id": 1, "name": "s", "start_latlng": [1, 2], "end_latlng": [3, 4]}]},
                request=httpx.Request("GET", url),
            )

    segments = fetch_explore_segments(FakeClient(), "tok123", 40.0, -74.0, 41.0, -73.0)
    assert len(segments) == 1
    assert captured["url"] == trails_mod.STRAVA_EXPLORE_URL
    assert captured["params"]["bounds"] == "40.0,-74.0,41.0,-73.0"
    assert captured["params"]["activity_type"] == "running"
    assert captured["headers"] == {"Authorization": "Bearer tok123"}


def test_fetch_segment_detail_sends_auth_header():
    captured = {}

    class FakeClient:
        def get(self, url, headers, timeout):
            captured["url"] = url
            captured["headers"] = headers
            return httpx.Response(
                200,
                json={"id": 42, "athlete_count": 10, "effort_count": 100, "star_count": 2},
                request=httpx.Request("GET", url),
            )

    detail = fetch_segment_detail(FakeClient(), "tok123", 42)
    assert detail == {"id": 42, "athlete_count": 10, "effort_count": 100, "star_count": 2}
    assert captured["url"] == "https://www.strava.com/api/v3/segments/42"
    assert captured["headers"] == {"Authorization": "Bearer tok123"}
