-- BenriSpace v2 migration (weights_version 'v2-handtuned').
-- Applied to production on 2026-10-02. (Not applied automatically: run by hand
-- against any other target database after review.) Additive only (nullable columns, idempotent), so v1 rows and the
-- deployed v1 code keep working with these columns null.
-- Mirrored into contracts/schema.sql so a fresh database already has them.

alter table feature_store
    add column if not exists restaurant_count_500m int,
    add column if not exists restaurant_nearest_m double precision,
    add column if not exists bar_count_500m int,
    add column if not exists bar_nearest_m double precision,
    add column if not exists whole_foods_nearest_m double precision,
    add column if not exists starbucks_nearest_m double precision,
    add column if not exists target_nearest_m double precision,
    add column if not exists premium_retail_raw double precision,
    add column if not exists emergency_facility_count_1600m int,
    add column if not exists emergency_facility_nearest_m double precision,
    add column if not exists emergency_corridor_facility_raw double precision,
    add column if not exists school_district_geoid text,
    add column if not exists school_district_name text,
    add column if not exists school_district_rating double precision,
    add column if not exists school_rating_source text;

alter table scores
    add column if not exists restaurant_score double precision,
    add column if not exists bar_score double precision,
    add column if not exists premium_retail_score double precision,
    add column if not exists school_proximity_score double precision;
