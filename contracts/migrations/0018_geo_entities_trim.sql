-- BenriSpace migration 0018: trim `geo_entities`. NOT yet applied. DESTRUCTIVE (drops unused
-- columns), idempotent. Mirrored into contracts/schema.sql.
--
--   geom                 the generated Point column from 0012 and its GiST index (about 4.5 MB
--                        at 64k cells, ~70 B per cell): no query reads it. Cells are looked
--                        up by the (latitude, longitude) btree and the geohash. If a spatial
--                        cell query is ever needed, an expression index costs the same as the
--                        index alone: create index on geo_entities using gist
--                        (st_setsrid(st_makepoint(longitude, latitude), 4326)).
--   created_at / updated_at   never read or written after the grid insert (16 B per cell).
--
-- Dropping a column does not shrink the heap by itself; it stops costing space for new rows
-- and the next table rewrite (vacuum full geo_entities, optional) returns the rest.
-- Each statement below is a single statement (one per semicolon).

alter table geo_entities
    drop column if exists geom,
    drop column if exists created_at,
    drop column if exists updated_at;
