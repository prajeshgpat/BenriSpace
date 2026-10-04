"""Airport proximity ingestion job — populates
feature_store.nearest_tier1_airport_code and feature_store.airport_drive_time_min
per docs/ROADMAP.md's "Proximity to tier-1 airports" scoring factor
("Hardcoded list + drive time via routing engine").

Design calls made here (flag if wrong, easy to change):

- **Tier-1 airport list, hardcoded, NYC-metro only.** docs/ROADMAP.md's factor
  table names "JFK, Dulles, SFO-class" as illustrative examples of
  tier-1-caliber commercial airports nationally — not a literal in-scope
  list for a NYC-metro-only v1 (docs/ROADMAP.md's v1 scope: five boroughs, Long
  Island, Westchester, Hudson Valley, northern NJ, Fairfield County CT).
  For this instance the relevant tier-1 airports are the three major
  commercial airports actually inside that service radius: JFK, LaGuardia
  (LGA), and Newark Liberty (EWR). Dulles/SFO are hundreds of miles outside
  the radius and can never be "nearest" for any cell in the grid, so
  they're excluded rather than padding the list with airports that would
  never win. Secondary/regional fields at the metro's edge (Stewart/SWF,
  Islip/ISP) are deliberately left out too — they're not tier-1 commercial
  hubs; easy to add later if scoring wants a separate "regional airport"
  factor.

- **Pluggable routing abstraction** (`DriveTimeRouter` below), because
  Valhalla isn't hosted yet — docs/ROADMAP.md Phase 2 "Requirements from you"
  explicitly defers *where* it runs to a later decision.
  `common.config.VALHALLA_URL` is the signal this job reads: set -> real
  routed drive time via Valhalla's HTTP `/route` API; unset (today's
  reality) -> straight-line-distance fallback via `common.geo.haversine_m`
  converted to an estimated minutes figure using an assumed average speed.
  THE FALLBACK IS A KNOWN-APPROXIMATE PLACEHOLDER, NOT A REAL DRIVE-TIME
  ESTIMATE — see `HaversineFallbackRouter` for the assumed speed and why.
  `get_router()` is the single place that decides which implementation is
  live, so swapping in real Valhalla later (once Phase 2 hosting is
  decided) is a one-place change, not a rewrite of this file.

- **Nearest airport = smallest routed drive time**, not smallest
  straight-line distance, whenever a real router is available — road
  geometry can make a farther-as-the-crow-flies airport the faster drive
  (detours around water, highway access). Under the fallback (no road
  network, straight-line only) "nearest by drive time" and "nearest by
  distance" are the same airport by construction, since the fallback's
  drive time is just a linear transform of distance — but `nearest_airport`
  doesn't special-case this; it always compares whatever
  `drive_time_minutes()` returns, so the logic is identical either way.
"""

import sys
from dataclasses import dataclass

import httpx

from common import config
from common.db import get_connection, iter_geo_entities, upsert_feature_store
from common.geo import haversine_m
from common.ingestion_log import ingestion_job


@dataclass(frozen=True)
class Airport:
    code: str
    name: str
    lat: float
    lon: float


# See module docstring for why these three and not docs/ROADMAP.md's illustrative
# Dulles/SFO examples.
TIER1_AIRPORTS = [
    Airport("JFK", "John F. Kennedy International", 40.6413, -73.7781),
    Airport("LGA", "LaGuardia", 40.7769, -73.8740),
    Airport("EWR", "Newark Liberty International", 40.6895, -74.1745),
]


class DriveTimeRouter:
    """Interface every routing implementation follows: one method, lat/lon
    in, minutes out. `get_router()` is the single place that decides which
    implementation is live, so callers (`nearest_airport`, `run`) never
    branch on VALHALLA_URL themselves — that's the "one-place change" this
    abstraction buys when Phase 2 stands up real Valhalla."""

    def drive_time_minutes(
        self, origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float
    ) -> float:
        raise NotImplementedError


class ValhallaRouter(DriveTimeRouter):
    """Real routed drive time via Valhalla's `/route` HTTP API.

    NOT exercised against a live instance in this sandbox — docs/ROADMAP.md
    Phase 2 "Requirements from you" defers where Valhalla is hosted, so
    VALHALLA_URL is unset here and this path is untestable live. The
    request/response shape below follows Valhalla's documented `/route`
    endpoint, so this should work unchanged the moment Phase 2 sets
    VALHALLA_URL to a real instance — sanity-check this shape against
    whatever Valhalla version/config actually gets deployed.

    Request:  POST {VALHALLA_URL}/route
        {
          "locations": [{"lat": <origin_lat>, "lon": <origin_lon>},
                         {"lat": <dest_lat>, "lon": <dest_lon>}],
          "costing": "auto",
          "units": "kilometers"
        }
    Response: {"trip": {"summary": {"time": <seconds>, "length": <km>}, ...}}
        This code reads `trip.summary.time` (total route seconds) and
        converts to minutes.
    """

    def __init__(self, base_url: str, timeout_s: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def drive_time_minutes(
        self, origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float
    ) -> float:
        payload = {
            "locations": [
                {"lat": origin_lat, "lon": origin_lon},
                {"lat": dest_lat, "lon": dest_lon},
            ],
            "costing": "auto",
            "units": "kilometers",
        }
        response = httpx.post(f"{self.base_url}/route", json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        data = response.json()
        seconds = data["trip"]["summary"]["time"]
        return seconds / 60.0


class HaversineFallbackRouter(DriveTimeRouter):
    """KNOWN-APPROXIMATE PLACEHOLDER — NOT a real drive-time estimate.

    Used whenever VALHALLA_URL is unset (today's reality; Phase 2 hasn't
    decided where Valhalla runs yet — see docs/ROADMAP.md). Converts straight-line
    distance (`common.geo.haversine_m`) to estimated minutes using an
    assumed average speed of **30 mph (~48 km/h)** — a rough blend of
    highway + local-road travel and typical NYC-metro traffic, not measured
    against any real road network.

    This systematically UNDERSTATES real drive time in two compounding
    ways: (1) straight-line distance is always <= actual road distance,
    since real roads detour around water, rail corridors, and highway
    interchanges that are common throughout this metro; (2) 30 mph is
    optimistic for dense in-borough segments near JFK/LGA at typical
    traffic times. Treat `airport_drive_time_min` values produced by this
    fallback as directionally useful (closer airport = lower number) but
    not as an accurate minutes figure. Replace with `ValhallaRouter` the
    moment VALHALLA_URL is set — don't tune this constant to try to "fix"
    the fallback; fix it by standing up real routing instead.
    """

    ASSUMED_AVG_SPEED_KMH = 48.0  # ~30 mph — see class docstring.

    def drive_time_minutes(
        self, origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float
    ) -> float:
        distance_km = haversine_m(origin_lat, origin_lon, dest_lat, dest_lon) / 1000.0
        hours = distance_km / self.ASSUMED_AVG_SPEED_KMH
        return hours * 60.0


def get_router() -> DriveTimeRouter:
    """Single decision point: real Valhalla if VALHALLA_URL is configured,
    straight-line fallback otherwise. Everything downstream is
    routing-implementation-agnostic."""
    if config.VALHALLA_URL:
        return ValhallaRouter(config.VALHALLA_URL)
    return HaversineFallbackRouter()


def nearest_airport(
    lat: float,
    lon: float,
    router: DriveTimeRouter,
    airports: list[Airport] = TIER1_AIRPORTS,
) -> tuple[Airport, float]:
    """Returns (Airport, drive_time_minutes) for the tier-1 airport with the
    smallest routed drive time from (lat, lon). Only a handful of airports
    per call (currently 3) — trivially fast, no need to short-circuit."""
    best: tuple[Airport, float] | None = None
    for airport in airports:
        minutes = router.drive_time_minutes(lat, lon, airport.lat, airport.lon)
        if best is None or minutes < best[1]:
            best = (airport, minutes)
    assert best is not None  # airports list is never empty in practice
    return best


def run() -> None:
    router = get_router()
    with get_connection() as conn, ingestion_job("airports") as ctx:
        count = 0
        for entity in iter_geo_entities(conn):
            airport, minutes = nearest_airport(entity["latitude"], entity["longitude"], router)
            upsert_feature_store(
                conn,
                entity["id"],
                {
                    "nearest_tier1_airport_code": airport.code,
                    "airport_drive_time_min": round(minutes, 2),
                },
            )
            count += 1
        conn.commit()
        ctx.rows_affected = count

    print(f"Updated airport drive-time for {count} geo_entities.", file=sys.stderr)


if __name__ == "__main__":
    run()
