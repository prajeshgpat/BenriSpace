"""The covered metro area, as bounding boxes: the single source of truth.

Lives in common/ because both sides need it: ingestion builds the geohash grid
from these boxes, and the API restricts address suggestions to them.
scripts/build_lambda.sh ships api/common/scoring but not ingestion, so it
can't live in either of those.
"""

BOUNDING_BOXES: list[tuple[str, float, float, float, float]] = [
    ("nyc", 40.49, 40.92, -74.26, -73.70),
    ("long_island", 40.55, 41.20, -73.75, -71.85),
    ("westchester", 40.87, 41.40, -73.95, -73.60),
    ("hudson_valley", 41.10, 42.00, -74.50, -73.60),
    ("northern_nj", 39.85, 41.10, -75.20, -73.90),
    ("fairfield_ct", 40.95, 41.40, -73.75, -73.05),
]


def union_bbox() -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat) enclosing every covered box."""
    return (
        min(b[3] for b in BOUNDING_BOXES),
        min(b[1] for b in BOUNDING_BOXES),
        max(b[4] for b in BOUNDING_BOXES),
        max(b[2] for b in BOUNDING_BOXES),
    )


def metro_center() -> tuple[float, float]:
    """(lat, lon) centre of the first (densest) covered box, used to bias
    geocoder results toward the middle of the metro."""
    _, min_lat, max_lat, min_lon, max_lon = BOUNDING_BOXES[0]
    return (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
