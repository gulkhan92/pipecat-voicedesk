-- Phase 1: knowledge base schema for the voice agent's retrieval layer.
-- Mirrors the text chatbot's support_kb table so both channels retrieve
-- from the same grounded content.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS support_kb (
    id SERIAL PRIMARY KEY,
    intent TEXT NOT NULL,
    instruction TEXT NOT NULL,
    response TEXT NOT NULL,
    embedding vector(384),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS support_kb_intent_idx ON support_kb (intent);

-- HNSW index over the embedding column for fast approximate nearest-neighbor
-- lookups. Built after data load in generate_embeddings.py once rows exist,
-- but declared here so the schema is self-describing; CONCURRENTLY is not
-- used because this runs once at container init against an empty table.
CREATE INDEX IF NOT EXISTS support_kb_embedding_hnsw_idx
    ON support_kb
    USING hnsw (embedding vector_cosine_ops);
