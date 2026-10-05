-- BenriSpace migration 0019: the persisted compact score file. NOT yet applied. Additive,
-- idempotent. Mirrored into contracts/schema.sql. The API works without it (it falls back to
-- building the file from `scores`, ~8 s on a cold Lambda).
--
--   score_files   one row per weights_version: the gzipped /v1/map/scores body (about 300 KB
--                 for 64k cells) and the ETag it was built for. Written by
--                 `python -m api.scorefile` (the weekly score job runs it after scoring.run);
--                 read by api/scorefile.py when the stored ETag matches the current score
--                 stamp, so a cold request reads one row instead of scanning every score.
-- Each statement below is a single statement (one per semicolon).

create table if not exists score_files (
    weights_version text        primary key,
    etag            text        not null,
    body_gz         bytea       not null,
    computed_at     timestamptz not null default now()
);
