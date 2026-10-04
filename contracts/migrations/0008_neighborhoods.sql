-- BenriSpace migration 0008: human neighborhood names.
-- Applied to production on 2026-10-04. Apply BEFORE running
-- `python -m ingestion.neighborhoods` (it updates both columns). The API
-- tolerates the columns being absent (neighborhood is then null), so it can
-- deploy before or after. Additive and idempotent. Mirrored into
-- contracts/schema.sql.
--
-- neighborhood  label such as 'Park Slope, Brooklyn' or 'Montclair, NJ', from
--               OpenStreetMap place nodes (ingestion/neighborhoods.py).

alter table geo_entities add column if not exists neighborhood text;

alter table areas add column if not exists neighborhood text;
