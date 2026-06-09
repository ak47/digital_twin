# Data Model: 001 Conversation Persistence & Owner Responses

**Date**: 2026-06-09  
**Database**: Cloud SQL PostgreSQL

## Entity relationship (logical)

```mermaid
erDiagram
    conversations ||--o{ messages : contains
    owner_settings ||--|| singleton : one_row

    conversations {
        uuid id PK
        text visitor_name nullable
        timestamptz last_activity_at
        boolean needs_attention
        timestamptz last_escalation_email_at nullable
        timestamptz created_at
    }

    messages {
        bigserial id PK
        uuid conversation_id FK
        text role "visitor|twin|owner"
        text content
        jsonb tool_calls nullable
        boolean needs_attention_row
        boolean read_by_owner
        timestamptz created_at
    }

    owner_settings {
        int id PK "always 1"
        text additional_instructions
        timestamptz updated_at
    }
```

P3 adds `archive_messages` (same columns as `messages`).

## Tables

### `conversations`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` PK | Client `X-Session-Id` / `conversation_id` |
| `visitor_name` | `TEXT` NOT NULL DEFAULT `'Rando'` | Display name; default **Rando** until visitor provides `visitor_name` on chat POST |
| `last_activity_at` | `TIMESTAMPTZ` NOT NULL | Updated on every message |
| `needs_attention` | `BOOLEAN` NOT NULL DEFAULT false | Conversation-level escalation flag |
| `last_escalation_email_at` | `TIMESTAMPTZ` NULL | Debounce escalation emails |
| `created_at` | `TIMESTAMPTZ` NOT NULL DEFAULT now() | |

**Indexes**: `idx_conversations_last_activity` on `(last_activity_at DESC)`; partial index on `needs_attention` where true.

### `messages`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | Monotonic; used for `?after=` polling |
| `conversation_id` | `UUID` FK → `conversations(id)` ON DELETE CASCADE | |
| `role` | `TEXT` NOT NULL CHECK (role IN ('visitor','twin','owner')) | |
| `content` | `TEXT` NOT NULL | Max 20_000 chars enforced in API |
| `tool_calls` | `JSONB` NULL | e.g. `[{"tool":"notify_owner"}]` |
| `needs_attention_row` | `BOOLEAN` NOT NULL DEFAULT false | Legacy per-row flag; inbox uses conversation-level |
| `read_by_owner` | `BOOLEAN` NOT NULL DEFAULT false | Cleared on admin open |
| `created_at` | `TIMESTAMPTZ` NOT NULL DEFAULT now() | |

**Indexes**: `(conversation_id, id)` for thread fetch and poll.

### `owner_settings`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `INT` PK CHECK (id = 1) | Singleton |
| `additional_instructions` | `TEXT` NOT NULL DEFAULT '' | Markdown |
| `updated_at` | `TIMESTAMPTZ` NOT NULL DEFAULT now() | |

Seed: `INSERT INTO owner_settings (id) VALUES (1) ON CONFLICT DO NOTHING`.

### `archive_messages` (P3)

Same columns as `messages` plus optional `archived_at TIMESTAMPTZ`. Populated by move from `messages` on archive.

## Derived views (application layer, not DB views)

### Conversation summary (inbox row)

Computed in query (avatar `list_conversations` pattern):

- `conversation_id`, `visitor_name`
- `preview`: last message `content` truncated 120 chars
- `last_created_at`: max `messages.created_at`
- `last_id`: max `messages.id`
- `message_count`: count
- `unread`: any message with `read_by_owner = false` and `role IN ('visitor','twin')`
- `needs_attention`: `conversations.needs_attention`

## State transitions

### `needs_attention`

```text
false → true   twin escalates (tool or rules) OR owner marks manually (future)
true → false  owner POST /resolve OR owner opens thread (optional auto-clear on open per spec)
```

### `read_by_owner`

On admin `GET /admin/conversations/{id}`: set all rows in conversation `read_by_owner = true` and `conversations.needs_attention = false` (matches avatar `open_conversation`).

### Escalation email debounce

Send email when `needs_attention` becomes true AND (`last_escalation_email_at` IS NULL OR older than debounce window). Update `last_escalation_email_at` on successful send.

## Validation rules

| Rule | Enforcement |
|------|-------------|
| Message content ≤ 20_000 chars | API `clamp_message` |
| Role enum | DB CHECK + Pydantic |
| Allowlist emails | Auth layer only |
| Additional instructions ≤ 32_000 chars | API before save |
| Conversation id format | UUID v4 regex (existing `session_store.validate_session_id`) |

## Migration from GCS sessions

- New chats always create `conversations` row on first message.
- Legacy: if `DATABASE_URL` set and UUID not in DB, optional one-time import from GCS blob not in P1 scope (YAGNI); visitors with old ids start fresh unless blob migration script added later.

## Retention

- No auto-delete in P1/P2.
- P3 bulk archive moves threads idle > 72h to `archive_messages`.
