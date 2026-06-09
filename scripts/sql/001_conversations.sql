-- Conversation persistence schema (feature 001) — REFERENCE ONLY
-- Use Alembic instead: uv run alembic upgrade head

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    visitor_name TEXT NOT NULL DEFAULT 'Rando',
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    needs_attention BOOLEAN NOT NULL DEFAULT false,
    last_escalation_email_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_last_activity
    ON conversations (last_activity_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversations_needs_attention
    ON conversations (needs_attention)
    WHERE needs_attention = true;

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('visitor', 'twin', 'owner')),
    content TEXT NOT NULL,
    tool_calls JSONB,
    needs_attention_row BOOLEAN NOT NULL DEFAULT false,
    read_by_owner BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages (conversation_id, id);

CREATE TABLE IF NOT EXISTS owner_settings (
    id INT PRIMARY KEY CHECK (id = 1),
    additional_instructions TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO owner_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
