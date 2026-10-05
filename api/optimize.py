"""POST /v1/optimize: the multi-destination location optimizer.

Given anchors (an address like work, a brand like "Trader Joe's", a category
like "gym"), find the grid cells that minimise the weekly travel time to all
of them, nearest matching place per anchor.

  cost = sum over anchors of tripsPerWeek x 2 (round trip) x minutes

Minutes are estimated first (straight line x 1.3 circuity / mode speed), then
the best candidates are refined with openrouteservice for walk and drive
(common/ors.py, best-effort). The pure engine (everything above "DB glue")
takes plain dicts so tests need no database or network.
"""

import math
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, field_validator, model_validator

from api.geocoding import geocode_address
from api.mapdata import InvalidMapRequest
from api.priorities import Priorities, parse_priorities
from api.schemas import CamelModel
from common import ors
from common.config import SCORING_WEIGHTS_VERSION
from common.coverage import union_bbox
from common.geo import haversine_m
from common.places import (
    bbox_around,
    places_by_brand_in_box,
    places_by_category_in_box,
)
from common.units import M_PER_MI, format_distance

Mode = Literal["walk", "drive", "transit"]

CIRCUITY = 1.3
WALK_MPH = 3.0
DRIVE_MPH = 25.0
DRIVE_OVERHEAD_MIN = 2.0
TRANSIT_MPH = 15.0  # includes waits
ROUND_TRIP = 2
SPREAD_MI = 1.0
REFINE_POOL = 25
SEARCH_MARGIN_MI = 5.0  # places are searched this far beyond the candidate radius
DEFAULT_RADIUS_MI = 15.0
MAX_RADIUS_MI = 30.0
MAX_ANCHORS = 6
TRANSIT_NOTE = (
    "Transit minutes use precomputed train times (walk + ride + walk) where a rail station is "
    "within 1.5 mi of both ends, and are estimated elsewhere."
)

CATEGORY_WORDS: dict[str, str] = {
    "grocery": "grocery", "groceries": "grocery", "grocery store": "grocery",
    "supermarket": "grocery", "gym": "gym", "fitness": "gym", "cafe": "cafe",
    "cafes": "cafe", "coffee": "cafe", "coffee shop": "cafe", "restaurant": "restaurant",
    "restaurants": "restaurant", "bar": "bar", "bars": "bar", "pub": "bar",
    "transit": "transit", "train": "transit", "station": "transit", "subway": "transit",
    "school": "school", "schools": "school", "gas": "gas_station",
    "gas station": "gas_station", "gas_station": "gas_station",
    "airport": "airport", "airports": "airport",
    "convenience": "convenience_store", "convenience store": "convenience_store",
    "convenience_store": "convenience_store",
}  # fmt: skip
CATEGORY_TRIPS = {"gym": 3.0, "grocery": 1.0}
MODE_WORDS = {"drive": "by car", "walk": "on foot", "transit": "by transit"}


# --------------------------------------------------------------------- wire models


class OptimizeAnchor(CamelModel):
    kind: Literal["address", "brand", "category"]
    query: str = Field(min_length=1, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    trips_per_week: float | None = Field(default=None, gt=0, le=50)
    mode: Mode | None = None

    @field_validator("query")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

    @model_validator(mode="after")
    def _both_or_neither(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class OptimizeRequest(CamelModel):
    anchors: list[OptimizeAnchor] = Field(min_length=1, max_length=MAX_ANCHORS)
    default_mode: Mode = "drive"
    radius_mi: float = Field(default=DEFAULT_RADIUS_MI, gt=0, le=MAX_RADIUS_MI)
    limit: int = Field(default=3, ge=1, le=10)
    factors: str | list[str] | None = None
    weights: str | dict[str, float] | None = None


class OptimizeAnchorResult(CamelModel):
    query: str
    kind: Literal["address", "brand", "category"]
    name: str
    latitude: float
    longitude: float
    minutes: int
    distance_label: str | None
    mode: Mode
    approx: bool


class OptimizeResult(CamelModel):
    latitude: float
    longitude: float
    neighborhood: str | None = None
    area_label: str | None = None
    weekly_minutes: int
    score: int
    anchors: list[OptimizeAnchorResult]


class OptimizeUnresolved(CamelModel):
    query: str
    reason: str


class OptimizeResponse(CamelModel):
    results: list[OptimizeResult]
    assumptions: list[str]
    unresolved: list[OptimizeUnresolved]


class OptimizeInputError(ValueError):
    """Route turns it into 400 invalid_request."""


class OptimizeOutOfCoverage(ValueError):
    """Route turns it into 422 out_of_coverage."""


# ------------------------------------------------------------------- pure engine


@dataclass
class Target:
    name: str
    latitude: float
    longitude: float


@dataclass
class ResolvedAnchor:
    query: str
    kind: str
    mode: str
    trips: float
    targets: list[Target]
    assumed_label: str | None = None  # set when trips was defaulted ("work", or the query)
    category: str | None = None  # category anchors: the precomputed-minutes key


def estimate_minutes(distance_m: float, mode: str) -> float:
    miles = distance_m / M_PER_MI * CIRCUITY
    if mode == "walk":
        return miles / WALK_MPH * 60.0
    if mode == "transit":
        return miles / TRANSIT_MPH * 60.0
    return miles / DRIVE_MPH * 60.0 + DRIVE_OVERHEAD_MIN


class _TargetIndex:
    """Nearest-target lookup over a lat/lon bucket grid, so thousands of
    candidates x thousands of places stays fast without numpy."""

    CELL = 0.02  # degrees, ~2 km

    def __init__(self, targets: list[Target]):
        self.targets = targets
        self.buckets: dict[tuple[int, int], list[int]] = {}
        for i, t in enumerate(targets):
            key = (math.floor(t.latitude / self.CELL), math.floor(t.longitude / self.CELL))
            self.buckets.setdefault(key, []).append(i)

    def _best_in(self, cells, lat: float, lon: float, cos_lat: float, best):
        for key in cells:
            for i in self.buckets.get(key, ()):
                t = self.targets[i]
                dy = t.latitude - lat
                dx = (t.longitude - lon) * cos_lat
                d2 = dy * dy + dx * dx
                if best is None or d2 < best[0]:
                    best = (d2, i)
        return best

    def _scan_all(self, lat: float, lon: float, cos_lat: float) -> int:
        return min(
            range(len(self.targets)),
            key=lambda i: (
                (self.targets[i].latitude - lat) ** 2
                + ((self.targets[i].longitude - lon) * cos_lat) ** 2
            ),
        )

    def nearest(self, lat: float, lon: float) -> int:
        cos_lat = max(0.01, math.cos(math.radians(lat)))
        if len(self.targets) <= 48:
            return self._scan_all(lat, lon, cos_lat)
        ci, cj = math.floor(lat / self.CELL), math.floor(lon / self.CELL)
        min_cell_deg = self.CELL * min(1.0, cos_lat)  # narrowest side, in lat-degree units
        best = None
        for ring in range(600):
            if ring == 0:
                cells = [(ci, cj)]
            else:
                cells = [(ci + dx, cj + ring) for dx in range(-ring, ring + 1)]
                cells += [(ci + dx, cj - ring) for dx in range(-ring, ring + 1)]
                cells += [(ci + ring, cj + dy) for dy in range(-ring + 1, ring)]
                cells += [(ci - ring, cj + dy) for dy in range(-ring + 1, ring)]
            best = self._best_in(cells, lat, lon, cos_lat, best)
            # Anything not yet scanned is at least `ring` narrow cells away.
            if best is not None and best[0] <= (ring * min_cell_deg) ** 2:
                break
        if best is None:  # pathological spread: scan everything
            return self._scan_all(lat, lon, cos_lat)
        return best[1]


def nearest_targets(candidates: list[dict], targets: list[Target]) -> tuple[list[int], list[float]]:
    """For each candidate, (index of the nearest target, haversine metres)."""
    index = _TargetIndex(targets)
    idx, dist = [], []
    for c in candidates:
        i = index.nearest(c["latitude"], c["longitude"])
        t = targets[i]
        idx.append(i)
        dist.append(haversine_m(c["latitude"], c["longitude"], t.latitude, t.longitude))
    return idx, dist


@dataclass
class Evaluation:
    """Per-anchor, per-candidate travel numbers (mutated by ORS refinement)."""

    target_idx: list[list[int]]
    distance_m: list[list[float]]
    minutes: list[list[float]]
    approx: list[list[bool]]

    def cost(self, anchors: list[ResolvedAnchor]) -> list[float]:
        n = len(self.minutes[0]) if self.minutes else 0
        return [
            sum(a.trips * ROUND_TRIP * self.minutes[ai][ci] for ai, a in enumerate(anchors))
            for ci in range(n)
        ]


def evaluate(candidates: list[dict], anchors: list[ResolvedAnchor]) -> Evaluation:
    idx, dist, mins = [], [], []
    for a in anchors:
        i, d = nearest_targets(candidates, a.targets)
        idx.append(i)
        dist.append(d)
        mins.append([estimate_minutes(x, a.mode) for x in d])
    return Evaluation(idx, dist, mins, [[True] * len(candidates) for _ in anchors])


def rank_order(
    candidates: list[dict], cost: list[float], subset: list[int] | None = None
) -> list[int]:
    """Candidate indexes best first: lowest whole-minute cost, then highest composite."""
    pool = range(len(candidates)) if subset is None else subset
    return sorted(
        pool, key=lambda i: (round(float(cost[i])), -(candidates[i].get("composite") or 0.0))
    )


def spread(
    candidates: list[dict], order: list[int], limit: int, min_mi: float = SPREAD_MI
) -> list[int]:
    """Greedy: keep each candidate at least min_mi from those already kept."""
    min_m = min_mi * M_PER_MI
    kept: list[int] = []
    for i in order:
        c = candidates[i]
        if all(
            haversine_m(
                c["latitude"], c["longitude"], candidates[k]["latitude"], candidates[k]["longitude"]
            )
            >= min_m
            for k in kept
        ):
            kept.append(i)
            if len(kept) == limit:
                break
    return kept


def refine_with_ors(
    candidates: list[dict], pool: list[int], anchors: list[ResolvedAnchor], ev: Evaluation
) -> list[int]:
    """Replaces walk/drive estimates with openrouteservice minutes for `pool`
    (one matrix call per mode, shrinking the pool to respect the element cap).
    Returns the pool actually refined (a prefix of `pool`); estimates stay for
    anything ORS could not answer."""
    per_mode: dict[str, dict[tuple[float, float], None]] = {}
    for ai, a in enumerate(anchors):
        if a.mode in ors.PROFILES:
            dests = per_mode.setdefault(a.mode, {})
            for ci in pool:
                t = a.targets[ev.target_idx[ai][ci]]
                dests[(t.latitude, t.longitude)] = None
    if not per_mode or not ors.api_key():
        return pool
    biggest = max(len(d) for d in per_mode.values())
    keep = min(len(pool), ors.MAX_ELEMENTS // max(1, biggest))
    if keep < 1:
        return pool
    pool = pool[:keep]
    sources = [(candidates[ci]["latitude"], candidates[ci]["longitude"]) for ci in pool]
    for mode, dest_map in per_mode.items():
        # Only destinations the shrunken pool still uses.
        used = {
            (a.targets[ev.target_idx[ai][ci]].latitude, a.targets[ev.target_idx[ai][ci]].longitude)
            for ai, a in enumerate(anchors)
            if a.mode == mode
            for ci in pool
        }
        dests = [d for d in dest_map if d in used]
        dest_pos = {d: j for j, d in enumerate(dests)}
        matrix = ors.matrix_minutes(mode, sources, dests)
        if matrix is None:
            continue
        overhead = DRIVE_OVERHEAD_MIN if mode == "drive" else 0.0
        for ai, a in enumerate(anchors):
            if a.mode != mode:
                continue
            for row, ci in enumerate(pool):
                t = a.targets[ev.target_idx[ai][ci]]
                value = matrix[row][dest_pos[(t.latitude, t.longitude)]]
                if value is not None:
                    ev.minutes[ai][ci] = value + overhead
                    ev.approx[ai][ci] = False
    return pool


PRUNE_KEEP = 4 * REFINE_POOL
M_PER_DEG = 111_320.0


def weiszfeld(
    points: list[tuple[float, float]], weights: list[float], iters: int = 50
) -> tuple[float, float]:
    """Weighted geometric median of (lat, lon) points (Weiszfeld's algorithm, in a local
    equirectangular frame): the point minimising sum(weight x distance)."""
    lat0 = sum(p[0] for p in points) / len(points)
    kx = math.cos(math.radians(lat0))
    xy = [(p[1] * kx, p[0]) for p in points]
    x = sum(w * p[0] for w, p in zip(weights, xy, strict=True)) / sum(weights)
    y = sum(w * p[1] for w, p in zip(weights, xy, strict=True)) / sum(weights)
    for _ in range(iters):
        num_x = num_y = den = 0.0
        for w, p in zip(weights, xy, strict=True):
            d = math.hypot(p[0] - x, p[1] - y)
            if d < 1e-9:
                return y, x / kx
            num_x += w * p[0] / d
            num_y += w * p[1] / d
            den += w / d
        nx, ny = num_x / den, num_y / den
        if math.hypot(nx - x, ny - y) < 1e-9:
            x, y = nx, ny
            break
        x, y = nx, ny
    return y, x / kx


def _box_distance_m(lat: float, lon: float, box: tuple[float, float, float, float]) -> float:
    """Straight-line metres from a point to a (min_lat, max_lat, min_lon, max_lon) box (0 inside)."""
    clat = min(max(lat, box[0]), box[1])
    clon = min(max(lon, box[2]), box[3])
    return haversine_m(lat, lon, clat, clon)


def prune_candidates(
    candidates: list[dict], anchors: list[ResolvedAnchor], keep: int = PRUNE_KEEP
) -> list[dict]:
    """Exact lower-bound pruning. Seed: the `keep` candidates nearest the weighted geometric
    median of the anchors get their full straight-line cost; the largest of those is an upper
    bound on the keep-th best cost. Any other candidate whose lower bound (distance to each
    anchor's target bounding box, never more than the real nearest target) already exceeds it
    cannot reach the top `keep`, so it is dropped before the expensive evaluation."""
    if len(candidates) <= keep or not anchors:
        return candidates
    centres = []
    for a in anchors:
        centres.append(_centroid([(t.latitude, t.longitude) for t in a.targets]))
    median = weiszfeld(centres, [a.trips for a in anchors])
    boxes = [
        (
            min(t.latitude for t in a.targets),
            max(t.latitude for t in a.targets),
            min(t.longitude for t in a.targets),
            max(t.longitude for t in a.targets),
        )
        for a in anchors
    ]

    def lower_bound(c) -> float:
        return sum(
            a.trips * ROUND_TRIP * estimate_minutes(_box_distance_m(c["latitude"], c["longitude"], b), a.mode)
            for a, b in zip(anchors, boxes, strict=True)
        )

    seeded = sorted(
        candidates, key=lambda c: haversine_m(median[0], median[1], c["latitude"], c["longitude"])
    )[:keep]
    ev = evaluate(seeded, anchors)
    threshold = max(ev.cost(anchors))
    kept = [c for c in candidates if lower_bound(c) <= threshold]
    return kept if len(kept) >= keep else candidates


def apply_precomputed(
    conn, candidates: list[dict], anchors: list[ResolvedAnchor], ev: Evaluation, pool: list[int]
) -> None:
    """Replace estimates with stored routing minutes where we have them (marks approx False):
    category anchors on walk / drive from cell_travel (nearest place of the category in the cell's
    own travel mode), airports from cell_hubs, and single-address transit anchors from the rail
    matrix (walk + ride + walk)."""
    from api import routing_data

    hashes = {ci: candidates[ci].get("geohash") for ci in pool}
    for ai, a in enumerate(anchors):
        if a.mode in ("walk", "drive") and a.category:
            gh = [h for h in hashes.values() if h]
            overhead = DRIVE_OVERHEAD_MIN if a.mode == "drive" else 0.0
            if a.category == "airport":
                if a.mode != "drive":
                    continue
                found = routing_data.hub_minutes(conn, gh, "airport")
                for ci in pool:
                    hit = found.get(hashes[ci] or "")
                    if hit:
                        ev.minutes[ai][ci] = hit[1] + overhead
                        ev.approx[ai][ci] = False
                continue
            found = routing_data.travel_slots(conn, gh, a.category, 1)
            for ci in pool:
                hit = found.get(hashes[ci] or "")
                if hit and hit[0] == a.mode:
                    ev.minutes[ai][ci] = hit[1] + overhead
                    ev.approx[ai][ci] = False
        elif a.mode == "transit" and len(a.targets) == 1 and a.kind == "address":
            t = a.targets[0]
            trips = routing_data.rail_trips(
                conn, [(candidates[ci]["latitude"], candidates[ci]["longitude"]) for ci in pool], (t.latitude, t.longitude)
            )
            for ci, minutes in zip(pool, trips, strict=True):
                if minutes is not None:
                    ev.minutes[ai][ci] = minutes
                    ev.approx[ai][ci] = False


def build_results(
    candidates: list[dict],
    anchors: list[ResolvedAnchor],
    limit: int,
    use_ors: bool = True,
    conn=None,
) -> list[OptimizeResult]:
    if not candidates or not anchors:
        return []
    candidates = prune_candidates(candidates, anchors)
    ev = evaluate(candidates, anchors)
    order = rank_order(candidates, ev.cost(anchors))
    pool = spread(candidates, order, max(REFINE_POOL, limit))
    if conn is not None:
        apply_precomputed(conn, candidates, anchors, ev, pool)
        pool = spread(candidates, rank_order(candidates, ev.cost(anchors), pool), max(REFINE_POOL, limit))
    if use_ors:
        pool = refine_with_ors(candidates, pool, anchors, ev)
        pool = spread(candidates, rank_order(candidates, ev.cost(anchors), pool), limit)
    else:
        pool = pool[:limit]
    cost = ev.cost(anchors)
    results = []
    for ci in pool[:limit]:
        c = candidates[ci]
        rows = []
        for ai, a in enumerate(anchors):
            t = a.targets[ev.target_idx[ai][ci]]
            rows.append(
                OptimizeAnchorResult(
                    query=a.query,
                    kind=a.kind,
                    name=t.name,
                    latitude=round(t.latitude, 5),
                    longitude=round(t.longitude, 5),
                    minutes=round(float(ev.minutes[ai][ci])),
                    distance_label=format_distance(float(ev.distance_m[ai][ci])),
                    mode=a.mode,
                    approx=bool(ev.approx[ai][ci]),
                )
            )
        results.append(
            OptimizeResult(
                latitude=round(c["latitude"], 5),
                longitude=round(c["longitude"], 5),
                neighborhood=c.get("neighborhood"),
                area_label=c.get("area_label"),
                weekly_minutes=round(float(cost[ci])),
                score=round(c.get("composite") or 0.0),
                anchors=rows,
            )
        )
    return results


def build_assumptions(anchors: list[ResolvedAnchor], results: list[OptimizeResult]) -> list[str]:
    notes = []
    for a in anchors:
        if a.assumed_label is None:
            continue
        n = f"{a.trips:g}"
        trips = "trip" if a.trips == 1 else "trips"
        how = MODE_WORDS[a.mode]
        if a.assumed_label == "work":
            notes.append(f"Assumed {n} work {trips}/week {how}")
        else:
            notes.append(f"Assumed {n} {trips}/week to {a.assumed_label} {how}")
    if any(a.mode == "transit" for a in anchors):
        notes.append(TRANSIT_NOTE)
    if any(r.approx for res in results for r in res.anchors):
        notes.append(
            "Some minutes are estimates: straight line x 1.3, at 3 mph walking, "
            "25 mph driving plus 2 min parking, or 15 mph transit including waits."
        )
    return notes


def default_trips(kind: str, first_address: bool, category: str | None) -> float:
    if kind == "address" and first_address:
        return 5.0
    return CATEGORY_TRIPS.get(category or "", 1.0)


def category_for_word(word: str) -> str | None:
    return CATEGORY_WORDS.get(" ".join(word.lower().replace("-", " ").split()))


# ----------------------------------------------------------------------- DB glue


def _priorities(req: OptimizeRequest) -> Priorities:
    factors = ",".join(req.factors) if isinstance(req.factors, list) else req.factors
    weights = (
        ",".join(f"{k}:{v:g}" for k, v in req.weights.items())
        if isinstance(req.weights, dict)
        else req.weights
    )
    try:
        return parse_priorities(factors, weights)
    except InvalidMapRequest as exc:
        raise OptimizeInputError(str(exc)) from exc


def _in_metro(lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = union_bbox()
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def _targets(places: list[dict]) -> list[Target]:
    return [Target(p["name"], p["latitude"], p["longitude"]) for p in places]


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def fetch_candidates(
    conn, lat: float, lon: float, radius_mi: float, prio: Priorities
) -> list[dict]:
    """Scored grid cells within radius_mi of (lat, lon), with the composite for
    the selected priorities. `neighborhood` is read through to_jsonb so the
    query works before migration 0008 adds the column."""
    radius_m = radius_mi * M_PER_MI
    min_lat, max_lat, min_lon, max_lon = bbox_around(lat, lon, radius_m)
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct on (s.geo_entity_id)
                s.*, ge.latitude, ge.longitude, ge.formatted_address, ge.geohash,
                to_jsonb(ge) ->> 'neighborhood' as neighborhood
            from scores s
            join geo_entities ge on ge.id = s.geo_entity_id
            where ge.latitude between %s and %s and ge.longitude between %s and %s
            order by s.geo_entity_id, (s.weights_version = %s) desc nulls last, s.computed_at desc
            """,
            (min_lat, max_lat, min_lon, max_lon, SCORING_WEIGHTS_VERSION),
        )
        rows = [dict(r) for r in cur]
    out = []
    for r in rows:
        if haversine_m(lat, lon, r["latitude"], r["longitude"]) > radius_m:
            continue
        composite = prio.composite_from_columns(r)
        out.append(
            {
                "geohash": r.get("geohash"),
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
                "neighborhood": r.get("neighborhood"),
                "area_label": r.get("formatted_address"),
                "composite": composite if composite is not None else 0.0,
            }
        )
    return out


def resolve_anchors(
    conn, req: OptimizeRequest
) -> tuple[list[ResolvedAnchor], list[OptimizeUnresolved], tuple[float, float] | None]:
    """Resolves every anchor to target points. Returns (anchors, unresolved,
    search centre). Raises OptimizeOutOfCoverage / OptimizeInputError."""
    unresolved: list[OptimizeUnresolved] = []
    slots: list[ResolvedAnchor | None] = [None] * len(req.anchors)
    first_address = True
    fixed_points: list[tuple[float, float]] = []

    def make(i, a, targets, category=None, fixed_first=False):
        explicit = a.trips_per_week is not None
        trips = a.trips_per_week if explicit else default_trips(a.kind, fixed_first, category)
        label = None
        if not explicit:
            label = "work" if (a.kind == "address" and fixed_first) else a.query
        slots[i] = ResolvedAnchor(
            a.query, a.kind, a.mode or req.default_mode, trips, targets, label
        )

    for i, a in enumerate(req.anchors):
        if a.kind != "address":
            continue
        point = (a.latitude, a.longitude) if a.latitude is not None else geocode_address(a.query)
        if point is None:
            unresolved.append(
                OptimizeUnresolved(query=a.query, reason="Could not find that address.")
            )
            continue
        if not _in_metro(*point):
            raise OptimizeOutOfCoverage(f"{a.query!r} is outside the covered metro area.")
        fixed_points.append(point)
        make(i, a, [Target(a.query, point[0], point[1])], fixed_first=first_address)
        first_address = False

    centre = _centroid(fixed_points) if fixed_points else None
    margin_mi = req.radius_mi + SEARCH_MARGIN_MI
    if centre is not None:
        box = bbox_around(*centre, margin_mi * M_PER_MI)
    else:
        min_lon, min_lat, max_lon, max_lat = union_bbox()
        box = (min_lat, max_lat, min_lon, max_lon)

    brand_hits: dict[int, list[dict]] = {}
    for i, a in enumerate(req.anchors):
        if a.kind != "brand":
            continue
        places = places_by_brand_in_box(conn, a.query, *box)
        if not places:
            unresolved.append(
                OptimizeUnresolved(query=a.query, reason="No matching places found nearby.")
            )
            continue
        brand_hits[i] = places
        top = Counter(p["category"] for p in places).most_common(1)[0][0]
        make(i, a, _targets(places), category=top)

    if centre is None and brand_hits:
        centre = _centroid(
            [(p["latitude"], p["longitude"]) for ps in brand_hits.values() for p in ps]
        )
        box = bbox_around(*centre, margin_mi * M_PER_MI)

    has_category = any(a.kind == "category" for a in req.anchors)
    if centre is None and has_category and not brand_hits and not unresolved:
        raise OptimizeInputError("Provide at least one address or brand anchor to search around.")

    for i, a in enumerate(req.anchors):
        if a.kind != "category":
            continue
        category = category_for_word(a.query)
        if category is None:
            unresolved.append(OptimizeUnresolved(query=a.query, reason="Unknown category."))
            continue
        if centre is None:
            unresolved.append(OptimizeUnresolved(query=a.query, reason="Nothing to search around."))
            continue
        if category == "airport":
            from api import routing_data

            places = [
                {"name": n, "latitude": la, "longitude": lo}
                for n, la, lo in routing_data.airport_targets(conn)
            ]
        else:
            places = places_by_category_in_box(conn, category, *box)
        if not places:
            unresolved.append(
                OptimizeUnresolved(query=a.query, reason="No matching places found nearby.")
            )
            continue
        make(i, a, _targets(places), category=category)
        slots[i].category = category

    return [s for s in slots if s is not None], unresolved, centre


def optimize(conn, req: OptimizeRequest, use_ors: bool = True) -> OptimizeResponse:
    prio = _priorities(req)
    anchors, unresolved, centre = resolve_anchors(conn, req)
    # A typed address that could not be found must be fixed first: ranking
    # around the other anchors alone would answer a different question.
    unresolved_address = any(
        a.kind == "address" and any(u.query == a.query for u in unresolved) for a in req.anchors
    )
    if not anchors or centre is None or unresolved_address:
        return OptimizeResponse(results=[], assumptions=[], unresolved=unresolved)
    candidates = fetch_candidates(conn, centre[0], centre[1], req.radius_mi, prio)
    results = build_results(candidates, anchors, req.limit, use_ors, conn)
    return OptimizeResponse(
        results=results, assumptions=build_assumptions(anchors, results), unresolved=unresolved
    )
