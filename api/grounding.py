"""Grounding checks for LLM text: every number and proper noun must come from
the source data. Used by Ask Benri (api/chat.py) to reject invented figures."""

import re

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Capitalised word of 2+ letters; a trailing possessive is stripped before lookup.
_PROPER_RE = re.compile(r"[A-Z][A-Za-z'’-]+")
# Words that may be capitalised mid-text without being in the source.
ALLOWED_CAPITALISED = frozenset({"Tradeoff", "Tip", "Strengths", "Weaknesses"})


def numbers(text: str) -> set[str]:
    """Every number in the text, with thousands separators dropped."""
    return {m.replace(",", "") for m in _NUMBER_RE.findall(text)}


def norm(text: str) -> str:
    """Lower-case with typographic apostrophes straightened (OSM names use both)."""
    return text.replace("’", "'").lower()


def unknown_proper_nouns(text: str, haystack: str) -> bool:
    """True when a capitalised word that is not at the start of a sentence is
    absent from the (normalised) source text: invented names are rejected."""
    for m in _PROPER_RE.finditer(text):
        before = text[: m.start()].rstrip()
        if not before or before[-1] in ".!?:":
            continue  # sentence start: ordinary capitalisation
        word = m.group(0).rstrip("-")
        for suffix in ("'s", "’s"):
            word = word.removesuffix(suffix)
        if word in ALLOWED_CAPITALISED:
            continue
        if norm(word) not in haystack:
            return True
    return False
