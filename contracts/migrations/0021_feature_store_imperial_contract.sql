-- BenriSpace migration 0021 (Wave 3, step 2 of 2): imperial feature_store columns, CONTRACT.
-- NOT yet applied. DESTRUCTIVE and irreversible: drops the metric columns that 0020 replaced.
-- Run it only after the code that reads the new columns is deployed and an ingestion / scoring
-- run has succeeded. Mirrored into contracts/schema.sql.
--
-- One ALTER TABLE: the old columns go and the remaining numeric / double precision columns
-- are narrowed to real (and the v2.1 integer counts to smallint) in a single table rewrite,
-- which also returns the space of the dropped columns (no `vacuum full` needed). It needs
-- free room for the new copy (about 35 MB at 64k cells). Raw signals and densities keep
-- about 7 significant digits as real; airport_drive_time_min stays numeric.
-- Each statement below is a single statement (one per semicolon).

alter table feature_store
    drop column if exists grocery_count_500m,
    drop column if exists gym_count_500m,
    drop column if exists cafe_count_500m,
    drop column if exists gas_station_count_500m,
    drop column if exists convenience_store_count_500m,
    drop column if exists restaurant_count_500m,
    drop column if exists bar_count_500m,
    drop column if exists transit_stop_count_800m,
    drop column if exists running_trail_count_800m,
    drop column if exists strava_segment_count_800m,
    drop column if exists school_count_1600m,
    drop column if exists emergency_facility_count_1600m,
    drop column if exists school_avg_rating_1600m,
    drop column if exists grocery_nearest_m,
    drop column if exists gym_nearest_m,
    drop column if exists cafe_nearest_m,
    drop column if exists gas_station_nearest_m,
    drop column if exists convenience_store_nearest_m,
    drop column if exists transit_nearest_m,
    drop column if exists school_nearest_m,
    drop column if exists running_trail_nearest_m,
    drop column if exists restaurant_nearest_m,
    drop column if exists bar_nearest_m,
    drop column if exists whole_foods_nearest_m,
    drop column if exists starbucks_nearest_m,
    drop column if exists target_nearest_m,
    drop column if exists emergency_facility_nearest_m,
    alter column congestion_proxy_raw type real,
    alter column emergency_corridor_proxy_raw type real,
    alter column strava_segment_popularity_raw type real,
    alter column premium_retail_raw type real,
    alter column emergency_corridor_facility_raw type real,
    alter column school_district_rating type real,
    alter column shopping_nearest_ft type real,
    alter column shopping_raw type real,
    alter column park_nearest_ft type real,
    alter column park_largest_sq_ft_half_mi type real,
    alter column recreation_raw type real,
    alter column pop_density_per_sq_mi type real,
    alter column shopping_count_1mi type smallint,
    alter column shopping_variety_count_1mi type smallint,
    alter column park_count_1mi type smallint;
