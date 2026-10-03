"""Local eval of the AI explanation prompt (NOT run in CI; makes paid Haiku calls).

    .venv/bin/python scripts/eval_explanations.py [--max-calls 30] [--baseline]

For 10 real points x 3 priority sets it builds the real evidence packet from the
live public API (read-only: /v1/area, /v1/places, /v1/map/cells for metro
percentiles), runs api.ai_explain.ai_explanation with a throwaway in-memory
cache (nothing touches the database) and prints each text with a rubric score:

  - at least 2 named places from the evidence (or all of them if fewer exist)
  - exactly one 'Tradeoff:' marker
  - no banned filler adjectives
  - passes validate_output (non-None result)
  - 60-90 words in total

--baseline additionally runs the old expl-v1 prompt on three points for a
before/after comparison. The API key is read by common.llm from the environment
(.env); it is never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import common.config  # noqa: F401  (loads .env)
from api import ai_explain
from api.lookup import sub_scores_from_score_row
from api.mapdata import FACTOR_COLUMNS
from api.metro_stats import ColumnStats, MetroStats
from api.priorities import parse_priorities
from common import llm
from common.units import M_PER_MI

BASE = "https://api.benrispace.com/v1"
POINTS = {
    "Times Square": (40.7580, -73.9855),
    "Park Slope": (40.6710, -73.9777),
    "Princeton": (40.3573, -74.6672),
    "Hoboken": (40.7440, -74.0324),
    "White Plains": (41.0340, -73.7629),
    "Rural CT (Newtown)": (41.4200, -73.4100),
    "Astoria": (40.7644, -73.9235),
    "Stamford": (41.0534, -73.5387),
    "Newark": (40.7357, -74.1724),
    "Montclair": (40.8259, -74.2090),
}
PRIORITY_SETS = {
    "all": None,
    "groceries+transit+cafes": "grocery,transit,cafe",
    "school+gym+quiet": "school,gym,emergencyCorridor",
}
WHOLE_REGION = "-75.6,39.6,-72.0,42.0"
_cache: dict[str, object] = {}


def get_json(path: str, **params) -> dict:
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    if url in _cache:
        return _cache[url]  # type: ignore[return-value]
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    _cache[url] = data
    return data


def build_stats() -> MetroStats:
    """Approximate metro distributions from precision-5 map cells, one factor at a time."""
    stats: MetroStats = {}
    for key, column in FACTOR_COLUMNS.items():
        data = get_json(
            "/map/cells", bbox=WHOLE_REGION, precision=5, factors=key, limit=20000
        )
        values = sorted(v for v in data["scores"] if v is not None)
        if not values:
            continue
        n = len(values)
        mean = sum(values) / n
        std = (sum((v - mean) ** 2 for v in values) / n) ** 0.5
        q = tuple(values[min(n - 1, int(i / 100 * (n - 1) + 0.5))] for i in range(101))
        stats[column] = ColumnStats(mean, std, q)
    return stats


def live_places(conn, lat, lon, factor, radius_mi, limit):
    data = get_json("/places", lat=lat, lon=lon, factor=factor, radiusMi=radius_mi, limit=limit)
    return [{"name": p["name"], "distance_label": p["distanceLabel"]} for p in data["places"]]


class ThrowawayConn:
    """Accepts and ignores every DB call (llm usage logging)."""

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


class Budget:
    def __init__(self, max_calls: int):
        self.max_calls, self.calls = max_calls, 0


def install_memory_llm(budget: Budget, log: list) -> None:
    memory: dict[str, dict] = {}
    llm.get_cached = lambda conn, key: memory.get(key)
    llm._store = lambda conn, key, kind, response, usage: memory.__setitem__(key, response)
    llm.month_spend_usd = lambda conn: 0.0
    real_complete = llm.complete_json

    def counted(conn, kind, cache_key, system, user, validate, max_tokens=500):
        if cache_key not in memory:
            if budget.calls >= budget.max_calls:
                return None  # hard cap on paid calls for this eval run
            budget.calls += 1

        def logged(parsed):
            ok = validate(parsed)
            log.append((ok, parsed))
            return ok

        return real_complete(conn, kind, cache_key, system, user, logged, max_tokens)

    ai_explain.complete_json = counted
    ai_explain.get_stats = lambda conn, version, metro=None: STATS
    ai_explain.places_for_factor = live_places


def word_count(parsed: dict) -> int:
    texts = [parsed["summary"], *(parsed.get("strengths") or []), *(parsed.get("weaknesses") or [])]
    return sum(len(t.split()) for t in texts)


def rubric(text: str | None, parsed: dict | None, evidence: dict) -> dict[str, bool]:
    names = [p["name"] for ps in evidence.get("places", {}).values() for p in ps]
    need = min(2, len(set(names)))
    body = text or ""
    cited = sum(1 for n in set(names) if n.lower() in body.lower())
    return {
        "places>=2": text is not None and cited >= need,
        "one_tradeoff": body.count("Tradeoff:") == 1,
        "no_filler": text is not None
        and (ai_explain.filler_allowed(evidence) or not ai_explain.BANNED_FILLER_RE.search(body)),
        "valid": text is not None,
        "words_60_90": parsed is not None and 60 <= word_count(parsed) <= 90,
    }


def load_point(name: str, lat: float, lon: float) -> dict:
    try:
        area = get_json("/area", lat=lat, lon=lon)
    except urllib.error.HTTPError:  # no road-bounded area (rural): use the grid cell
        area = dict(get_json("/score", lat=lat, lon=lon), address="this location")
    expl = get_json(f"/score/{area['geoEntityId']}/explanation")
    nearest_m = {k: (None if v is None else v * M_PER_MI) for k, v in expl["nearestMi"].items()}
    return {
        "name": name, "lat": lat, "lon": lon, "area": area, "nearest_m": nearest_m,
        "sub": sub_scores_from_score_row(
            {FACTOR_COLUMNS[k]: v for k, v in area["subScores"].items()}
        ),
    }  # fmt: skip


V1_SYSTEM = (
    "You explain a location's convenience score to a home-seeker using ONLY the JSON "
    "evidence given. Never mention any number, place name, brand, or amenity that is not "
    "in the evidence. Use feet and miles exactly as written in the evidence; never use "
    "metric units. Write a summary of 2-3 sentences, then up to 3 short strengths and up "
    "to 3 short weaknesses, each tied to a factor in the evidence. Use a plain, friendly "
    "tone. Output ONLY a JSON object of the form "
    '{"summary": str, "strengths": [str], "weaknesses": [str]} and nothing else.'
)


def run_baseline(point: dict) -> str | None:
    """Old expl-v1 behaviour: plain evidence (no priorities/places/percentiles)."""
    ev = ai_explain.build_evidence(
        point["sub"], point["nearest_m"], point["area"]["compositeScore"],
        point["area"]["address"], point["area"]["weightsVersion"],
    )  # fmt: skip
    slim = {
        "place": ev["place"], "weightsVersion": ev["weightsVersion"], "composite": ev["composite"],
        "factors": [{k: f[k] for k in ("factor", "label", "score", "nearest")} for f in ev["factors"]],
    }  # fmt: skip
    parsed = llm.complete_json(
        ThrowawayConn(), "explanation", "v1:" + point["name"], V1_SYSTEM,
        json.dumps(slim, separators=(",", ":")),
        lambda p: ai_explain.validate_output(p, ev) or True, 450,
    )  # fmt: skip
    return ai_explain.format_explanation(parsed) if parsed else None


STATS: MetroStats = {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=30)
    ap.add_argument("--baseline", action="store_true")
    args = ap.parse_args()
    global STATS
    STATS = build_stats()
    budget, log = Budget(args.max_calls), []
    install_memory_llm(budget, log)
    conn = ThrowawayConn()

    totals: dict[str, int] = {}
    runs = passed = 0
    points = {}
    for name, (lat, lon) in POINTS.items():
        try:
            points[name] = load_point(name, lat, lon)
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] {name}: {type(exc).__name__}: {exc}")
    for name, point in points.items():
        for set_name, factors in PRIORITY_SETS.items():
            pri = parse_priorities(factors)
            n_log = len(log)
            text = ai_explain.ai_explanation(
                conn, f"{name}:{set_name}", point["sub"], point["nearest_m"],
                point["area"]["compositeScore"], point["area"]["address"],
                point["area"]["weightsVersion"],
                priorities=pri, lat=point["lat"], lon=point["lon"],
            )  # fmt: skip
            parsed = next((p for ok, p in reversed(log[n_log:]) if ok), None)
            evidence = ai_explain.build_evidence(
                point["sub"], point["nearest_m"], point["area"]["compositeScore"],
                point["area"]["address"], point["area"]["weightsVersion"],
                priorities=pri, stats=STATS,
                places=ai_explain.fetch_priority_places(conn, point["lat"], point["lon"], pri.factors),
            )  # fmt: skip
            result = rubric(text, parsed, evidence)
            ok = all(result.values())
            runs += 1
            passed += ok
            for k, v in result.items():
                totals[k] = totals.get(k, 0) + v
            print(f"\n=== {name} | {set_name} | {'PASS' if ok else 'FAIL'} {result}")
            print(text or "(rules fallback)")
            for rejected_ok, rejected in log[n_log:]:
                if not rejected_ok:
                    print("  rejected output:", json.dumps(rejected)[:400])
    print(f"\nRubric pass rate: {passed}/{runs} = {100 * passed / max(runs, 1):.0f}%")
    print("Per check:", {k: f"{v}/{runs}" for k, v in totals.items()})
    print(f"Haiku calls made: {budget.calls}")

    if args.baseline:
        for name in ("Times Square", "Hoboken", "Rural CT (Newtown)"):
            if name in points:
                print(f"\n--- expl-v1 baseline: {name}")
                print(run_baseline(points[name]))


if __name__ == "__main__":
    main()
