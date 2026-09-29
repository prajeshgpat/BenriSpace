-- BenriSpace feature-store schema (Phase 0 contract)
-- Target: Postgres via Supabase. pgvector extension is enabled here because
-- Phase 3 adds an embedding column to `scores` via a later migration — no
-- separate vector DB needed.
--
-- Three tables, split by concern:
--   geo_entities    identity/geocoding — one row per address/geohash
--   feature_store   raw counts/distances per POI category (Phase 1 ingestion output)
--   scores          normalized sub-scores + composite score (Phase 1 scoring output)
--   ingestion_runs  audit log, one row per ingestion job run (one job per data source)

create extension if not exists vector;

create table geo_entities (
    id              uuid primary key default gen_random_uuid(),
    geohash         text not null unique,
    latitude        double precision not null,
    longitude       double precision not null,
    formatted_address text,
    metro_area      text not null,          -- e.g. 'nyc', 'northern_nj', 'fairfield_ct'
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index geo_entities_metro_area_idx on geo_entities (metro_area);

-- One row per geo_entity per ingestion cycle. Raw values only — no
-- normalization or weighting here, that happens in `scores`.
create table feature_store (
    geo_entity_id   uuid primary key references geo_entities (id) on delete cascade,

    -- POIs (OSM Overpass) — positive factors
    grocery_count_500m         integer,
    grocery_nearest_m          numeric,
    gym_count_500m             integer,
    gym_nearest_m              numeric,
    cafe_count_500m            integer,
    cafe_nearest_m             numeric,

    -- POIs (OSM Overpass) — negative factors
    gas_station_count_500m         integer,
    gas_station_nearest_m          numeric,
    convenience_store_count_500m   integer,
    convenience_store_nearest_m    numeric,

    -- Transit (GTFS static, per agency)
    transit_stop_count_800m    integer,
    transit_nearest_m          numeric,
    transit_agencies           jsonb,       -- e.g. ["mta", "lirr"] serving nearest stop(s)

    -- Schools (NYC Open Data + county sources)
    school_count_1600m         integer,
    school_nearest_m           numeric,
    school_avg_rating_1600m    numeric,

    -- Roads (OSM classification tags)
    road_classification        text,        -- OSM highway=* tag of nearest segment
    congestion_proxy_raw       numeric,      -- raw density/classification signal, not yet normalized
    emergency_corridor_proxy_raw numeric,    -- raw signal, mitigated by street_orientation
    street_orientation        text,         -- 'side_street' | 'facing_corridor' | 'unknown'

    -- Airports (hardcoded tier-1 list + routing engine)
    nearest_tier1_airport_code text,        -- e.g. 'JFK'
    airport_drive_time_min    numeric,

    updated_at                  timestamptz not null default now()
);

-- Precomputed, versioned scores. Never computed live per-request — the API
-- reads from this table only. A new weights_version gets a new row per
-- geo_entity rather than overwriting, so score history is preserved.
create table scores (
    id                  uuid primary key default gen_random_uuid(),
    geo_entity_id       uuid not null references geo_entities (id) on delete cascade,
    weights_version     text not null,       -- e.g. 'v1-handtuned'

    -- Normalized sub-scores, 0-100, direction already applied
    -- (negative factors are inverted before storage so higher is always better)
    grocery_score           numeric,
    gym_score                numeric,
    cafe_score               numeric,
    gas_station_score       numeric,
    convenience_store_score numeric,
    transit_score            numeric,
    school_score             numeric,
    road_score               numeric,
    emergency_corridor_score numeric,
    airport_score            numeric,

    composite_score     numeric not null,

    -- Phase 3 adds: embedding vector(N) here via migration, for
    -- "similar neighborhoods" search over pgvector.

    computed_at         timestamptz not null default now(),
    unique (geo_entity_id, weights_version)
);

create index scores_geo_entity_idx on scores (geo_entity_id);
create index scores_weights_version_idx on scores (weights_version);

-- Audit log for ingestion jobs. Each data source (OSM POIs, each GTFS
-- agency, each school data source, roads, airports) is a separate job —
-- this table tracks their independent run history rather than embedding
-- per-category timestamps into feature_store.
create table ingestion_runs (
    id              uuid primary key default gen_random_uuid(),
    source          text not null,       -- e.g. 'osm_poi', 'gtfs_mta', 'gtfs_lirr', 'gtfs_metro_north', 'gtfs_nj_transit', 'schools_nyc_open_data', 'osm_roads', 'airports'
    status          text not null,       -- 'running' | 'success' | 'failed'
    rows_affected   integer,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    error_message   text
);

create index ingestion_runs_source_idx on ingestion_runs (source);
