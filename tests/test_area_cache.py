from api.area_cache import TTLCache, point_key, scores_key


def test_ttl_expiry_and_eviction():
    now = [0.0]
    c = TTLCache(ttl_s=10, max_entries=2, clock=lambda: now[0])
    c.put("a", 1)
    assert c.get("a") == 1
    now[0] = 11
    assert c.get("a") is None
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)  # evicts the oldest
    assert c.get("a") is None and c.get("c") == 3


def test_keys():
    assert point_key(40.671004, -73.977701) == point_key(40.671001, -73.977699)
    assert scores_key(5, "v") != scores_key(5, "v", ["gym"])
