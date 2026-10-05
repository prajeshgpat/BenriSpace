-- BenriSpace migration 0014: areas_slim, a compact table of small road-bounded areas.
-- NOT yet applied. Additive only, idempotent. Mirrored into contracts/schema.sql.
-- Needs PostGIS (migration 0012 creates the extension on Supabase).
--
-- One geometry per area (coordinates on a ~1e-5 degree grid, lightly simplified by the
-- writer ingestion/areas/slim.py) plus a few scalars. No jsonb geometry copy and no
-- area_cells: polygon scores come from on-demand point sampling (api/point_score.py).
-- The API reads it when AREAS_TABLE=areas_slim.

create extension if not exists postgis;

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
