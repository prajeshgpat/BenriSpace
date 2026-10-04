-- BenriSpace similar-areas embeddings (pgvector). Applied to production on 2026-10-03.
-- Additive only; idempotent. Mirrored into contracts/schema.sql.
--
-- scores.embedding : 14-dim vector, one dimension per sub-score, z-scored across
--                    the metro (scoring/embeddings.py). Filled by
--                    `python -m scoring.embeddings`, read by GET /v1/similar.

create extension if not exists vector;

alter table scores add column if not exists embedding vector(14);

create index if not exists scores_embedding_hnsw_idx
    on scores using hnsw (embedding vector_l2_ops);
