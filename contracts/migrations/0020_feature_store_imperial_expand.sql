-- BenriSpace migration 0020 (Wave 3, step 1 of 2): imperial feature_store columns, EXPAND.
-- NOT yet applied. Additive and idempotent; old columns are untouched. Mirrored into
-- contracts/schema.sql (as the final shape, after 0021).
--
-- Renames, in the owner's imperial convention (docs/PLANNED.md Wave 3):
--   *_count_500m  -> *_count_1600ft   *_count_800m -> *_count_half_mi
--   *_count_1600m -> *_count_1mi      school_avg_rating_1600m -> school_avg_rating_1mi
--   *_nearest_m   -> *_nearest_ft     (value x 3.280839895, one decimal)
-- New columns are also narrower: counts smallint, distances and ratings real. The feature
-- rows computed by the code are unchanged; common/feature_columns.py translates at the
-- database boundary (writes, and every read of feature_store).
--
-- ORDER (expand / backfill / deploy / contract):
--   1. Apply this migration (adds the columns and backfills them from the old ones).
--   2. Deploy the API / run ingestion built from this commit: they read and write ONLY the new
--      columns. Old code keeps working until then because the old columns still hold the data.
--      Do not run an ingestion job between steps 1 and 2 with OLD code: it would update only
--      the old columns and the new ones would go stale.
--   3. Apply 0021 (drops the old columns; irreversible).
-- The backfill rewrites every feature_store row once, so the table briefly holds old and new
-- copies (about +60 MB until autovacuum reuses the space): apply it after 0016 / 0017 free
-- room. Each statement below is a single statement (one per semicolon).

alter table feature_store
    add column if not exists grocery_count_1600ft smallint,
    add column if not exists gym_count_1600ft smallint,
    add column if not exists cafe_count_1600ft smallint,
    add column if not exists gas_station_count_1600ft smallint,
    add column if not exists convenience_store_count_1600ft smallint,
    add column if not exists restaurant_count_1600ft smallint,
    add column if not exists bar_count_1600ft smallint,
    add column if not exists transit_stop_count_half_mi smallint,
    add column if not exists running_trail_count_half_mi smallint,
    add column if not exists strava_segment_count_half_mi smallint,
    add column if not exists school_count_1mi smallint,
    add column if not exists emergency_facility_count_1mi smallint,
    add column if not exists school_avg_rating_1mi real,
    add column if not exists grocery_nearest_ft real,
    add column if not exists gym_nearest_ft real,
    add column if not exists cafe_nearest_ft real,
    add column if not exists gas_station_nearest_ft real,
    add column if not exists convenience_store_nearest_ft real,
    add column if not exists transit_nearest_ft real,
    add column if not exists school_nearest_ft real,
    add column if not exists running_trail_nearest_ft real,
    add column if not exists restaurant_nearest_ft real,
    add column if not exists bar_nearest_ft real,
    add column if not exists whole_foods_nearest_ft real,
    add column if not exists starbucks_nearest_ft real,
    add column if not exists target_nearest_ft real,
    add column if not exists emergency_facility_nearest_ft real;

update feature_store set
    grocery_count_1600ft = grocery_count_500m::smallint,
    gym_count_1600ft = gym_count_500m::smallint,
    cafe_count_1600ft = cafe_count_500m::smallint,
    gas_station_count_1600ft = gas_station_count_500m::smallint,
    convenience_store_count_1600ft = convenience_store_count_500m::smallint,
    restaurant_count_1600ft = restaurant_count_500m::smallint,
    bar_count_1600ft = bar_count_500m::smallint,
    transit_stop_count_half_mi = transit_stop_count_800m::smallint,
    running_trail_count_half_mi = running_trail_count_800m::smallint,
    strava_segment_count_half_mi = strava_segment_count_800m::smallint,
    school_count_1mi = school_count_1600m::smallint,
    emergency_facility_count_1mi = emergency_facility_count_1600m::smallint,
    school_avg_rating_1mi = school_avg_rating_1600m::real,
    grocery_nearest_ft = round((grocery_nearest_m * 3.280839895)::numeric, 1)::real,
    gym_nearest_ft = round((gym_nearest_m * 3.280839895)::numeric, 1)::real,
    cafe_nearest_ft = round((cafe_nearest_m * 3.280839895)::numeric, 1)::real,
    gas_station_nearest_ft = round((gas_station_nearest_m * 3.280839895)::numeric, 1)::real,
    convenience_store_nearest_ft = round((convenience_store_nearest_m * 3.280839895)::numeric, 1)::real,
    transit_nearest_ft = round((transit_nearest_m * 3.280839895)::numeric, 1)::real,
    school_nearest_ft = round((school_nearest_m * 3.280839895)::numeric, 1)::real,
    running_trail_nearest_ft = round((running_trail_nearest_m * 3.280839895)::numeric, 1)::real,
    restaurant_nearest_ft = round((restaurant_nearest_m * 3.280839895)::numeric, 1)::real,
    bar_nearest_ft = round((bar_nearest_m * 3.280839895)::numeric, 1)::real,
    whole_foods_nearest_ft = round((whole_foods_nearest_m * 3.280839895)::numeric, 1)::real,
    starbucks_nearest_ft = round((starbucks_nearest_m * 3.280839895)::numeric, 1)::real,
    target_nearest_ft = round((target_nearest_m * 3.280839895)::numeric, 1)::real,
    emergency_facility_nearest_ft = round((emergency_facility_nearest_m * 3.280839895)::numeric, 1)::real;
