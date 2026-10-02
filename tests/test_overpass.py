from types import SimpleNamespace

import httpx
import pytest

from common import overpass

REQUEST = httpx.Request("POST", overpass.OVERPASS_URL)


def _response(status: int, headers: dict | None = None, json: dict | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers, json=json or {}, request=REQUEST)


class Harness:
    """Scripted responses plus a fake clock, so retry/backoff logic is tested
    without sleeping or hitting the network. Each scripted item is
    (response, seconds_the_call_took)."""

    def __init__(self, monkeypatch, script):
        self.script = list(script)
        self.now = 0.0
        self.sleeps: list[float] = []
        self.calls = 0

        def fake_post(url, **kwargs):
            response, took = self.script[self.calls]
            self.calls += 1
            self.now += took
            return response

        def fake_sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds

        monkeypatch.setattr(overpass.httpx, "post", fake_post)
        monkeypatch.setattr(
            overpass, "time", SimpleNamespace(monotonic=lambda: self.now, sleep=fake_sleep)
        )

    def run(self):
        return overpass.post_overpass_query("[out:json];", timeout=30)


def test_success_returns_json_without_sleeping(monkeypatch):
    h = Harness(monkeypatch, [(_response(200, json={"elements": [1]}), 2)])
    assert h.run() == {"elements": [1]}
    assert h.sleeps == []


def test_fast_504_is_retried_then_succeeds(monkeypatch):
    # A 504 in 5s = the public server is busy, not that our query is too big.
    h = Harness(monkeypatch, [(_response(504), 5), (_response(200, json={"ok": True}), 3)])
    assert h.run() == {"ok": True}
    assert h.sleeps == [overpass.BUSY_BACKOFF_S]


def test_busy_backoff_grows_and_gives_up_after_the_limit(monkeypatch):
    h = Harness(monkeypatch, [(_response(503), 1)] * (overpass.MAX_BUSY_RETRIES + 1))
    with pytest.raises(httpx.HTTPStatusError):
        h.run()
    assert h.sleeps == [30.0, 60.0, 90.0]
    assert h.calls == overpass.MAX_BUSY_RETRIES + 1


def test_slow_504_is_not_retried_so_callers_can_split_the_query(monkeypatch):
    # 120s before the gateway gave up = the query was too big. Retrying the
    # identical query would waste minutes; roads.py / trails.py split the bbox.
    h = Harness(monkeypatch, [(_response(504), 120)])
    with pytest.raises(httpx.HTTPStatusError):
        h.run()
    assert h.sleeps == []
    assert h.calls == 1


def test_429_honours_retry_after(monkeypatch):
    h = Harness(
        monkeypatch,
        [(_response(429, headers={"Retry-After": "7"}), 1), (_response(200, json={"ok": 1}), 1)],
    )
    assert h.run() == {"ok": 1}
    assert h.sleeps == [7.0]


def test_429_falls_back_to_default_wait_and_gives_up_after_the_limit(monkeypatch):
    h = Harness(monkeypatch, [(_response(429), 1)] * (overpass.MAX_RATE_LIMIT_RETRIES + 1))
    with pytest.raises(httpx.HTTPStatusError):
        h.run()
    assert h.sleeps == [overpass.DEFAULT_RETRY_AFTER_S] * overpass.MAX_RATE_LIMIT_RETRIES


def test_client_errors_are_not_retried(monkeypatch):
    h = Harness(monkeypatch, [(_response(400), 1)])
    with pytest.raises(httpx.HTTPStatusError):
        h.run()
    assert h.sleeps == []
