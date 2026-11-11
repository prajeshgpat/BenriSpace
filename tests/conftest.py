"""Shared fixtures. The API's neighborhood lookups hit the database; the route
tests run on fake connections, so by default every lookup returns no labels
(tests that want labels monkeypatch api.lookup.get_neighborhoods_by_geohash)."""

import os

# A developer's .env (loaded by common.config at import) may pin SCORING_WEIGHTS_VERSION to the
# production model; the tests assume the code default. dotenv never overrides a set variable,
# so pin the default here, before any test module imports common.config.
os.environ["SCORING_WEIGHTS_VERSION"] = "v2.1-handtuned"

import pytest


@pytest.fixture(autouse=True)
def _no_neighborhood_db(monkeypatch):
    monkeypatch.setattr("api.lookup.get_neighborhoods_by_geohash", lambda conn, geohashes: {})


@pytest.fixture(autouse=True)
def _no_local_areas_env(monkeypatch):
    """A developer's .env may set AREAS_TABLE=areas_slim (loaded by common.config), which
    switches /v1/area to the areas_slim path; tests that want it set the variables themselves."""
    monkeypatch.delenv("AREAS_TABLE", raising=False)
    monkeypatch.delenv("AREAS_DATABASE_URL", raising=False)
