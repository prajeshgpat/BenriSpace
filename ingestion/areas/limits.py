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


def configure(
    max_area_sq_mi: float | None = None,
    max_extent_mi: float | None = None,
    target_tile_mi: float | None = None,
    min_sliver_sq_mi: float | None = None,
) -> dict[str, float]:
    """Overrides the caps for this process (the build CLI's --max-area-sq-mi etc. and
    the AREAS_* env vars). Unset arguments keep their current value; the defaults above
    stay as they are, so a plain build is unchanged. limits_apply reads these module
    attributes at call time. Returns the effective caps."""
    global MAX_AREA_SQ_MI, MAX_EXTENT_MI, TARGET_TILE_MI, MIN_SLIVER_SQ_MI
    global MAX_AREA_M2, MAX_EXTENT_M, TARGET_TILE_M, MIN_SLIVER_M2
    if max_area_sq_mi is not None:
        MAX_AREA_SQ_MI = max_area_sq_mi
    if max_extent_mi is not None:
        MAX_EXTENT_MI = max_extent_mi
    if target_tile_mi is not None:
        TARGET_TILE_MI = target_tile_mi
    if min_sliver_sq_mi is not None:
        MIN_SLIVER_SQ_MI = min_sliver_sq_mi
    for v in (MAX_AREA_SQ_MI, MAX_EXTENT_MI, TARGET_TILE_MI):
        if v <= 0:
            raise ValueError("size caps must be positive")
    if MIN_SLIVER_SQ_MI < 0 or MIN_SLIVER_SQ_MI >= MAX_AREA_SQ_MI:
        raise ValueError("min sliver must be in [0, max area)")
    MAX_AREA_M2 = MAX_AREA_SQ_MI * SQ_M_PER_SQ_MI
    MAX_EXTENT_M = MAX_EXTENT_MI * M_PER_MI
    TARGET_TILE_M = TARGET_TILE_MI * M_PER_MI
    MIN_SLIVER_M2 = MIN_SLIVER_SQ_MI * SQ_M_PER_SQ_MI
    return {
        "max_area_sq_mi": MAX_AREA_SQ_MI,
        "max_extent_mi": MAX_EXTENT_MI,
        "target_tile_mi": TARGET_TILE_MI,
        "min_sliver_sq_mi": MIN_SLIVER_SQ_MI,
    }
