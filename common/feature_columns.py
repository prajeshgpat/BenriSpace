"""feature_store column names in imperial units (migrations 0020 / 0021) and the boundary
that translates them.

Ingestion jobs, the scoring engine and point scoring compute in the units they always
did: distances in metres, counts within 500 m / 800 m / 1600 m, under the original
`*_nearest_m` / `*_count_500m` keys. Only the database changed: the columns are now
`*_nearest_ft` (feet, real) and `*_count_1600ft` / `*_count_half_mi` / `*_count_1mi`
(smallint). This module is the single place that knows both spellings:

    to_db_fields(fields)   ingestion write: legacy keys -> new columns, metres -> feet
    from_db_row(row)       any read: new columns -> legacy keys, feet -> metres (the new
                           keys stay in the row too)

so a typo or a missed rename shows up as one failing test, not as silently wrong scores.
The metre / feet conversions are exact inverses up to the stored `real` precision (about
7 significant digits, under a millimetre for any distance we store).
"""

from collections.abc import Iterable, Mapping

FT_PER_M = 3.280839895

# Cell-radius counts: same value, new name (the radius in the name is now imperial).
_COUNT_RENAMES: dict[str, str] = {
    "grocery_count_500m": "grocery_count_1600ft",
    "gym_count_500m": "gym_count_1600ft",
    "cafe_count_500m": "cafe_count_1600ft",
    "gas_station_count_500m": "gas_station_count_1600ft",
    "convenience_store_count_500m": "convenience_store_count_1600ft",
    "restaurant_count_500m": "restaurant_count_1600ft",
    "bar_count_500m": "bar_count_1600ft",
    "transit_stop_count_800m": "transit_stop_count_half_mi",
    "running_trail_count_800m": "running_trail_count_half_mi",
    "strava_segment_count_800m": "strava_segment_count_half_mi",
    "school_count_1600m": "school_count_1mi",
    "emergency_facility_count_1600m": "emergency_facility_count_1mi",
    "school_avg_rating_1600m": "school_avg_rating_1mi",  # a rating, not a count: no conversion
}

# Nearest distances: value x FT_PER_M under the new name.
_DISTANCE_RENAMES: dict[str, str] = {
    f"{stem}_nearest_m": f"{stem}_nearest_ft"
    for stem in (
        "grocery",
        "gym",
        "cafe",
        "gas_station",
        "convenience_store",
        "transit",
        "school",
        "running_trail",
        "restaurant",
        "bar",
        "whole_foods",
        "starbucks",
        "target",
        "emergency_facility",
    )
}

# legacy key -> new column
RENAMES: dict[str, str] = {**_COUNT_RENAMES, **_DISTANCE_RENAMES}
# new column -> legacy key
LEGACY_BY_NEW: dict[str, str] = {new: old for old, new in RENAMES.items()}
DISTANCE_COLUMNS: frozenset[str] = frozenset(_DISTANCE_RENAMES.values())


def new_name(column: str) -> str:
    """The database column for a legacy key (other names pass through)."""
    return RENAMES.get(column, column)


def to_db_fields(fields: Mapping) -> dict:
    """An ingestion job's {legacy or new key: value} as {database column: value}."""
    out = {}
    for key, value in fields.items():
        column = RENAMES.get(key, key)
        if key in _DISTANCE_RENAMES and value is not None:
            value = round(float(value) * FT_PER_M, 1)
        out[column] = value
    return out


def from_db_row(row: Mapping | None) -> dict | None:
    """A database row with the legacy metre keys added next to the new columns."""
    if row is None:
        return None
    out = dict(row)
    for new, old in LEGACY_BY_NEW.items():
        if new not in out:
            continue
        value = out[new]
        if value is not None and new in DISTANCE_COLUMNS:
            value = float(value) / FT_PER_M
        out[old] = value
    return out


def from_db_rows(rows: Iterable[Mapping]) -> list[dict]:
    return [from_db_row(r) for r in rows]
