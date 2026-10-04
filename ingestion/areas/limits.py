"""Size limits for road-bounded areas (single source of truth).

Product rule: "your 10-minute radius dictates your life", so a neighbourhood
area is about one square mile. api/areas.py mirrors MAX_AREA_SQ_MI and
MAX_EXTENT_MI (the API image does not ship `ingestion`); a test asserts the
values are equal.
"""

SQ_M_PER_SQ_MI = 2_589_988.11
M_PER_MI = 1609.344

MAX_AREA_SQ_MI = 0.8  # hard cap on one area
TARGET_TILE_MI = 0.75  # side of the tile grid used to cut oversized faces
MAX_EXTENT_MI = 1.4  # hard cap on the longest side of an area's bounding box
MIN_SLIVER_SQ_MI = 0.02  # smaller faces are merged into a neighbour when the caps allow

MAX_AREA_M2 = MAX_AREA_SQ_MI * SQ_M_PER_SQ_MI
MAX_EXTENT_M = MAX_EXTENT_MI * M_PER_MI
TARGET_TILE_M = TARGET_TILE_MI * M_PER_MI
MIN_SLIVER_M2 = MIN_SLIVER_SQ_MI * SQ_M_PER_SQ_MI
