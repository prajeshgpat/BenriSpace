"""Imperial display helpers. Everything user-facing is feet and miles;
internals (column names like *_500m, haversine, radii) stay metric."""

import math

M_PER_MI = 1609.344
FT_PER_M = 3.280839895
KM_PER_MI = M_PER_MI / 1000.0
FEET_STEP = 50
FEET_BELOW_MI = 0.1

# Fixed copy for the radii the product talks about.
_RADIUS_COPY = {500: "~0.3 mi", 800: "0.5 mi", 1600: "1 mi"}


def m_to_ft(meters: float) -> float:
    return meters * FT_PER_M


def m_to_mi(meters: float) -> float:
    return meters / M_PER_MI


def km_to_mi(km: float) -> float:
    return km / KM_PER_MI


def mi_to_km(miles: float) -> float:
    return miles * KM_PER_MI


def _round_half_up(value: float, step: float = 1.0) -> float:
    return math.floor(value / step + 0.5) * step


def format_distance(meters: float | None) -> str | None:
    """'450 ft' under 0.1 mi (feet to the nearest 50), else '0.4 mi'.
    None (or a non-finite/negative value) -> None."""
    if meters is None or not math.isfinite(meters) or meters < 0:
        return None
    miles = m_to_mi(meters)
    if miles < FEET_BELOW_MI:
        return f"{int(_round_half_up(m_to_ft(meters), FEET_STEP))} ft"
    return f"{_round_half_up(miles * 10) / 10:,.1f} mi"


def radius_copy(meters: float) -> str:
    """Short copy for a search radius: 500 -> '~0.3 mi', 800 -> '0.5 mi',
    1600 -> '1 mi'; other radii fall back to one-decimal miles."""
    known = _RADIUS_COPY.get(int(meters)) if float(meters).is_integer() else None
    if known:
        return known
    text = f"{_round_half_up(m_to_mi(meters) * 10) / 10:,.1f}"
    return f"{text.removesuffix('.0')} mi"
