-- BenriSpace performance + product tables migration. NOT yet applied.
-- Additive only, idempotent. Mirrored into contracts/schema.sql.
-- Run by hand after review; the API works without it (each feature falls back
-- while its index or table is missing, see api/similar.py, api/feedback.py).
--
--   geo_entities (latitude, longitude)   bounding-box queries stop scanning 64k rows
--   pg_trgm + GIN on lower(places.name / brand)   indexed brand search ("trader joe")
--   scores (weights_version, geo_entity_id) INCLUDE (composite_score)   covering index
--   similar_cells   top-20 similar cells per cell, written by scoring/embeddings.py
--   feedback        thumbs / reports from the web app (POST /v1/feedback)
-- Each statement below is a single statement (one per semicolon).

create index if not exists geo_entities_lat_lon_idx on geo_entities (latitude, longitude);

create extension if not exists pg_trgm;

create index if not exists places_name_trgm_idx on places using gin (lower(name) gin_trgm_ops);

create index if not exists places_brand_trgm_idx on places using gin (lower(brand) gin_trgm_ops);

create index if not exists scores_version_entity_cover_idx
    on scores (weights_version, geo_entity_id) include (composite_score);

create table if not exists similar_cells (
    geo_entity_id   uuid not null references geo_entities (id) on delete cascade,
    weights_version text not null,
    neighbor_id     uuid not null references geo_entities (id) on delete cascade,
    rank            smallint not null,
    distance        real not null,
    primary key (geo_entity_id, weights_version, rank)
);

create table if not exists feedback (
    id           bigserial primary key,
    kind         text not null check (kind in ('summary', 'chat', 'place')),
    target       text,
    rating       smallint,
    message      text,
    visitor_hash text not null,
    created_at   timestamptz not null default now()
);
