-- BenriSpace Wave 3 migration: population density + PostGIS foundation. Applied to production on 2026-10-04.
-- Additive only, idempotent. Mirrored into contracts/schema.sql. Run by hand after review.
-- Needs an instance where `create extension postgis` is allowed (Supabase: yes).
--
--   feature_store.pop_density_per_sq_mi / travel_mode   written by ingestion/density.py
--   geo_entities.geom / places.geom      Point(4326), GENERATED from latitude/longitude so
--                                        existing and future inserts stay in sync with no
--                                        code change (the table is rewritten once)
--   areas.geom                           MultiPolygon(4326), backfilled from the GeoJSON in
--                                        areas.geometry; the areas build must set it on insert
--   road_segments                        major roads + rail, written by ingestion/road_segments.py
-- No API query uses these yet. Each statement below is a single statement (one per semicolon).

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
