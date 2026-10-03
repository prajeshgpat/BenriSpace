"""Thin, safe wrapper around the Anthropic API for the explanation layer.

Rules this module enforces so callers can stay simple:
- Haiku 4.5 only (cheap, fast); the evidence the model sees is always passed
  in by the caller, and its output must pass the caller's `validate` check.
- Responses are cached in Postgres (llm_cache); a hit costs nothing.
- Every paid call is logged to llm_usage, and calls stop once month-to-date
  spend reaches LLM_MONTHLY_BUDGET_USD (default 5.0).
- `complete_json` never raises: any failure (no key, over budget, timeout,
  invalid JSON, failed validation) returns None so the caller falls back to
  the rule-based text.
"""

import contextlib
import hashlib
import json
import os
import sys
from collections.abc import Callable
from typing import Any

MODEL = "claude-haiku-4-5"
# USD per million tokens (Haiku 4.5).
INPUT_USD_PER_MTOK = 1.0
OUTPUT_USD_PER_MTOK = 5.0
DEFAULT_MONTHLY_BUDGET_USD = 5.0
REQUEST_TIMEOUT_S = 20.0


def monthly_budget_usd() -> float:
    try:
        return float(os.environ.get("LLM_MONTHLY_BUDGET_USD", DEFAULT_MONTHLY_BUDGET_USD))
    except ValueError:
        return DEFAULT_MONTHLY_BUDGET_USD


def api_key() -> str | None:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return key or None


def call_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * INPUT_USD_PER_MTOK + output_tokens * OUTPUT_USD_PER_MTOK) / 1_000_000


def make_cache_key(kind: str, *parts: Any) -> str:
    """Stable hash of everything that should invalidate a cached response."""
    raw = json.dumps([kind, *parts], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def month_spend_usd(conn) -> float:
    with conn.cursor() as cur:
        cur.execute(
            "select coalesce(sum(cost_usd), 0) as spend from llm_usage "
            "where created_at >= date_trunc('month', now())"
        )
        row = cur.fetchone()
    return float(row["spend"]) if row else 0.0


def get_cached(conn, cache_key: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("select response from llm_cache where cache_key = %s", (cache_key,))
        row = cur.fetchone()
    return row["response"] if row else None


def _store(conn, cache_key: str, kind: str, response: dict, usage: tuple[int, int]) -> None:
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute(
            "insert into llm_cache (cache_key, kind, response, model) values (%s, %s, %s, %s) "
            "on conflict (cache_key) do nothing",
            (cache_key, kind, Jsonb(response), MODEL),
        )
        cur.execute(
            "insert into llm_usage (kind, model, input_tokens, output_tokens, cost_usd) "
            "values (%s, %s, %s, %s, %s)",
            (kind, MODEL, usage[0], usage[1], call_cost_usd(*usage)),
        )
    conn.commit()


def _extract_json(text: str) -> dict | None:
    """The first JSON object in the model's text, tolerating code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def complete_json(
    conn,
    kind: str,
    cache_key: str,
    system: str,
    user: str,
    validate: Callable[[dict], bool],
    max_tokens: int = 500,
) -> dict | None:
    """Cached, budget-capped, validated JSON completion. None on any failure."""
    try:
        cached = get_cached(conn, cache_key)
        if cached is not None:
            return cached
        key = api_key()
        if key is None:
            return None
        if month_spend_usd(conn) >= monthly_budget_usd():
            print("llm: monthly budget reached; using rule-based text", file=sys.stderr)
            return None

        import anthropic

        client = anthropic.Anthropic(api_key=key, timeout=REQUEST_TIMEOUT_S, max_retries=1)
        message = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        usage = (message.usage.input_tokens, message.usage.output_tokens)
        text = "".join(b.text for b in message.content if b.type == "text")
        parsed = _extract_json(text)
        if parsed is None or not validate(parsed):
            # Failed output was still paid for: record it, but cache nothing.
            with conn.cursor() as cur:
                cur.execute(
                    "insert into llm_usage (kind, model, input_tokens, output_tokens, cost_usd) "
                    "values (%s, %s, %s, %s, %s)",
                    (kind, MODEL, usage[0], usage[1], call_cost_usd(*usage)),
                )
            conn.commit()
            return None
        _store(conn, cache_key, kind, parsed, usage)
        return parsed
    except Exception as exc:  # noqa: BLE001 - the layer must never break the endpoint
        print(f"llm: {type(exc).__name__}; using rule-based text", file=sys.stderr)
        with contextlib.suppress(Exception):
            conn.rollback()
        return None
