-- BenriSpace migration 0017: compact `scores`. NOT yet applied. DESTRUCTIVE (rounds stored
-- sub-scores, drops scores.id), idempotent where possible. Mirrored into contracts/schema.sql.
--
--   sub-scores   numeric / double precision -> smallint (whole points, 0-100). Every reader
--                already rounds to whole points, and the compact score file quantizes to
--                bytes. numeric cost ~11 B and double 8 B per value, smallint 2 B.
--   composite    numeric -> real (4 B; one decimal is kept by scoring/run.py).
--   scores.id    dropped (a uuid nobody reads, 16 B per row and a 9.4 MB index); the unique
--                (geo_entity_id, weights_version) becomes the primary key, and writers' ON
--                CONFLICT (geo_entity_id, weights_version) keeps working unchanged.
--   indexes      scores_geo_entity_idx (a prefix of the primary key) and
--                scores_weights_version_idx (a prefix of the covering index
--                scores_version_entity_cover_idx) are dropped.
--
-- Measured on a 128,640-row local copy of production's shape: 181 MB -> about 20 MB.
-- ALTER ... TYPE rewrites the table, so it needs free space for the new copy (about 25 MB
-- here) while the old one still exists; do it AFTER dropping v2-handtuned
-- (scripts/delete_scores.py) and 0016. A rewrite also returns the space of earlier dropped
-- columns and dead rows; no `vacuum full` is needed afterwards.
-- Code compatibility: old and new code read smallint the same (ints instead of Decimals).
-- Each statement below is a single statement (one per semicolon).

alter table scores
    drop constraint if exists scores_pkey,
    drop column if exists id,
    drop constraint if exists scores_geo_entity_id_weights_version_key,
    alter column grocery_score type smallint using round(grocery_score)::smallint,
    alter column gym_score type smallint using round(gym_score)::smallint,
    alter column cafe_score type smallint using round(cafe_score)::smallint,
    alter column gas_station_score type smallint using round(gas_station_score)::smallint,
    alter column convenience_store_score type smallint using round(convenience_store_score)::smallint,
    alter column transit_score type smallint using round(transit_score)::smallint,
    alter column school_score type smallint using round(school_score)::smallint,
    alter column road_score type smallint using round(road_score)::smallint,
    alter column emergency_corridor_score type smallint using round(emergency_corridor_score)::smallint,
    alter column airport_score type smallint using round(airport_score)::smallint,
    alter column trail_popularity_score type smallint using round(trail_popularity_score)::smallint,
    alter column restaurant_score type smallint using round(restaurant_score)::smallint,
    alter column bar_score type smallint using round(bar_score)::smallint,
    alter column premium_retail_score type smallint using round(premium_retail_score)::smallint,
    alter column school_proximity_score type smallint using round(school_proximity_score)::smallint,
    alter column shopping_score type smallint using round(shopping_score)::smallint,
    alter column recreation_score type smallint using round(recreation_score)::smallint,
    alter column gas_convenience_score type smallint using round(gas_convenience_score)::smallint,
    alter column composite_score type real using composite_score::real,
    add primary key (geo_entity_id, weights_version);

drop index if exists scores_geo_entity_idx;

drop index if exists scores_weights_version_idx;
