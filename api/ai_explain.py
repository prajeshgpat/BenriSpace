"""AI-written score explanations, strictly grounded in the stored evidence.

The model sees only a small JSON evidence object (scores 0-100, distances in
feet/miles, factor labels). Its output is accepted only if every number in it
appears in that evidence and no metric unit is used; otherwise (or on any LLM
failure) callers fall back to the rule-based text in api/explain.py.
"""

import json
import re

from pydantic.alias_generators import to_camel

from api.explain import FACTOR_LABELS
from api.schemas import SubScores
from common.llm import complete_json, make_cache_key
from common.units import format_distance

PROMPT_VERSION = "expl-v1"
MAX_SUMMARY_CHARS = 450
MAX_BULLET_CHARS = 140
MAX_BULLETS = 3

SYSTEM = (
    "You explain a location's convenience score to a home-seeker using ONLY the JSON "
    "evidence given. Never mention any number, place name, brand, or amenity that is not "
    "in the evidence. Use feet and miles exactly as written in the evidence; never use "
    "metric units. Write a summary of 2-3 sentences, then up to 3 short strengths and up "
    "to 3 short weaknesses, each tied to a factor in the evidence. Use a plain, friendly "
    "tone. Output ONLY a JSON object of the form "
    '{"summary": str, "strengths": [str], "weaknesses": [str]} and nothing else.'
)

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_METRIC_RE = re.compile(r"\bkm\b|kilomet|\bmeters?\b|\bmetres?\b|\bm\b", re.IGNORECASE)


def build_evidence(
    sub_scores: SubScores,
    nearest_m: dict[str, float | None] | None,
    composite: float,
    place_label: str,
    weights_version: str,
) -> dict:
    """Only factors with a score are included; distances are feet/miles text."""
    factors = []
    for field, value in sub_scores.model_dump(by_alias=False).items():
        if value is None:
            continue
        key = to_camel(field)
        factors.append(
            {
                "factor": key,
                "label": FACTOR_LABELS.get(field, field),
                "score": round(value),
                "nearest": format_distance((nearest_m or {}).get(key)),
            }
        )
    return {
        "place": place_label,
        "weightsVersion": weights_version,
        "composite": round(composite),
        "factors": factors,
    }


def _numbers(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMBER_RE.findall(text)}


def _allowed_numbers(evidence: dict) -> set[str]:
    allowed = {"100", str(evidence.get("composite"))}
    allowed |= _numbers(str(evidence.get("place") or ""))
    allowed |= _numbers(str(evidence.get("weightsVersion") or ""))
    for item in evidence.get("factors", []):
        if item.get("score") is not None:
            allowed.add(str(item["score"]))
        allowed |= _numbers(item.get("nearest") or "")
        allowed |= _numbers(item.get("label") or "")
    return allowed


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
    allowed = _allowed_numbers(evidence)
    for text in texts:
        if _METRIC_RE.search(text):
            return False
        if not _numbers(text) <= allowed:
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
) -> str | None:
    evidence = build_evidence(sub_scores, nearest_m, composite, place_label, weights_version)
    if not evidence["factors"]:
        return None
    cache_key = make_cache_key("explanation", PROMPT_VERSION, entity_key, weights_version, evidence)
    parsed = complete_json(
        conn,
        kind="explanation",
        cache_key=cache_key,
        system=SYSTEM,
        user=json.dumps(evidence, separators=(",", ":")),
        validate=lambda p: validate_output(p, evidence),
        max_tokens=450,
    )
    if parsed is None or not validate_output(parsed, evidence):
        return None
    return format_explanation(parsed)
