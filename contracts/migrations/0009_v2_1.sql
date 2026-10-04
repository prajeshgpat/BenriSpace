-- BenriSpace v2.1 migration (weights_version 'v2.1-handtuned'). Applied to production on 2026-10-04.
-- Additive only (nullable columns), idempotent. Run by hand after review, BEFORE deploying
-- the API that reads these columns. v2 rows keep working with the new columns null.
-- Mirrored into contracts/schema.sql so a fresh database already has them.
--
-- v2.1 makes every scoring factor a user-facing pill (docs/SCORING.md v1.4).
-- New feature_store columns are named in imperial units (owner rule).
-- Each statement below is a single statement (one per semicolon).

-- Shopping: general retail destinations from OpenStreetMap shop tags (ingestion/osm_retail_parks.py).
-- shopping_raw is the 0-1 proximity + variety signal the scoring engine normalizes.
alter table feature_store
    add column if not exists shopping_count_1mi int,
    add column if not exists shopping_nearest_ft double precision,
    add column if not exists shopping_variety_count_1mi int,
    add column if not exists shopping_raw double precision;

-- Recreation: parks, playgrounds, nature reserves, gardens, recreation grounds.
-- recreation_raw is the 0-1 PARK half of the Recreation factor (proximity + size of the
-- largest park within half a mile). Trail access still comes from running_trail_* columns.
alter table feature_store
    add column if not exists park_count_1mi int,
    add column if not exists park_nearest_ft double precision,
    add column if not exists park_largest_sq_ft_half_mi double precision,
    add column if not exists recreation_raw double precision;

-- New score columns. Traffic keeps using road_score (same meaning, renamed in the UI only).
-- Gas and convenience stores are now ONE positive factor (gas_convenience_score), and also
-- feed the Noise Corridor (emergency_corridor_score) as an adjacency penalty at scoring time.
-- v2 rows hold Shopping in premium_retail_score and Recreation in trail_popularity_score,
-- which the API reads as a fallback.
alter table scores
    add column if not exists shopping_score double precision,
    add column if not exists recreation_score double precision,
    add column if not exists gas_convenience_score double precision;
