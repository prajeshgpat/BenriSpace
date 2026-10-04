"""AI-written score explanations, strictly grounded in the stored evidence.

The model sees only a JSON evidence packet: the user's selected priorities,
every factor's score and metro percentile, up to two named nearby places (with
feet/miles distances) per selected place-based factor, and the road-bounded
area name. Its output is accepted only if every number appears in the evidence,
no metric unit is used, every capitalised proper noun is in the evidence, no
filler adjective is unearned and the length is sane; otherwise (or on any LLM
failure) callers fall back to the rule-based text in api/explain.py.
"""

import contextlib
import json
import re

from pydantic.alias_generators import to_camel

from api.explain import FACTOR_LABELS
from api.factors import FACTOR_COLUMNS
from api.metro_stats import MetroStats, get_stats
from api.places import places_for_factor
from api.priorities import TOGGLEABLE_FACTORS, Priorities
from api.schemas import SubScores
from common.llm import complete_json, make_cache_key
from common.units import format_distance

PROMPT_VERSION = "expl-v2"
MAX_WORDS = 110  # the prompt asks for 60-90; this only rejects runaway text
MAX_SUMMARY_CHARS = 650
MAX_BULLET_CHARS = 140
MAX_BULLETS = 2
PLACES_PER_FACTOR = 2
PLACE_RADIUS_MI = 1.0
# Selected factors for which named places exist (wire key -> places factor).
PLACE_FACTORS = (
    "grocery", "gym", "cafe", "restaurant", "bar", "shopping", "recreation",
    "gasConvenience", "transit", "school",
)  # fmt: skip
FILLER_PERCENTILE = 95

SYSTEM = (
    "You write a short, honest explanation of a location's convenience scores for a "
    "home-seeker, using ONLY the JSON evidence given. Rules:\n"
    "1. Speak to the user's selected priorities (evidence.priorities) first, in that order. "
    "Factors with selected=false are not priorities: never mention them, except in the "
    "single tradeoff sentence if that is the honest tradeoff.\n"
    "2. Cite at least two named places from evidence.places with their distances, copied "
    "exactly (for example 'Acme Market, 0.3 mi'). If the evidence has fewer than two, cite "
    "all it has. Never invent or alter a place name, street name, number or distance.\n"
    "3. Compare with the metro using each factor's vsMetro text (for example 'top 3% of "
    "the metro'), copied verbatim as a standalone phrase ('grocery access is top 3% of the "
    "metro'); never prefix it with 'ahead of' or 'only', never say 'percentile' and do not "
    "do your own arithmetic.\n"
    "4. Structure of the summary: one or two sentences on the priorities with named "
    "places; then exactly one sentence starting 'Tradeoff:' (one honest weakness from "
    "the evidence, a low score or a weak vsMetro); then exactly one sentence starting "
    "'Tip:' (one concrete suggestion drawn from the evidence, such as a named place to "
    "use or a strength to lean on) that involves only the user's selected priorities. Use the words 'Tradeoff:' and 'Tip:' once each and "
    "no other 'however/but' tradeoff.\n"
    "5. Banned words: excellent, exceptional, outstanding, perfect, excels, shines, "
    "top-tier, convenient lifestyle, everyday amenities. Plain, factual, friendly tone.\n"
    "6. Feet and miles only, exactly as written in the evidence. Write factor names in "
    "lower case. Do not name cities, boroughs or neighbourhoods unless they appear in the "
    "evidence.\n"
    "7. The summary must be between 65 and 85 words. strengths and weaknesses must be "
    "empty lists.\n"
    "Output ONLY a JSON object of the form "
    '{"summary": str, "strengths": [], "weaknesses": []} and nothing else.'
)

BANNED_FILLER_RE = re.compile(
    r"\bexcellent\b|\bexceptional\b|convenient lifestyle|everyday amenities", re.IGNORECASE
)
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_METRIC_RE = re.compile(r"\bkm\b|kilomet|\bmeters?\b|\bmetres?\b|\bm\b", re.IGNORECASE)
# Capitalised word of 2+ letters; a trailing possessive is stripped before lookup.
_PROPER_RE = re.compile(r"[A-Z][A-Za-z'\u2019-]+")
# Words that may be capitalised mid-text without being in the evidence.
ALLOWED_CAPITALISED = frozenset({"Tradeoff", "Tip", "Strengths", "Weaknesses"})


def vs_metro_text(percentile: int) -> str:
    """How a factor compares with the metro, as words the model can quote."""
    if percentile >= 90:
        return f"top {max(1, 100 - percentile)}% of the metro"
    if percentile >= 50:
        return f"ahead of {percentile}% of the metro"
    if percentile < 10:
        return f"bottom {max(1, percentile)}% of the metro"
    return f"ahead of only {percentile}% of the metro"


def build_evidence(
    sub_scores: SubScores,
    nearest_m: dict[str, float | None] | None,
    composite: float,
    place_label: str,
    weights_version: str,
    *,
    priorities: Priorities | None = None,
    stats: MetroStats | None = None,
    places: dict[str, list[dict]] | None = None,
) -> dict:
    """Only factors with a score are included; distances are feet/miles text.
    `stats` adds each factor's metro percentile and median, `places` the named
    places per selected factor ({factor: [{"name", "distance"}]})."""
    selected = set(priorities.factors if priorities else TOGGLEABLE_FACTORS)
    factors = []
    for field, value in sub_scores.model_dump(by_alias=False).items():
        if value is None:
            continue
        key = to_camel(field)
        item = {
            "factor": key,
            "label": FACTOR_LABELS.get(field, field),
            "score": round(value),
            "nearest": format_distance((nearest_m or {}).get(key)),
            "selected": key in selected,
        }
        column = FACTOR_COLUMNS[key]
        if stats and column in stats:
            item["percentile"] = stats[column].percentile(value)
            item["vsMetro"] = vs_metro_text(item["percentile"])
            item["metroMedian"] = round(stats[column].median)
        factors.append(item)
    order = priorities.ordered_by_weight() if priorities else list(TOGGLEABLE_FACTORS)
    labels = {f["factor"]: f["label"] for f in factors}
    evidence: dict = {
        "place": place_label,
        "weightsVersion": weights_version,
        "composite": round(composite),
        "priorities": [labels[k] for k in order if k in labels],
        "factors": factors,
    }
    if places:
        evidence["places"] = {
            labels.get(k, k): v for k, v in places.items() if v and k in selected
        }
    ranked = sorted(
        (f for f in factors if f["selected"] and "metroMedian" in f),
        key=lambda f: f["score"] - f["metroMedian"],
    )
    if ranked:
        evidence["weakestSelected"] = [f["label"] for f in ranked[:2] if f["score"] < f["metroMedian"]]
        evidence["strongestSelected"] = [
            f["label"] for f in reversed(ranked[-2:]) if f["score"] > f["metroMedian"]
        ]
    return evidence


def fetch_priority_places(conn, lat: float, lon: float, factors: list[str]) -> dict[str, list[dict]]:
    """Up to PLACES_PER_FACTOR nearest named places per selected place-based
    factor, as {factor: [{"name", "distance"}]}. Failures just omit a factor."""
    out: dict[str, list[dict]] = {}
    for factor in PLACE_FACTORS:
        if factor not in factors:
            continue
        try:
            rows = places_for_factor(conn, lat, lon, factor, PLACE_RADIUS_MI, PLACES_PER_FACTOR)
        except Exception:  # noqa: BLE001 - places are an enhancement
            with contextlib.suppress(Exception):
                conn.rollback()
            continue
        if rows:
            out[factor] = [{"name": r["name"], "distance": r["distance_label"]} for r in rows]
    return out


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMBER_RE.findall(text)}


def _leaves(node: object):
    if isinstance(node, dict):
        for v in node.values():
            yield from _leaves(v)
    elif isinstance(node, list):
        for v in node:
            yield from _leaves(v)
    elif node is not None and not isinstance(node, bool):
        yield node


def _allowed_numbers(evidence: dict) -> set[str]:
    allowed = {"100"}
    for leaf in _leaves(evidence):
        allowed |= _numbers(str(leaf))
    return allowed


def _norm(text: str) -> str:
    """Lower-case with typographic apostrophes straightened (OSM names use both)."""
    return text.replace("\u2019", "'").lower()


def _evidence_text(evidence: dict) -> str:
    return _norm(json.dumps(evidence, ensure_ascii=False))


def _unknown_proper_nouns(text: str, haystack: str) -> bool:
    """True when a capitalised word that is not at the start of a sentence is
    absent from the evidence text (conservative: invented names are rejected)."""
    for m in _PROPER_RE.finditer(text):
        before = text[: m.start()].rstrip()
        if not before or before[-1] in ".!?:":
            continue  # sentence start: ordinary capitalisation
        word = m.group(0).rstrip("-")
        for suffix in ("'s", "\u2019s"):
            word = word.removesuffix(suffix)
        if word in ALLOWED_CAPITALISED:
            continue
        if _norm(word) not in haystack:
            return True
    return False


def filler_allowed(evidence: dict) -> bool:
    """Praise words are earned only when a selected factor is at/above the
    FILLER_PERCENTILE of the metro."""
    return any(
        f.get("selected") and f.get("percentile", 0) >= FILLER_PERCENTILE
        for f in evidence.get("factors", [])
    )


def validate_output(parsed: object, evidence: dict) -> bool:
    if not isinstance(parsed, dict):
        return False
    summary = parsed.get("summary")
    strengths = parsed.get("strengths", [])
    weaknesses = parsed.get("weaknesses", [])
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY_CHARS:
        return False
    texts = [summary]
    for bullets in (strengths, weaknesses):
        if not isinstance(bullets, list) or len(bullets) > MAX_BULLETS:
            return False
        for b in bullets:
            if not isinstance(b, str) or not b.strip() or len(b) > MAX_BULLET_CHARS:
                return False
            texts.append(b)
    if sum(len(t.split()) for t in texts) > MAX_WORDS:
        return False
    allowed = _allowed_numbers(evidence)
    haystack = _evidence_text(evidence)
    filler_ok = filler_allowed(evidence)
    for text in texts:
        if _METRIC_RE.search(text):
            return False
        if not _numbers(text) <= allowed:
            return False
        if not filler_ok and BANNED_FILLER_RE.search(text):
            return False
        if _unknown_proper_nouns(text, haystack):
            return False
    return True


def format_explanation(parsed: dict) -> str:
    text = parsed["summary"].strip()
    strengths = [s.strip().rstrip(".") for s in parsed.get("strengths") or []]
    weaknesses = [w.strip().rstrip(".") for w in parsed.get("weaknesses") or []]
    if strengths:
        text += f" Strengths: {'; '.join(strengths)}."
    if weaknesses:
        text += f" Weaknesses: {'; '.join(weaknesses)}."
    return text


def ai_explanation(
    conn,
    entity_key: str,
    sub_scores: SubScores,
    nearest_m: dict[str, float | None] | None,
    composite: float,
    place_label: str,
    weights_version: str,
    *,
    priorities: Priorities | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> str | None:
    """Cached, validated AI text, or None (callers use the rule-based text).
    The cache key includes the sorted selected factors; `lat`/`lon` enable the
    named-places evidence."""
    stats = None
    with contextlib.suppress(Exception):
        stats = get_stats(conn, weights_version)
    places = None
    if priorities is not None and lat is not None and lon is not None:
        places = fetch_priority_places(conn, lat, lon, priorities.factors)
    evidence = build_evidence(
        sub_scores, nearest_m, composite, place_label, weights_version,
        priorities=priorities, stats=stats, places=places,
    )  # fmt: skip
    if not evidence["factors"]:
        return None
    cache_key = make_cache_key(
        "explanation",
        PROMPT_VERSION,
        entity_key,
        weights_version,
        priorities.cache_part if priorities else "default",
        evidence,
    )
    parsed = complete_json(
        conn,
        kind="explanation",
        cache_key=cache_key,
        system=SYSTEM,
        user=json.dumps(evidence, separators=(",", ":"), ensure_ascii=False),
        validate=lambda p: validate_output(p, evidence),
        max_tokens=500,
    )
    if parsed is None or not validate_output(parsed, evidence):
        return None
    return format_explanation(parsed)
