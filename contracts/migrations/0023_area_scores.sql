-- BenriSpace migration 0023: per-area scores for density weights versions (v2.2-density).
-- NOT yet applied. Additive, idempotent. Mirrored into contracts/schema.sql.
--
--   area_scores   one row per (road-bounded area, weights_version): the 13 factor scores,
--                 the school proximity part and the composite. Written by
--                 `python -m scoring.area_run --write`, which scores each area once from
--                 routed travel times and place densities and also writes the same scores to
--                 `scores` for every grid cell inside the area (map, score file and
--                 /v1/score agree). GET /v1/area serves this row for a density version
--                 instead of scoring sample points on demand. About 36k rows, ~2 MB.
-- Each statement below is a single statement (one per semicolon).

create table if not exists area_scores (
    area_id                  integer     not null,
    weights_version          text        not null,
    grocery_score            smallint,
    gym_score                smallint,
    cafe_score               smallint,
    restaurant_score         smallint,
    bar_score                smallint,
    shopping_score           smallint,
    gas_convenience_score    smallint,
    transit_score            smallint,
    school_score             smallint,
    school_proximity_score   smallint,
    road_score               smallint,
    emergency_corridor_score smallint,
    airport_score            smallint,
    recreation_score         smallint,
    composite_score          real,
    computed_at              timestamptz not null default now(),
    primary key (area_id, weights_version)
);
