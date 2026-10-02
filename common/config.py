"""Env-var config. Values are unset in production until the account/key
setup in PHASES.md's "Requirements from you" sections is done — code that
needs them should fail loudly (KeyError/explicit check) rather than fall
back to a fake default, so a misconfigured deploy is obvious immediately.
"""

import os

from dotenv import load_dotenv

from scoring.engine import WEIGHTS_VERSION_V1, WEIGHTS_VERSION_V2  # noqa: F401 (re-exported)

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://benrispace:benrispace@localhost:5432/benrispace",
)

# Read directly from the environment at call time by api/suggest.py (so Lambda can
# inject it from SSM before import and tests can unset it); listed here for discovery.
LOCATIONIQ_API_KEY = os.environ.get("LOCATIONIQ_API_KEY")
NJ_TRANSIT_API_KEY = os.environ.get("NJ_TRANSIT_API_KEY")
NJ_TRANSIT_API_USERNAME = os.environ.get("NJ_TRANSIT_API_USERNAME")

# Optional — trail ingestion (ingestion/trails.py) degrades to OSM-only
# trail data when unset, same pattern as NJ Transit above.
STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
STRAVA_REFRESH_TOKEN = os.environ.get("STRAVA_REFRESH_TOKEN")

# Phase 2 — unset until Valhalla hosting is decided (PHASES.md Phase 2
# Requirements). Airport ingestion falls back to straight-line distance
# until this is set.
VALHALLA_URL = os.environ.get("VALHALLA_URL")

# Phase 3 — unset until an LLM provider is decided (PHASES.md Phase 3
# Requirements).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,https://benrispace.com,https://www.benrispace.com",
    ).split(",")
    if origin.strip()
]

# Deployed default stays v1 until v2 data is ingested; the v2 constant is
# for the ingestion workflow / local runs to opt in via the env var.
SCORING_WEIGHTS_VERSION = os.environ.get("SCORING_WEIGHTS_VERSION", WEIGHTS_VERSION_V1)
