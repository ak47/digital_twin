-- Archive table (feature 001 P3) — REFERENCE ONLY
-- Included in Alembic revision 001_initial

CREATE TABLE IF NOT EXISTS archive_messages (
    id BIGINT NOT NULL,
    conversation_id UUID NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls JSONB,
    needs_attention_row BOOLEAN NOT NULL DEFAULT false,
    read_by_owner BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, id)
);

CREATE INDEX IF NOT EXISTS idx_archive_messages_archived_at
    ON archive_messages (archived_at DESC);
