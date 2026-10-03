-- BenriSpace named places (for "what could improve this score" suggestions).
-- Applied to production on 2026-10-03. Additive only; idempotent.
-- Mirrored into contracts/schema.sql so a fresh database already has it.
--
-- One row per named, scored amenity: OSM POIs (grocery, gym, cafe, restaurant,
-- bar, gas_station, convenience_store, plus brand rows whole_foods/starbucks/
-- target), NCES schools and GTFS transit stops. Unnamed POIs are not stored.
-- Each ingestion job owns its `source` and replaces that source wholesale.

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
