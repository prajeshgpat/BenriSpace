"""p50/p95 latency of the hot endpoints against a running local API.

  AREAS_TABLE=areas_slim AREAS_DATABASE_URL=postgresql://postgres:benri@localhost:5433/postgres \\
    .venv/bin/uvicorn api.main:app --port 8000 &
  .venv/bin/python scripts/bench_endpoints.py --calls 50 [--distinct]

Default cycles 8 fixed points (repeat visits: exercises the in-process caches);
--distinct jitters every call by ~20 m so each call is a cold lookup.
"""

import argparse
import random
import statistics
import time

import httpx

POINTS = [
    (40.6710, -73.9777), (40.7178, -74.0431), (40.8259, -74.2090), (40.8680, -73.4250),
    (40.7484, -73.9857), (40.7282, -73.9942), (40.6892, -73.9442), (40.9176, -73.8000),
]  # fmt: skip
ENDPOINTS = {
    "/v1/score": {},
    "/v1/score?precision=point": {"precision": "point"},
    "/v1/area?precision=point": {"precision": "point"},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--calls", type=int, default=50)
    ap.add_argument("--distinct", action="store_true")
    ap.add_argument("--spread", action="store_true", help="jitter ~1 km: every call a new area")
    a = ap.parse_args()
    rng = random.Random(7)
    with httpx.Client(base_url=a.base, timeout=60) as c:
        for label, extra in ENDPOINTS.items():
            path = label.split("?")[0]
            for lat, lon in POINTS[:2]:  # warm connections / scales
                c.get(path, params={"lat": lat, "lon": lon, **extra})
            ms, bad = [], 0
            for i in range(a.calls):
                lat, lon = POINTS[i % len(POINTS)]
                if a.spread:
                    lat += rng.uniform(-8e-3, 8e-3)
                    lon += rng.uniform(-8e-3, 8e-3)
                elif a.distinct:
                    lat += rng.uniform(-2e-4, 2e-4)
                    lon += rng.uniform(-2e-4, 2e-4)
                t = time.perf_counter()
                r = c.get(path, params={"lat": lat, "lon": lon, **extra})
                ms.append((time.perf_counter() - t) * 1000)
                bad += r.status_code != 200
            ms.sort()
            print(
                f"{label:28s} p50 {statistics.median(ms):6.0f} ms  "
                f"p95 {ms[int(0.95 * len(ms)) - 1]:6.0f} ms  non-200: {bad}"
            )


if __name__ == "__main__":
    main()
