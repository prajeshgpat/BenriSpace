-- BenriSpace LLM layer (AI explanations). Applied to production on 2026-10-03.
-- Additive only; idempotent. Mirrored into contracts/schema.sql.
--
-- llm_cache : generated, validated responses keyed by a hash of the evidence
--             (entity, weights_version, scores, prompt version) so the same
--             area is only ever paid for once.
-- llm_usage : one row per paid API call; month-to-date spend drives the
--             monthly budget kill-switch (common/llm.py).

create table if not exists llm_cache (
    cache_key     text primary key,
    kind          text not null,
    response      jsonb not null,
    model         text not null,
    created_at    timestamptz not null default now()
);

create table if not exists llm_usage (
    id             bigserial primary key,
    kind           text not null,
    model          text not null,
    input_tokens   int not null,
    output_tokens  int not null,
    cost_usd       double precision not null,
    created_at     timestamptz not null default now()
);

create index if not exists llm_usage_created_at_idx on llm_usage (created_at);
