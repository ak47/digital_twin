# Implementation Plan: Conversation Persistence & Owner Responses

**Branch**: `001-conversation-persistence-admin` | **Date**: 2026-06-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-conversation-persistence-admin/spec.md`

## Summary

Add **Cloud SQL PostgreSQL** for per-message conversation history, a **Google OAuth + email-allowlist admin** surface (API in this repo; UI in `ak47.github.io`), **owner replies** visible to visitors via polling, **escalation email alerts**, and **owner-editable additional instructions** injected last into the Gemini system prompt. Keep Vertex Gemini + optional RAG; extend—not replace—the existing `GET/POST /api/chat` SSE flow.

Phased delivery: **P1** persistence + admin inbox/reply + Google auth → **P2** escalation email + polling contract + instructions → **P3** archive/export (deferred).

## Technical Context

**Language/Version**: Python ≥3.13 (`uv`, hatchling)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, psycopg[binary], google-auth/oauthlib (OAuth), itsdangerous (session cookie), existing google-genai / Vertex stack

**Storage**: Cloud SQL PostgreSQL (`conversations`, `messages`, `owner_settings`); GCS unchanged for RAG corpus; legacy GCS session bucket optional during transition

**Testing**: pytest + httpx (`uv run pytest -q tests`); new unit tests for store, auth, admin routes

**Target Platform**: Cloud Run (`linux/amd64`), Terraform-managed GCP

**Project Type**: Single API service (`src/digital_twin/`) + external static frontend

**Performance Goals**: Inbox list < 500ms p95 at portfolio traffic; poll endpoint lightweight (indexed `conversation_id, id`)

**Constraints**: CORS credentialed admin from GitHub Pages; structured JSON logs on all new failure paths; constitution amendment for DB

**Scale/Scope**: Single owner, low concurrent visitors, max 3 Cloud Run replicas

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| I. Terraform-First | Cloud SQL, connector, secrets, env in `terraform/` | ✅ Planned (`terraform/cloud_sql.tf`) |
| II. Structured Observability | Named events: `conversation_persist_failed`, `admin_auth_denied`, `escalation_email_failed`, etc. | ✅ In contracts/design |
| III. CI-Validated Changes | pytest for new modules | ✅ Required in implement |
| IV. RAG Content Separation | Additional instructions in DB, not image bake-in | ✅ Compliant |
| V. Simplicity | Thin store module, no extra microservices | ✅ See Complexity Tracking |

**Phase 0 pass**: ✅ [research.md](./research.md) resolves all technical choices.

**Phase 1 re-check**: ✅ [data-model.md](./data-model.md) + [contracts/openapi.yaml](./contracts/openapi.yaml) satisfy gates; frontend remains out of repo per constitution.

## Project Structure

### Documentation (this feature)

```text
specs/001-conversation-persistence-admin/
├── plan.md              # This file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1 validation guide
├── contracts/
│   └── openapi.yaml     # Phase 1 API contract
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/digital_twin/
├── main.py                 # Wire public + admin routers; CORS credentials
├── conversation_store.py   # NEW — SQLAlchemy CRUD, inbox, poll
├── admin_auth.py           # NEW — Google OAuth, allowlist, cookie session
├── admin_routes.py         # NEW — inbox, reply, instructions
├── escalation_email.py     # NEW — Gmail send + debounce
├── llm.py                  # Three-role transcript; additional instructions tail
├── settings.py             # DATABASE_URL, OAuth, allowlist, escalation env
└── session_store.py        # Legacy GCS path when DATABASE_URL unset

scripts/sql/
└── 001_conversations.sql   # Schema bootstrap

terraform/
├── cloud_sql.tf            # NEW — instance, DB, user, secrets
└── cloud_run.tf            # DATABASE_URL, OAuth env, Cloud SQL connection

tests/
├── test_conversation_store.py
├── test_admin_auth.py
└── test_admin_routes.py
```

**Structure Decision**: Extend existing single-package layout (Constitution V). No new services.

**Frontend** (sibling repo): `ak47.github.io/no_ego` — see `docs/digital-twin-001-frontend-requirements.md`.

## Implementation Phases

### Phase P1 — Core loop (MVP)

| Area | Work |
|------|------|
| Infra | `terraform/cloud_sql.tf`; Secret Manager; Cloud Run Cloud SQL connector; env vars |
| Schema | `scripts/sql/001_conversations.sql` |
| Store | `conversation_store.py` — insert/list/open/poll |
| Chat | POST `/api/chat` persists visitor+twin; GET history from DB |
| Public | `GET /api/conversations/{id}?after=` |
| Admin auth | Google OAuth + `ADMIN_ALLOWED_EMAILS` + signed cookie |
| Admin API | inbox, thread, owner message POST, resolve |
| LLM | Labeled transcript with owner role authoritative |
| CORS | `allow_credentials=True` |
| Tests | store + auth + admin integration with test DB |

### Phase P2 — Alerts, poll UX, instructions

| Area | Work |
|------|------|
| Escalation | `notify_owner` tool or equivalent; `needs_attention`; `escalation_email.py` |
| Debounce | `last_escalation_email_at` on conversation |
| Instructions | `owner_settings` GET/PUT admin; load in `llm.py` last in system block |
| Rate limit | DB-backed per-conversation window |
| Frontend | Ship ak47.github.io admin + polling (coordinated) |

### Phase P3 — Archive & export (deferred)

| Area | Work |
|------|------|
| Schema | `archive_messages` |
| API | export JSONL, archive/restore/bulk 72h |
| Frontend | Archive tab |

## Environment variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection (Cloud SQL on Run) |
| `ADMIN_ALLOWED_EMAILS` | Comma-separated allowlist |
| `ADMIN_SESSION_SECRET` | Cookie signing (Secret Manager) |
| `ADMIN_SESSION_MAX_AGE_SECONDS` | Default `7200` (2 hours, FR-005c) |
| `GOOGLE_OAUTH_CLIENT_ID` | OAuth |
| `GOOGLE_OAUTH_CLIENT_SECRET` | OAuth (Secret Manager) |
| `ADMIN_OAUTH_REDIRECT_URI` | Callback URL |
| `ESCALATION_EMAIL_TO` | Defaults to `RESUME_BOT_DIGEST_EMAIL_TO` |
| `ESCALATION_EMAIL_DEBOUNCE_MINUTES` | Default 60 |

Existing: `CORS_ALLOWED_ORIGINS`, Gmail digest vars, Gemini/RAG vars.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Constitution: alternate DB (Cloud SQL) | Per-message history, inbox, settings row, multi-replica debounce | GCS JSON blobs cannot support inbox queries or `after=` polling efficiently |
| CORS `allow_credentials` | Admin session cookie from GitHub Pages origin | Token-in-header only avoids cookie but worsens XSS risk for long-lived tokens in localStorage |
| Google OAuth vs IAP | Spec requires Google account + allowlist; local dev parity | IAP not available on localhost |
| Optional `notify_owner` tool | Reliable FR-010 escalation detection | Parsing free-text twin replies is brittle |

**Follow-up**: Constitution v1.1.0 (2026-06-09) permits Cloud SQL for conversation data — amendment complete.

## Artifact Index

| Artifact | Path |
|----------|------|
| Research | [research.md](./research.md) |
| Data model | [data-model.md](./data-model.md) |
| API contract | [contracts/openapi.yaml](./contracts/openapi.yaml) |
| Validation guide | [quickstart.md](./quickstart.md) |
| Frontend coordination | `../ak47.github.io/docs/digital-twin-001-frontend-requirements.md` |

**Next command**: `/speckit-tasks` to generate `tasks.md`.
