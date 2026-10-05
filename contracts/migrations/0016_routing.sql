-- BenriSpace Wave 4 migration 0016: routing precompute. NOT applied (owner approval needed).
-- Additive only, idempotent, mirrored into contracts/schema.sql. Written by ingestion/routing/*.
-- No PostGIS needed. About 7 MB for the 64k-cell metro (all arrays are smallint / int).
--
-- Minutes are stored as deci-minutes (tenths of a minute) in smallint arrays, so one value is
-- 2 bytes and 3276.7 minutes is the ceiling; -1 means "not reachable within the search cap".
--
--   routing_meta    what the arrays mean (category order, K, speeds, build date), so readers
--                   never depend on a code constant that may have changed since the build
--   cell_travel     one row per cell, in that cell's own travel mode (walk or drive): walk /
--                   drive minutes to the nearest and k-th nearest place of each category,
--                   index = category_index * k + (k - 1)
--   cell_graph      one row per cell and mode: travel minutes to the 8 neighbouring cells
--                   (N, NE, E, SE, S, SW, W, NW) measured on the road network; the API runs
--                   Dijkstra on it for isochrones, so no routing engine is needed at request time
--   routing_hubs    airports and rail stations (ids are stable within a build)
--   cell_hubs       drive minutes from each cell to its nearest hubs of a kind
--   rail_matrix     rail ride minutes between stations: one row per origin station, the array
--                   is aligned with routing_hubs where kind = 'rail' ordered by id

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
