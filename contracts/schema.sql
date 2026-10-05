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
    strava_segment_count_800m  integer,     -- null when Strava isn't configured, not 0 — see docs/SCORING.md
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

    -- v2.1 columns (contracts/migrations/0009_v2_1.sql, not yet applied) — all nullable, imperial units
    shopping_count_1mi int,
    shopping_nearest_ft double precision,
    shopping_variety_count_1mi int,
    shopping_raw double precision,
    park_count_1mi int,
    park_nearest_ft double precision,
    park_largest_sq_ft_half_mi double precision,
    recreation_raw double precision,

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
    -- v2.1 columns (contracts/migrations/0009_v2_1.sql, not yet applied) — nullable.
    -- Traffic is road_score. v2 rows keep Shopping in premium_retail_score and
    -- Recreation in trail_popularity_score (the API reads them as a fallback).
    shopping_score           double precision,
    recreation_score         double precision,
    gas_convenience_score    double precision,

    composite_score     numeric not null,

    -- z-scored sub-score vector for "similar areas" search over pgvector
    -- (contracts/migrations/0007_embeddings.sql; scoring/embeddings.py).
    embedding           vector(14),

    computed_at         timestamptz not null default now(),
    unique (geo_entity_id, weights_version)
);

create index scores_geo_entity_idx on scores (geo_entity_id);
create index scores_weights_version_idx on scores (weights_version);
create index scores_embedding_hnsw_idx on scores using hnsw (embedding vector_l2_ops);

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

-- Shape columns (migration 0006, not yet applied): longest bbox side in metres
-- and Polsby-Popper compactness. Areas are capped at 1.5 sq mi / 2 mi across.
alter table areas
    add column if not exists extent_m double precision,
    add column if not exists compactness double precision;

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

-- Neighborhood names (migration 0008, not yet applied): 'Park Slope, Brooklyn',
-- from OSM place nodes (ingestion/neighborhoods.py).
alter table geo_entities add column if not exists neighborhood text;
alter table areas add column if not exists neighborhood text;

-- Ask BenriSpace chat (migration 0010, not yet applied): messages per visitor per day.
create table if not exists chat_usage (
    visitor_hash text not null,
    day          date not null,
    count        int not null default 0,
    primary key (visitor_hash, day)
);

-- Performance + product tables (migration 0011, not yet applied).
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

-- Population density + PostGIS foundation (migration 0012, not yet applied).
create extension if not exists postgis;

alter table feature_store
    add column if not exists pop_density_per_sq_mi double precision,
    add column if not exists travel_mode text;

alter table geo_entities
    add column if not exists geom geometry(Point, 4326)
        generated always as (st_setsrid(st_makepoint(longitude, latitude), 4326)) stored;

alter table places
    add column if not exists geom geometry(Point, 4326)
        generated always as (st_setsrid(st_makepoint(longitude, latitude), 4326)) stored;

alter table areas
    add column if not exists geom geometry(MultiPolygon, 4326);

update areas
    set geom = st_multi(st_setsrid(st_geomfromgeojson(geometry::text), 4326))
    where geom is null;

create index if not exists geo_entities_geom_idx on geo_entities using gist (geom);

create index if not exists places_geom_idx on places using gist (geom);

create index if not exists areas_geom_idx on areas using gist (geom);

create table if not exists road_segments (
    id                 bigserial primary key,
    osm_id             bigint,
    highway            text,                  -- OSM highway value, or 'rail'
    name               text,
    is_emergency_route boolean not null default false,
    geom               geometry(LineString, 4326)
);

create index if not exists road_segments_geom_idx on road_segments using gist (geom);

create index if not exists road_segments_osm_id_idx on road_segments (osm_id);

-- Per-metro factor scales for on-demand point scoring (migration 0013, not yet applied).
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

-- Compact small road-bounded areas (migration 0014, not yet applied). Geometry only, no
-- jsonb copy and no area_cells; scored by on-demand point sampling.
create table if not exists areas_slim (
    id            integer primary key,
    build_version text,
    metro_area    text,
    geom          geometry(MultiPolygon, 4326) not null,
    area_sq_mi    real,
    extent_mi     real,
    compactness   real,
    bounded_by    text[],
    neighborhood  text
);

create index if not exists areas_slim_geom_idx on areas_slim using gist (geom);

-- Per-category nearest-neighbour search for point scoring (migration 0015, not yet applied).
create extension if not exists btree_gist;
create index if not exists places_category_geom_gist on places using gist (category, geom);

-- Wave 4 routing precompute (migration 0016, not yet applied). Minutes are deci-minutes in
-- smallint arrays; -1 = not reachable. See the migration for the column meanings.
create table if not exists routing_meta (
    key         text primary key,
    value       jsonb not null,
    computed_at timestamptz not null default now()
);

create table if not exists cell_travel (
    geohash     text primary key,
    mode        text not null check (mode in ('walk', 'drive')),
    minutes_dm  smallint[] not null,
    computed_at timestamptz not null default now()
);

create table if not exists cell_graph (
    geohash     text not null,
    mode        text not null check (mode in ('walk', 'drive')),
    latitude    real not null,
    longitude   real not null,
    edges_dm    smallint[] not null,
    primary key (geohash, mode)
);

create index if not exists cell_graph_mode_lat_lon_idx on cell_graph (mode, latitude, longitude);

create table if not exists routing_hubs (
    id          integer primary key,
    kind        text not null check (kind in ('airport', 'rail')),
    code        text not null,
    name        text not null,
    latitude    double precision not null,
    longitude   double precision not null,
    unique (kind, code)
);

create index if not exists routing_hubs_kind_lat_lon_idx on routing_hubs (kind, latitude, longitude);

create table if not exists cell_hubs (
    geohash     text not null,
    kind        text not null check (kind in ('airport', 'rail')),
    hub_ids     integer[] not null,
    minutes_dm  smallint[] not null,
    primary key (geohash, kind)
);

create table if not exists rail_matrix (
    origin_id   integer primary key references routing_hubs (id) on delete cascade,
    minutes_dm  smallint[] not null
);
