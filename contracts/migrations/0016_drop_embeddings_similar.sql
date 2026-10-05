-- BenriSpace migration 0016: drop the similar-areas embedding column, its HNSW index and the
-- (never populated) similar_cells table. NOT yet applied. DESTRUCTIVE, idempotent. Mirrored
-- into contracts/schema.sql.
--
-- /v1/similar now computes the distance in SQL over the stored factor scores (api/similar.py),
-- so the vector(14) column (~7.8 MB for two versions) and the HNSW index (~46 MB) are dead
-- weight, and similar_cells (0011, written only with SIMILAR_CELLS=1) was never filled.
--
-- ORDER: deploy the API that no longer reads `embedding` FIRST. Until then /v1/similar answers
-- 404 on the old code (it treats the missing column as "no similarity data"); everything else
-- keeps working. The `vector` extension is left installed (harmless, no space).
-- The dropped column's space is returned by the table rewrite in 0017.
-- Each statement below is a single statement (one per semicolon).

drop table if exists similar_cells;

drop index if exists scores_embedding_hnsw_idx;

alter table scores drop column if exists embedding;
