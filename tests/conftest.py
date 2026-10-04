"""Shared fixtures. The API's neighborhood lookups hit the database; the route
tests run on fake connections, so by default every lookup returns no labels
(tests that want labels monkeypatch api.lookup.get_neighborhoods_by_geohash)."""

import pytest


@pytest.fixture(autouse=True)
def _no_neighborhood_db(monkeypatch):
    monkeypatch.setattr("api.lookup.get_neighborhoods_by_geohash", lambda conn, geohashes: {})
