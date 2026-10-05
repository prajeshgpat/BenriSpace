"""Shared constants and the compact codec for the Wave 4 routing tables (migration 0016).

Minutes are stored as deci-minutes in smallint arrays (2 bytes a value); -1 means "not
reachable within the search cap". Writers are ingestion/routing/*, readers are
api/routing_data.py and api/isochrone.py, so this module has no heavy imports.
"""

from __future__ import annotations

import math

from common.places import PLACE_CATEGORIES

K_NEAREST = 3  # nearest, 2nd and 3rd nearest place per category
CATEGORIES: tuple[str, ...] = PLACE_CATEGORIES
UNREACHABLE = -1
MAX_DM = 32000  # values above this are stored as UNREACHABLE

MODES = ("walk", "drive")
CAR_DENSITY_PER_SQ_MI = 10_000  # below this a cell's travel mode is car (SCORING.md)

WALK_M_PER_MIN = 80.467  # 3 mph
CIRCUITY = 1.3

# Per-mode search caps (minutes) used by the precompute and the API.
WALK_CAP_MIN = 30.0
DRIVE_CAP_MIN = 45.0
CAP_MIN = {"walk": WALK_CAP_MIN, "drive": DRIVE_CAP_MIN}

AIRPORTS: tuple[tuple[str, str, float, float], ...] = (
    ("JFK", "John F. Kennedy International", 40.6413, -73.7781),
    ("LGA", "LaGuardia", 40.7769, -73.8740),
    ("EWR", "Newark Liberty International", 40.6895, -74.1745),
    ("TEB", "Teterboro", 40.8501, -74.0608),
    ("HPN", "Westchester County", 41.0670, -73.7076),
    ("ISP", "Long Island MacArthur", 40.7952, -73.1002),
    ("SWF", "Stewart International", 41.5041, -74.1048),
    ("BDR", "Igor Sikorsky Memorial", 41.1635, -73.1262),
)
HUB_KINDS = ("airport", "rail")
RAIL_ID_BASE = 1000  # routing_hubs.id: airports 1..99, rail stations 1000+


def category_slot(category: str, k: int = 1) -> int:
    """Index of (category, k-th nearest) in cell_travel.minutes_dm; k is 1-based."""
    if not 1 <= k <= K_NEAREST:
        raise ValueError(f"k must be 1..{K_NEAREST}")
    return CATEGORIES.index(category) * K_NEAREST + (k - 1)


def to_dm(minutes: float | None) -> int:
    """Minutes -> stored deci-minutes (UNREACHABLE for None / non-finite / over the ceiling)."""
    if minutes is None or not math.isfinite(minutes) or minutes < 0:
        return UNREACHABLE
    dm = round(minutes * 10.0)
    return dm if dm <= MAX_DM else UNREACHABLE


def from_dm(value: int | None) -> float | None:
    """Stored deci-minutes -> minutes (None when unreachable)."""
    if value is None or value < 0:
        return None
    return value / 10.0


def meta_blob() -> dict:
    """What routing_meta['layout'] records so readers can verify the array order."""
    return {
        "categories": list(CATEGORIES),
        "k": K_NEAREST,
        "unit": "deci-minutes",
        "neighbor_order": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
        "caps_min": CAP_MIN,
    }
