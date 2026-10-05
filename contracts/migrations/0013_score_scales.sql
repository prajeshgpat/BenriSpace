-- BenriSpace migration 0013: per-metro factor scales for on-demand (precision=point) scoring.
-- NOT yet applied to production. Additive only, idempotent. Mirrored into contracts/schema.sql.
-- Run by hand after review; the API works without it (it computes the scales once per
-- Lambda instance from feature_store and caches them, see api/point_score.py).
--
--   score_scales   the p2 / p98 (v2.1; min / max for v2) raw-goodness bounds the scoring
--                  engine normalizes each factor against, per (weights_version, metro_area).
--                  15 rows per metro. Written by scoring/run.py after scoring; lets a
--                  location that is not a grid cell be scored with the same normalization.
--   component      primary | rating | secondary | secondary_rating (scoring/scales.py)
--   factor         the scores column the signal feeds (grocery_score, recreation_score, ...)
-- Each statement below is a single statement (one per semicolon).

create table if not exists score_scales (
    weights_version text             not null,
    metro_area      text             not null,
    factor          text             not null,
    component       text             not null,
    lo              double precision not null,
    hi              double precision not null,
    n               integer          not null default 0,
    computed_at     timestamptz      not null default now(),
    primary key (weights_version, metro_area, factor, component)
);
