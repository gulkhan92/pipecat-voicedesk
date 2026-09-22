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

-- Phase 4: per-turn log of the LLM provider layer, for the analytics
-- dashboard. One row per completed conversational turn.
CREATE TABLE IF NOT EXISTS call_turns (
    id SERIAL PRIMARY KEY,
    transcript TEXT NOT NULL,
    response_text TEXT,
    llm_provider TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    retrieval_hit_count INTEGER NOT NULL DEFAULT 0,
    retrieval_top_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS call_turns_created_at_idx ON call_turns (created_at);
CREATE INDEX IF NOT EXISTS call_turns_llm_provider_idx ON call_turns (llm_provider);

-- Phase 5: one row per escalated call, written by the escalation flow node.
-- A structured summary a human agent can act on, not a raw transcript dump.
CREATE TABLE IF NOT EXISTS escalations (
    id SERIAL PRIMARY KEY,
    caller_name TEXT,
    intent TEXT,
    reason TEXT NOT NULL,
    clarification_attempts INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS escalations_created_at_idx ON escalations (created_at);

-- Phase 7: one row per call session, for reporting voice agent performance
-- alongside the chat product's in the same analytics dashboard. Turn-level
-- detail (provider, tokens, retrieval hits) stays in call_turns; this table
-- is the coarser session summary: start/end time, turn count, providers
-- used, and how the call ended.
CREATE TABLE IF NOT EXISTS call_sessions (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    turn_count INTEGER NOT NULL DEFAULT 0,
    providers_used TEXT[] NOT NULL DEFAULT '{}',
    escalated BOOLEAN NOT NULL DEFAULT false,
    escalation_reason TEXT
);

CREATE INDEX IF NOT EXISTS call_sessions_started_at_idx ON call_sessions (started_at);

-- Link turns and escalations back to their session.
ALTER TABLE call_turns ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES call_sessions(id);
ALTER TABLE escalations ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES call_sessions(id);

CREATE INDEX IF NOT EXISTS call_turns_session_id_idx ON call_turns (session_id);
