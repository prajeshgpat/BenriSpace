-- BenriSpace migration 0003: road-bounded areas.
-- Applied to production on 2026-10-02. (Not applied automatically: run by hand
-- against any other database after review.) Additive; two new tables, nothing
-- existing is altered. Mirrored into contracts/schema.sql.
--
-- An area is a face of the network of secondary-and-above roads (secondary,
-- primary, trunk, motorway and their links) closed at the shore by the
-- coastline. `area_cells` maps each area to the geohash6 cells it overlaps so
-- a click can be scored by an area-weighted average of the cells' latest
-- scores, always current with the latest scoring run.

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
