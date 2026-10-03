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

    -- Running/walking trails (OSM trail tags; Strava Segments popularity is
    -- optional and additive — see ingestion/trails.py). Proxy for
    -- popularity/desirability/safety: an actively-used trail network
    -- correlates with a neighborhood people want to be outside in.
    running_trail_count_800m   integer,
    running_trail_nearest_m    numeric,
    strava_segment_count_800m  integer,     -- null when Strava isn't configured, not 0 — see normalization.md
    strava_segment_popularity_raw numeric,  -- aggregate athlete/effort-count signal, null when unavailable

    -- v2 columns (contracts/migrations/0002_v2.sql) — all nullable
    restaurant_count_500m int,
    restaurant_nearest_m double precision,
    bar_count_500m int,
    bar_nearest_m double precision,
    whole_foods_nearest_m double precision,
    starbucks_nearest_m double precision,
    target_nearest_m double precision,
    premium_retail_raw double precision,
    emergency_facility_count_1600m int,
    emergency_facility_nearest_m double precision,
    emergency_corridor_facility_raw double precision,
    school_district_geoid text,
    school_district_name text,
    school_district_rating double precision,
    school_rating_source text,

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
    trail_popularity_score   numeric,
    -- v2 columns (contracts/migrations/0002_v2.sql) — nullable
    restaurant_score         double precision,
    bar_score                double precision,
    premium_retail_score     double precision,
    school_proximity_score   double precision,  -- informational, not a composite factor

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
    source          text not null,       -- e.g. 'grid_generation', 'osm_poi', 'gtfs_transit' (+ per-agency: 'gtfs_mta', 'gtfs_lirr', 'gtfs_metro_north', 'gtfs_nj_transit'), 'schools', 'osm_roads', 'airports', 'scoring'
    status          text not null,       -- 'running' | 'success' | 'failed'
    rows_affected   integer,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    error_message   text
);

create index ingestion_runs_source_idx on ingestion_runs (source);

-- Road-bounded areas (migration 0003): faces of the secondary-and-above road
-- network, scored on demand from the geohash cells they overlap.
create table if not exists areas (
    id            integer primary key,
    build_version text not null,
    metro_area    text,
    min_lat       double precision not null,
    max_lat       double precision not null,
    min_lon       double precision not null,
    max_lon       double precision not null,
    area_sq_m     double precision not null,
    geometry      jsonb not null,          -- GeoJSON Polygon/MultiPolygon, [lon, lat], 5 decimals
    bounded_by    text[] not null default '{}',
    created_at    timestamptz not null default now()
);

create index if not exists areas_bbox_idx on areas (min_lat, max_lat, min_lon, max_lon);

create table if not exists area_cells (
    area_id       integer not null references areas (id) on delete cascade,
    geohash       text not null,
    overlap_sq_m  double precision not null,
    primary key (area_id, geohash)
);

create index if not exists area_cells_geohash_idx on area_cells (geohash);

-- v2 named places (contracts/migrations/0004_places.sql)
create table if not exists places (
    id          bigserial primary key,
    source      text not null,              -- 'osm' | 'nces' | 'gtfs:<agency>'
    source_id   text not null,              -- e.g. 'node/123', NCESSCH, 'stop_id'
    category    text not null,              -- scoring category key (snake_case)
    name        text not null,
    brand       text,
    latitude    double precision not null,
    longitude   double precision not null,
    updated_at  timestamptz not null default now(),
    unique (source, source_id, category)
);

-- Nearby lookups filter a lat/lon box within one category, then rank by distance.
create index if not exists places_category_lat_lon_idx
    on places (category, latitude, longitude);

-- v2 LLM layer (contracts/migrations/0005_llm.sql)
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
