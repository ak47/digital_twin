# Research: 001 Conversation Persistence & Owner Responses

**Date**: 2026-06-09  
**Spec**: [spec.md](./spec.md)

## R1 — Durable message storage on GCP

**Decision**: **Cloud SQL for PostgreSQL** (single small instance, private IP + Cloud SQL Auth Proxy connector on Cloud Run).

**Rationale**:
- Spec requires per-message rows, inbox aggregates, monotonic ids for `after=` polling, and a settings row—relational fits naturally.
- Matches the ed-donner/avatar `messages` table model without introducing Supabase (outside GCP Terraform workflow).
- Terraform resources (`google_sql_database_instance`, `google_sql_database`, IAM, Secret Manager for password) align with Constitution I.
- Portfolio traffic is low; `db-f1-micro` or `db-g1-small` is sufficient.

**Alternatives considered**:
| Option | Rejected because |
|--------|------------------|
| GCS JSON per session (status quo) | No efficient inbox query, no per-message id polling, poor admin list UX |
| Firestore | Document model awkward for ordered message threads + SQL-style inbox; new client patterns |
| Spanner | Operational/cost overhead for single-owner chat volume |
| Supabase | External SaaS; conflicts with Terraform-first GCP stack |

## R2 — Application data access

**Decision**: **SQLAlchemy 2.x** + **psycopg[binary]** with a thin `conversation_store.py` module (no heavy repository framework). Sync DB calls from FastAPI via existing `asyncio.to_thread` pattern.

**Rationale**: Keeps dependencies minimal (Constitution V); team already uses straightforward modules (`session_store.py`, `llm.py`). Migrations via SQL files in `terraform/sql/` or `scripts/sql/` applied once at deploy/startup.

**Alternatives considered**: Raw psycopg only (more boilerplate); async SQLAlchemy (unnecessary given current threading model).

## R3 — Admin authentication

**Decision**: **Google OAuth 2.0 authorization code flow** (backend-initiated redirect + callback). Verified `email` checked against **`ADMIN_ALLOWED_EMAILS`** env (comma-separated, lowercase-normalized). Session: **httpOnly signed cookie** (`itsdangerous.URLSafeTimedSerializer`, 7-day max age).

**Rationale**: Spec requires Google + hardcoded allowlist. OAuth code flow keeps client secret on server; works with admin UI on GitHub Pages origin via CORS `allow_credentials=True`.

**Alternatives considered**:
| Option | Rejected because |
|--------|------------------|
| Password + cookie (avatar reference) | Explicitly replaced in spec |
| Firebase Auth / Identity Platform | Extra product surface for single allowlist |
| Google IAP only | Harder to test locally; couples admin to GCP console |

**Implementation notes**:
- Terraform/Secret Manager: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `ADMIN_SESSION_SECRET`
- OAuth redirect URIs: production API `/admin/auth/google/callback` + localhost for dev
- Fail closed: allowlist miss → 403 + structured log `admin_auth_allowlist_denied`

## R4 — CORS and credentials

**Decision**: Enable **`allow_credentials=True`** on CORSMiddleware when admin routes ship; keep explicit `cors_allowed_origins` from Terraform (GitHub Pages + local Gatsby).

**Rationale**: Admin session cookies require credentialed cross-origin requests from `ak47.github.io` to Cloud Run API.

## R5 — Public chat API evolution

**Decision**: Add **`GET /api/conversations/{conversation_id}`** with optional `?after=` for polling. Keep **`GET/POST /api/chat`** during transition: both read/write through DB when `DATABASE_URL` set; fall back to GCS/memory only when unset (local tests).

**Rationale**: Minimizes frontend breakage (`X-Session-Id` unchanged); incremental poll maps to avatar reference.

**Message roles in API**: `visitor`, `twin`, `owner` (map legacy `user`/`assistant` in GET `/api/chat` for one release if needed).

## R6 — Twin transcript and escalation

**Decision**: Extend `llm.stream_reply` input to three-role labeled transcript. Add **prompt-level escalation rules** in `system.md` (or `rules` section): when unknown or contact capture, twin must signal escalation (structured marker or tool). On escalation: set `needs_attention` on conversation rows + send email.

**Rationale**: Avatar uses `push_tool`; we use email per spec. Tool-calling adds complexity; a post-generation hook that scans for escalation intent OR a lightweight `escalate` function tool are both viable—**prefer explicit tool** `notify_owner` for testability (mirrors push_tool semantics without Pushover).

**Alternatives considered**: Regex on twin text (fragile); manual-only flag (misses spec FR-010 automation).

## R7 — Escalation email

**Decision**: Reuse **`session_digest.py` Gmail send path** (`_gmail_service_account_json`, domain-wide delegation). New function `send_escalation_email(conversation_id, preview, visitor_message)`. Recipients: `ESCALATION_EMAIL_TO` defaulting to `RESUME_BOT_DIGEST_EMAIL_TO`. Debounce: store `last_escalation_email_at` on conversation; skip if unresolved and sent within 1 hour.

**Rationale**: Spec FR-011; infrastructure already provisioned for digest job. Distinct subject/body from idle digest.

## R8 — Additional instructions

**Decision**: Table `owner_settings` single row (`id=1`, `additional_instructions TEXT`, `updated_at`). Loaded on every `stream_reply` call; appended **last** in system instruction block (after static `system.md` + RAG).

**Rationale**: docs/MORE.md post-build refinement; FR-021/FR-022. Not cached in process memory across requests (read per turn).

## R9 — Rate limiting and multi-instance behavior

**Decision**: Conversation-scoped rate limit: **DB-backed sliding window** (table `rate_limit_events` or count messages in last minute per `conversation_id`) when DB enabled; fallback in-memory for no-DB dev.

**Rationale**: Spec edge case—must not rely solely on instance memory for abuse controls at scale (max 3 Cloud Run replicas).

## R10 — Idle session digest coexistence

**Decision**: Keep GCS session digest job **optional/legacy**. After DB cutover, digest job can scan DB for idle conversations (future) or remain disabled if escalation + inbox replace need. Phase 1: **do not remove** digest Terraform; mark conversations in DB as source of truth for new threads.

**Rationale**: Avoid breaking existing ops; spec treats escalation email as separate from digest.

## R11 — Constitution amendment (storage)

**Decision**: Amend Technology & Platform Constraints to: **Cloud SQL PostgreSQL for conversation/admin data**; GCS remains for RAG corpus and optional legacy session blobs.

**Rationale**: Required by spec; documented in plan Complexity Tracking until `/speckit-constitution` lands.

## R12 — Frontend coordination

**Decision**: Admin UI in **`ak47.github.io/no_ego`** per [digital-twin-001-frontend-requirements.md](https://github.com/andyak47/ak47.github.io/blob/main/docs/digital-twin-001-frontend-requirements.md) (sibling doc). Phased: P1 backend + admin API first, then frontend admin pages.

**Rationale**: Constitution: frontend out of repo; coordinated contract in `contracts/openapi.yaml`.

## R13 — P3 archive (deferred design sketch)

**Decision**: Table `archive_messages` identical schema to `messages`; archive = copy rows + delete from `messages` in transaction; restore = reverse. Bulk archive: `last_activity_at < now() - 72h`.

**Rationale**: Matches docs/MORE.md; implemented in Phase 3 tasks only.
