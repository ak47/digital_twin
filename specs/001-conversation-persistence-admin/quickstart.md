# Quickstart: Validate 001 Conversation Persistence & Owner Responses

**Prerequisites**: `uv sync --extra dev`, PostgreSQL (local Docker or Cloud SQL proxy), env vars from [plan.md](./plan.md#environment-variables).

**Contracts**: [contracts/openapi.yaml](./contracts/openapi.yaml)  
**Data model**: [data-model.md](./data-model.md)  
**Frontend**: `ak47.github.io/docs/digital-twin-001-frontend-requirements.md`

## 1. Local API with database

```bash
cd /Users/andy/werk/my_gits/projects/digital_twin
export DATABASE_URL="postgresql+psycopg://digital_twin:dev@localhost:5432/digital_twin"
export ADMIN_ALLOWED_EMAILS="you@example.com"
export ADMIN_SESSION_SECRET="dev-secret-min-32-chars-long!!!!"
export GOOGLE_OAUTH_CLIENT_ID="..."
export GOOGLE_OAUTH_CLIENT_SECRET="..."
export CORS_ALLOWED_ORIGINS="http://localhost:8000"
# Optional Gmail for escalation tests:
export GMAIL_DELEGATED_USER="..."
export ESCALATION_EMAIL_TO="you@example.com"

uv run python -m digital_twin.main   # or uvicorn per README
```

Apply schema (Alembic): `uv run alembic upgrade head` with `DATABASE_URL` set.

## 2. P1 — Visitor persistence

```bash
# New conversation + message
curl -sS -D - -X POST http://localhost:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Hello"}' | head

# Note X-Session-Id header; reload history
SID="<uuid-from-header>"
curl -sS http://localhost:8080/api/chat -H "X-Session-Id: $SID" | jq .
```

**Expected**: `messages` array with visitor + twin rows; same content after repeat GET.

## 3. P1 — Admin inbox (after Google login in browser)

1. Open admin UI (local Gatsby or curl OAuth flow).
2. `GET /admin/conversations` with session cookie → lists thread from step 2.
3. `GET /admin/conversations/$SID` → full transcript; unread cleared.

```bash
curl -sS http://localhost:8080/admin/conversations \
  -b "dt_admin=<cookie>" | jq .
```

## 4. P1 — Owner reply

```bash
curl -sS -X POST "http://localhost:8080/admin/conversations/$SID/messages" \
  -H 'Content-Type: application/json' \
  -b "dt_admin=<cookie>" \
  -d '{"content":"Thanks — I will follow up by email."}' | jq .
```

**Expected**: `role: owner` message returned.

Visitor poll:

```bash
curl -sS "http://localhost:8080/api/conversations/$SID?after=0" | jq .
```

**Expected**: owner message visible without new POST /api/chat.

## 5. P2 — Escalation email

Ask twin an unanswerable question via POST `/api/chat`. Check:

- `conversations.needs_attention = true` in DB
- Email received at `ESCALATION_EMAIL_TO` within 60s (or log event `escalation_email_sent`)
- Second escalation within 1h does not duplicate email (debounce)

## 6. P2 — Additional instructions

```bash
curl -sS -X PUT http://localhost:8080/admin/instructions \
  -H 'Content-Type: application/json' \
  -b "dt_admin=<cookie>" \
  -d '{"content":"## Focus\nEmphasize platform engineering experience."}'
```

Send new visitor message; twin reply should reflect instruction (manual review).

## 7. P2 — Polling (frontend)

With `no_ego` chat open, owner posts reply; within 15s visitor UI shows owner bubble without reload. Verify backoff in browser network tab (10s → 30s after 2min idle).

## 8. Automated tests

```bash
uv run pytest -q tests/test_conversation_store.py tests/test_admin_auth.py tests/test_chat_post.py
```

(Tests added during `/speckit-implement`.)

## 9. Production smoke (post-deploy)

1. Chat on <https://no-ego.net> About page → message persists on reload.
2. Google sign-in on admin route with allowlisted account → inbox shows thread.
3. Owner reply → visitor sees within poll interval.

## 10. P3 (deferred)

- Export: `GET /admin/conversations/export` → JSONL file
- Archive thread → absent from active inbox, present under Archive tab
