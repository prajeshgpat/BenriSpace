-- BenriSpace migration 0006: area shape columns.
-- Applied to production on 2026-10-03. Apply BEFORE running
-- `python -m ingestion.areas.build --source region --write` (write_areas inserts
-- extent_m and compactness) and before deploying the API that selects extent_m
-- in GET /v1/area. Additive and idempotent. Mirrored into contracts/schema.sql.
--
-- extent_m   longest side of the area's bounding box, in metres (local frame).
--            The API treats an area above 2 miles as not found.
-- compactness  Polsby-Popper 4*pi*area/perimeter^2 (1 = circle, near 0 = thin).
-- Existing rows keep NULL until the areas are rebuilt with the size limits
-- (<= 1.5 sq mi, <= 2 mi across; ingestion/areas/limits.py).

alter table areas
    add column if not exists extent_m double precision,
    add column if not exists compactness double precision;
