# Tasks: Conversation Persistence & Owner Responses

**Input**: Design documents from `specs/001-conversation-persistence-admin/`  
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml, quickstart.md

**Organization**: Tasks grouped by user story (US1–US7). Backend tasks in `digital_twin`; frontend tasks in `ak47.github.io/no_ego` per coordinated adoption doc.

**Tests**: Included where plan.md lists test modules (Constitution III — CI must pass `uv run pytest -q tests`).

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies, SQL layout, and constitution follow-up before application code.

- [x] T001 Add SQLAlchemy, psycopg[binary], itsdangerous, and google-auth-oauthlib to `pyproject.toml` and refresh `uv.lock`
- [x] T002 Create PostgreSQL schema file `scripts/sql/001_conversations.sql` per `data-model.md` (`conversations`, `messages`, `owner_settings`)
- [x] T003 [P] Document Cloud SQL env vars in `.env.example` (DATABASE_URL, OAuth, allowlist, escalation)
- [x] T004 Run `/speckit-constitution` MINOR amendment: add Cloud SQL for conversation data to `.specify/memory/constitution.md` Technology constraints

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Terraform, settings, DB access layer, admin auth skeleton, and CORS credentials — **blocks all user stories**.

**⚠️ CRITICAL**: No user story work until this phase is complete.

- [x] T005 Add `terraform/cloud_sql.tf` (PostgreSQL instance, database, user, Secret Manager password, IAM for Cloud Run)
- [x] T006 Update `terraform/cloud_run.tf` with Cloud SQL connector annotation, `DATABASE_URL`, OAuth secrets, `ADMIN_ALLOWED_EMAILS`, and escalation email env
- [x] T007 [P] Document Cloud SQL operator steps in `terraform/README.md` (apply order, local proxy, secret wiring); note that **`deploy-api.yml` updates image + app env only**—`DATABASE_URL` and OAuth env are **Terraform-managed** (same pattern as `RAG_CORPUS_RESOURCE`), so no deploy-workflow change required unless env vars are later moved to CI
- [x] T008 Extend `src/digital_twin/settings.py` with `database_url`, OAuth, allowlist, session secret, and escalation settings
- [x] T009 Create `src/digital_twin/conversation_store.py` with SQLAlchemy engine/session factory and health check when `DATABASE_URL` set
- [x] T010 Create `src/digital_twin/admin_auth.py` with Google OAuth helpers, allowlist check, and signed `dt_admin` cookie (itsdangerous) with **2-hour** session TTL (FR-005c: `max_age` on cookie + serializer validation)
- [x] T011 Update `src/digital_twin/main.py` to set `allow_credentials=True` on CORSMiddleware and mount placeholder admin router
- [x] T012 [P] Add structured log event names for new failure paths in `src/digital_twin/structured_logging.py` or module docstrings per plan.md

**Checkpoint**: Foundation ready — database connectable locally; admin auth module unit-testable in isolation.

---

## Phase 3: User Story 1 — Durable conversation history (Priority: P1) 🎯 MVP

**Goal**: Visitor messages and twin replies persist as ordered rows; reload restores full thread via `X-Session-Id`.

**Independent Test**: POST chat → GET history returns visitor + twin messages in order after page reload (see `quickstart.md` §2).

### Implementation for User Story 1

- [x] T013 [US1] Implement `insert_message`, `get_messages`, `ensure_conversation` in `src/digital_twin/conversation_store.py`; default `visitor_name` to **"Rando"** on create; update when visitor supplies `visitor_name` on POST `/api/chat`
- [x] T014 [US1] Wire `POST /api/chat` in `src/digital_twin/main.py` to persist visitor message before LLM and twin message after stream completes
- [x] T015 [US1] Wire `GET /api/chat` in `src/digital_twin/main.py` to load history from `conversation_store` when `DATABASE_URL` set (keep GCS fallback when unset)
- [x] T016 [US1] Add `GET /api/conversations/{conversation_id}` with optional `?after=` in `src/digital_twin/main.py` per `contracts/openapi.yaml`
- [x] T017 [US1] Update `src/digital_twin/llm.py` to build labeled transcript from DB roles (`visitor`, `twin`, `owner`) for generation input
- [x] T018 [US1] Add message length clamp (20_000 chars) in `src/digital_twin/main.py` matching spec FR-017
- [x] T019 [P] [US1] Add unit tests for store CRUD and ordering in `tests/test_conversation_store.py`
- [x] T020 [P] [US1] Extend `tests/test_chat_post.py` to assert messages persist when test DB/fixture available

**Checkpoint**: Public chat persists and reloads without admin features.

---

## Phase 4: User Story 2 — Owner inbox and thread review (Priority: P1)

**Goal**: Allowlisted Google sign-in; admin inbox list and thread open with read/attention cleared.

**Independent Test**: Two visitor threads visible in `GET /admin/conversations` after Google login; open thread shows full transcript (see `quickstart.md` §3).

### Implementation for User Story 2

- [x] T021 [US2] Implement `list_conversations` and `open_conversation` (mark read, clear attention) in `src/digital_twin/conversation_store.py`
- [x] T022 [US2] Create `src/digital_twin/admin_routes.py` with `GET /admin/conversations` and `GET /admin/conversations/{id}` per OpenAPI
- [x] T023 [US2] Add OAuth routes `GET /admin/auth/google` and `GET /admin/auth/google/callback` in `src/digital_twin/admin_routes.py`
- [x] T024 [US2] Add `GET /admin/me`, `POST /admin/logout`, and `require_admin` dependency in `src/digital_twin/admin_auth.py`
- [x] T025 [US2] Register admin router and auth dependencies in `src/digital_twin/main.py`
- [x] T026 [P] [US2] Add tests for allowlist pass/fail, 2-hour session expiry, and cookie session in `tests/test_admin_auth.py`
- [x] T027 [P] [US2] Add tests for inbox list and open in `tests/test_admin_routes.py`

**Checkpoint**: Owner can authenticate and browse conversations; no reply compose yet.

---

## Phase 5: User Story 3 — Owner replies in live thread (Priority: P1)

**Goal**: Owner posts `owner` role messages; visitors receive them; twin treats owner text as authoritative.

**Independent Test**: Admin POST reply → poll/GET shows owner message → follow-up visitor chat acknowledges owner (see `quickstart.md` §4).

### Implementation for User Story 3

- [x] T028 [US3] Implement `insert_owner_message` in `src/digital_twin/conversation_store.py`
- [x] T029 [US3] Add `POST /admin/conversations/{id}/messages` and `POST /admin/conversations/{id}/resolve` in `src/digital_twin/admin_routes.py`
- [x] T030 [US3] Update `src/digital_twin/llm.py` system/transcript rules so owner messages are authoritative and never contradicted (FR-014)
- [x] T031 [P] [US3] Add admin reply and resolve tests in `tests/test_admin_routes.py`
- [ ] T032 [P] [US3] Create admin shell in `ak47.github.io/no_ego/src/components/digital-twin-admin-layout.js` with shared nav **Conversations | Instructions | Archive** (FR-022a; see frontend requirements §5.2) plus login gate on `ak47.github.io/no_ego/src/pages/digital-twin-admin.js`
- [ ] T033 [US3] Extend `ak47.github.io/no_ego/src/utils/digitalTwinApi.js` with `adminGoogleSignIn`, `adminMe`, `adminListConversations`, `adminGetConversation` using `credentials: 'include'`
- [ ] T034 [US3] Build thread view + reply composer + resolve action in `ak47.github.io/no_ego/src/components/digital-twin-admin-thread.js`

**Checkpoint**: End-to-end human-in-the-loop reply works (visitor may need manual refresh until US5 polling).

---

## Phase 6: User Story 4 — Escalation email alerts (Priority: P2)

**Goal**: Twin escalations flag `needs_attention` and send debounced email via existing Gmail path.

**Independent Test**: Unanswerable question triggers email within 60s; debounce prevents spam (see `quickstart.md` §5).

### Implementation for User Story 4

- [x] T035 [US4] Create `src/digital_twin/escalation_email.py` reusing Gmail send from `src/digital_twin/session_digest.py`
- [x] T036 [US4] Add `set_needs_attention` and `last_escalation_email_at` update logic in `src/digital_twin/conversation_store.py`
- [x] T037 [US4] Implement escalation trigger on twin turn (notify_owner tool or post-generation hook) in `src/digital_twin/llm.py` and `src/digital_twin/main.py`
- [x] T038 [US4] Call `escalation_email.send` with debounce window from settings after flagging conversation
- [x] T039 [P] [US4] Add tests for debounce and needs_attention flag in `tests/test_escalation_email.py`
- [x] T040 [P] [US4] Add Terraform log-based alert for `escalation_email_failed` in `terraform/alerts.tf` if not covered by existing ERROR policy

**Checkpoint**: Owner receives email on escalation; inbox shows needs-attention badge.

---

## Phase 7: User Story 5 — Visitor polling for owner messages (Priority: P2)

**Goal**: Visitor chat polls `?after=` with tiered backoff; owner replies appear within 15s without reload.

**Independent Test**: Admin reply while chat open → visitor UI updates within active poll tier (see `quickstart.md` §7).

### Implementation for User Story 5

- [x] T041 [US5] Verify `GET /api/conversations/{id}?after=` returns only new rows with stable ordering in `src/digital_twin/conversation_store.py` (fix gaps if any from US1)
- [ ] T042 [US5] Add `pollMessages` to `ak47.github.io/no_ego/src/utils/digitalTwinApi.js` calling `/api/conversations/{id}?after=`
- [ ] T043 [US5] Implement tiered polling ladder (10s / 30s / 2m / 5m) in `ak47.github.io/no_ego/src/components/digital-twin-chat.js`
- [ ] T044 [US5] Render `owner` role with distinct styling in `ak47.github.io/no_ego/src/components/digital-twin-chat.js`
- [ ] T045 [US5] Map API message shape (`visitor`/`twin`/`owner`, `content`) in `digital-twin-chat.js` (backward compat with legacy `user`/`assistant`/`text` if retained)

**Checkpoint**: Owner replies visible on visitor chat without full page reload.

---

## Phase 8: User Story 6 — Owner-editable additional instructions (Priority: P2)

**Goal**: Admin Instructions tab saves Markdown; next twin turn injects content last in system prompt.

**Independent Test**: Save instruction → next visitor message reflects guidance (see `quickstart.md` §6).

### Implementation for User Story 6

- [x] T046 [US6] Implement `get_additional_instructions` and `save_additional_instructions` in `src/digital_twin/conversation_store.py` (`owner_settings` row)
- [x] T047 [US6] Add `GET /admin/instructions` and `PUT /admin/instructions` in `src/digital_twin/admin_routes.py` per OpenAPI
- [x] T048 [US6] Load instructions fresh each turn and append as final system section in `src/digital_twin/llm.py` (FR-022)
- [x] T049 [US6] Enforce max instructions size (32_000 chars) with clear API error in `src/digital_twin/admin_routes.py`
- [x] T050 [P] [US6] Add instructions GET/PUT tests in `tests/test_admin_routes.py`
- [ ] T051 [US6] Add Instructions tab content (Markdown textarea + save) routed through `digital-twin-admin-layout.js` in `ak47.github.io/no_ego/src/pages/digital-twin-admin-instructions.js`
- [ ] T052 [US6] Add `adminGetInstructions` and `adminSaveInstructions` to `ak47.github.io/no_ego/src/utils/digitalTwinApi.js`

**Checkpoint**: Owner can steer twin behavior without redeploy.

---

## Phase 9: User Story 7 — Export and archive (Priority: P3)

**Goal**: JSONL export, per-thread archive/restore, bulk 72h archive (deferred until P1/P2 shipped).

**Independent Test**: Export row count matches inbox; archive removes from active list; restore returns thread (see `quickstart.md` §10).

### Implementation for User Story 7

- [x] T053 [US7] Add `scripts/sql/002_archive_messages.sql` for `archive_messages` table per `data-model.md`
- [x] T054 [US7] Implement `archive_conversation`, `restore_conversation`, `bulk_archive_idle`, and `export_messages_jsonl` in `src/digital_twin/conversation_store.py`
- [x] T055 [US7] Add P3 admin routes (`/admin/conversations/export`, archive, restore, bulk) in `src/digital_twin/admin_routes.py`
- [x] T056 [P] [US7] Add archive/export tests in `tests/test_admin_archive.py`
- [ ] T057 [US7] Add Archive tab, download button, and bulk archive UI in `ak47.github.io/no_ego/src/pages/digital-twin-admin-archive.js`

**Checkpoint**: Operational backup and inbox hygiene without data loss.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Docs, rate limits, observability, and production validation.

- [x] T058 [P] Implement DB-backed per-conversation rate limit in `src/digital_twin/rate_limit.py` when `DATABASE_URL` set (FR-018)
- [x] T059 [P] Update `docs/architecture.md` with Cloud SQL, admin OAuth, and escalation email flows
- [x] T060 Update root `README.md` with admin OAuth setup, allowlist, and local Postgres quickstart link to `specs/001-conversation-persistence-admin/quickstart.md`
- [ ] T061 [P] Update `ak47.github.io/docs/digital-twin-001-frontend-requirements.md` checkboxes for completed phases
- [x] T062 Run full `uv run pytest -q tests` and fix regressions
- [ ] T063 Execute production smoke checklist in `specs/001-conversation-persistence-admin/quickstart.md` §9

---

## Dependencies & Execution Order

### Phase Dependencies

```text
Phase 1 (Setup) → Phase 2 (Foundational) → US1 → US2 → US3 → US4/US5/US6 (P2, partial parallel) → US7 (P3) → Polish
```

### User Story Dependencies

| Story | Depends on | Notes |
|-------|------------|-------|
| **US1** | Phase 2 | MVP — public persistence only |
| **US2** | US1 (messages exist) | Admin read paths |
| **US3** | US2 | Reply + frontend admin |
| **US4** | US1, US3 (optional) | Escalation on chat turn |
| **US5** | US1, US3 | Poll endpoint + frontend |
| **US6** | US2 | Admin auth required |
| **US7** | US1–US3 | P3 defer |

### Parallel Opportunities

**After Phase 2 completes:**

- T019 + T020 (US1 tests) in parallel
- T026 + T027 (US2 tests) in parallel

**After US3 completes:**

- US4 backend (T035–T040) ∥ US5 frontend (T042–T045) ∥ US6 backend (T046–T050)

**Polish:**

- T058 + T059 + T061 in parallel

### Parallel Example: User Story 2

```bash
# Tests in parallel after routes exist:
Task T026: tests/test_admin_auth.py
Task T027: tests/test_admin_routes.py
```

### Parallel Example: P2 stories

```bash
# Different repos — no file conflicts:
Developer A: T035–T040 (escalation email, digital_twin)
Developer B: T042–T045 (polling UI, ak47.github.io)
Developer C: T046–T050 (instructions API, digital_twin)
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Complete Phase 1 + Phase 2  
2. Complete Phase 3 (US1)  
3. **STOP and VALIDATE** — `quickstart.md` §2  
4. Deploy API with DB; visitor chat persists on reload  

### Incremental Delivery (recommended)

1. Setup + Foundational  
2. **US1** → persist + reload  
3. **US2 + US3** → admin inbox + owner reply (P1 human-in-the-loop)  
4. **US4 + US5 + US6** → email alerts, live polling, instructions (P2)  
5. **US7** → archive/export when ops need it (P3)  
6. Polish  

### Suggested MVP scope

**Minimum shippable increment**: Phase 1 + Phase 2 + **US1** (tasks T001–T020).  
**Full P1 spec**: through **US3** (tasks T001–T034).

---

## Notes

- Frontend paths use absolute sibling repo `ak47.github.io/no_ego/`; adjust if admin route names differ during implement.
- When `DATABASE_URL` is unset, retain GCS/memory session path for local unit tests without Postgres.
- Total tasks: **63** (T001–T063).
- Per-story counts: Setup 4, Foundational 8, US1 8, US2 7, US3 7, US4 6, US5 5, US6 7, US7 5, Polish 6.
