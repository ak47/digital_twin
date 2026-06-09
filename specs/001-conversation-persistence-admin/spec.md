# Feature Specification: Conversation Persistence & Owner Responses

**Feature Branch**: `001-conversation-persistence-admin`

**Created**: 2026-06-09

**Status**: Draft

**Input**: User description: "Incorporate ideas from the ed-donner/avatar backend (more branch), particularly adding a database to retain conversation history and an ability for the owner to respond to requests submitted via the digital twin. Compare with docs/MORE.md expanded features and the current digital_twin GCS-session + email-digest architecture. Frontend lives in ak47.github.io (no_ego)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Durable conversation history (Priority: P1)

A site visitor chats with the digital twin on the resume/portfolio page. Their messages and the twin's replies are stored as an ordered thread tied to a conversation identifier. If the visitor returns later (same browser session or after a refresh), they see the full thread instead of starting from scratch.

**Why this priority**: Without durable history, every page reload loses context and the owner cannot review what visitors asked. This is the foundation for every other capability in this feature.

**Independent Test**: Start a conversation, send several messages, reload the page, and confirm the full transcript reappears in order with correct speaker attribution (visitor vs twin).

**Acceptance Scenarios**:

1. **Given** a new visitor with no prior conversation, **When** they send a first message, **Then** a new conversation is created and both the visitor message and twin reply are persisted.
2. **Given** an existing conversation identifier stored in the visitor's browser, **When** the visitor reloads the page, **Then** all prior messages for that conversation are returned in chronological order.
3. **Given** a long conversation, **When** the visitor sends another message, **Then** the twin receives sufficient prior context to reply coherently without the visitor re-stating earlier details.

---

### User Story 2 - Owner inbox and thread review (Priority: P1)

The site owner signs into a protected admin experience using **Google account sign-in**. Only Google accounts whose email address appears on a **hardcoded allowlist** (maintained in application configuration) are granted access; all others are rejected after authentication. Once signed in, the owner sees a list of all visitor conversations, sorted by most recent activity. Each row shows enough context to decide whether to open it (preview text, message count, whether it needs attention, whether there are unread twin replies). Opening a conversation shows the full transcript including visitor messages, twin replies, and any owner messages already sent.

**Why this priority**: The owner must be able to discover and read visitor requests before they can respond. This mirrors the inbox pattern from the reference avatar project and replaces reliance on idle email digests as the only awareness channel.

**Independent Test**: Create two separate visitor conversations via the public chat, sign in with an allowlisted Google account, and confirm both appear in the inbox with accurate previews and full thread detail on open.

**Acceptance Scenarios**:

1. **Given** the owner is not authenticated, **When** they attempt to access the admin conversation list, **Then** access is denied.
2. **Given** a user completes Google sign-in with an email **not** on the allowlist, **When** the system validates their identity, **Then** admin access is denied and no admin session is issued.
3. **Given** a user completes Google sign-in with an email **on** the allowlist, **When** the system validates their identity, **Then** an authenticated admin session is established.
4. **Given** multiple conversations exist, **When** the allowlisted owner opens the inbox, **Then** conversations are ordered by most recent activity and each summary shows preview, count, and attention/unread indicators where applicable.
5. **Given** the owner opens a specific conversation, **When** the thread loads, **Then** every message is shown with role, content, and timestamp, and unread/attention flags for that conversation are cleared.

---

### User Story 3 - Owner replies in the live thread (Priority: P1)

When a visitor asks something the twin cannot answer, requests personal follow-up, or leaves contact details, the owner is alerted that the conversation needs attention **via email** (see User Story 4). The owner writes a reply from the admin experience; that reply appears in the visitor's thread as coming from the owner (distinct from the twin). The visitor sees the owner's message without sending a new prompt. On the visitor's next message to the twin, the twin treats the owner's words as authoritative and does not contradict or impersonate the owner.

**Why this priority**: This is the core human-in-the-loop capability the user requested—closing the loop on requests the twin escalates or cannot handle.

**Independent Test**: Trigger an escalation (or manually flag a conversation), post an owner reply from admin, confirm the visitor UI shows it on poll/refresh, then send a follow-up visitor message and confirm the twin acknowledges the owner's prior statement.

**Acceptance Scenarios**:

1. **Given** a conversation flagged as needing attention, **When** the owner posts a reply, **Then** the message is stored with an owner/human role and is visible in the admin thread immediately.
2. **Given** the owner has posted a reply, **When** the visitor's chat client refreshes or polls for updates, **Then** the owner message appears with distinct labeling from twin messages.
3. **Given** the owner has answered a visitor question directly, **When** the visitor asks a related follow-up, **Then** the twin's reply aligns with the owner's prior answer and does not override it.
4. **Given** the owner marks a conversation resolved, **When** no new escalation occurs, **Then** the needs-attention indicator is cleared while the transcript remains available.

---

### User Story 4 - Escalation when the twin cannot help (Priority: P2)

When the twin does not know an answer, or the visitor wants to get in touch, the twin tells the visitor honestly, records the question for the owner, and flags the conversation as needing attention. The owner receives a **timely email alert** outside the admin UI so they can respond without waiting for the scheduled idle-session digest. Push notifications (e.g., Pushover, as used in the reference avatar project) are **out of scope for this feature** and may be added in a future enhancement.

**Why this priority**: Email alerts make owner responses practical using infrastructure the project already has (Gmail digest); without them, the inbox only helps if the owner polls admin constantly.

**Independent Test**: Ask the twin a question outside its knowledge, confirm the conversation is flagged and the owner receives an escalation email within one minute.

**Acceptance Scenarios**:

1. **Given** a visitor asks something the twin cannot answer, **When** the twin responds, **Then** the conversation is marked needs-attention and the owner receives an email with conversation context and enough detail to open the thread in admin.
2. **Given** a visitor provides contact intent (e.g., email request), **When** the twin captures it, **Then** the owner receives an email with the contact detail and conversation context.
3. **Given** an escalation email was already sent for a conversation, **When** the owner opens and resolves it, **Then** duplicate emails for the same unresolved state are suppressed within a reasonable debounce window.
4. **Given** email delivery fails, **When** escalation occurs, **Then** the conversation remains needs-attention in the admin inbox and the failure is logged for operator review.

---

### User Story 5 - Visitor polling for owner messages (Priority: P2)

While a conversation is open, the visitor's chat periodically checks for new messages (especially owner replies) without requiring a full page reload. Polling frequency backs off when the thread is idle to reduce unnecessary load.

**Why this priority**: Owner replies are only useful if visitors see them promptly; the reference project solves this with incremental polling rather than SSE from admin to visitor.

**Independent Test**: With a visitor chat open, post an owner reply from admin; within the active polling interval, the visitor UI shows the new message without reload.

**Acceptance Scenarios**:

1. **Given** an active visitor chat, **When** the owner posts a reply, **Then** the visitor sees it within 15 seconds under normal activity.
2. **Given** no new messages for several minutes, **When** polling continues, **Then** the interval increases according to the idle ladder (active → short idle → longer idle).
3. **Given** the visitor sends a new message, **When** polling resumes, **Then** the interval resets to the most frequent tier.

---

### User Story 6 - Owner-editable additional instructions (Priority: P2)

The owner maintains a freeform Markdown block of extra guidance for the twin (e.g., current job search focus, topics to emphasize or avoid, temporary announcements). From the admin experience, they open an **Instructions** section, view the current text (empty initially), edit it, and save. Every new twin reply incorporates the latest saved instructions without redeploying the API or rebuilding knowledge files.

**Why this priority**: Lets the owner steer twin behavior in real time—complementing static RAG corpus and system prompt files. Matches the reference project's settings table pattern and docs/MORE.md.

**Independent Test**: Save instructions in admin, send a visitor message that should follow the new guidance, and confirm the twin's reply reflects it; change instructions again and confirm the next reply follows the update without restart.

**Acceptance Scenarios**:

1. **Given** no instructions have been saved, **When** the owner opens the Instructions section, **Then** they see an empty editable field and can save new Markdown content.
2. **Given** saved instructions exist, **When** the owner opens the Instructions section, **Then** the current Markdown is displayed and can be edited and saved.
3. **Given** the owner saves updated instructions, **When** a visitor sends the next chat message, **Then** the twin's reply is generated using the updated instructions (read fresh on that turn, not from a stale cache).
4. **Given** instructions are saved, **When** the owner clears the field and saves, **Then** subsequent twin replies behave as if no additional instructions exist.

---

### User Story 7 - Export and archive (Priority: P3)

The owner can export all active conversations to a portable file for backup or analysis, and can archive stale conversations to remove them from the active inbox while retaining the ability to restore them later. A bulk archive action applies to conversations with no activity for a configurable idle period (default 72 hours).

**Why this priority**: Valuable for operations and aligns with docs/MORE.md, but not required for the minimum viable human-in-the-loop loop.

**Independent Test**: Export conversations to a file and verify row count matches inbox; archive one thread and confirm it moves off the active list but can be restored with full transcript intact.

**Acceptance Scenarios**:

1. **Given** conversations exist in the active store, **When** the owner downloads the export, **Then** they receive a file containing one record per message with conversation metadata.
2. **Given** a conversation on the active list, **When** the owner archives it, **Then** it disappears from the active inbox but remains retrievable from an archive view.
3. **Given** archived conversations, **When** the owner restores one, **Then** it reappears in the active inbox with transcript intact.

---

### Edge Cases

- What happens when the visitor clears browser storage? They receive a new conversation identifier; prior thread remains in the owner's inbox but is not linked on the visitor side unless they retain the old id.
- How does the system handle concurrent owner and visitor messages? All messages are ordered by persistence timestamp; no message is lost; the twin sees the full ordered transcript on the next turn.
- What happens when persistence fails mid-reply? The visitor sees an error or warning; the partial turn is not presented as complete; the owner inbox reflects only successfully stored messages.
- What happens when an unauthorized party guesses a conversation identifier? They can read that thread's messages (same risk model as the reference project); admin and write paths remain protected.
- What happens during API replica scale-out? Conversation reads and writes remain consistent; rate limits and notifications must not depend solely on single-instance memory.
- What happens when escalation email delivery fails? The conversation remains flagged needs-attention in the inbox; failure is logged for operator review; no Pushover or other push fallback is required in this feature.
- What happens when additional instructions exceed a reasonable size? Saving is rejected or truncated with a clear admin error; the prior saved value remains in effect for twin generation.
- What happens when a Google account authenticates successfully but its email is not on the allowlist? Access is denied with a clear message; the attempt is logged; no partial admin session is created.
- What happens when the allowlist is updated? Only accounts on the new list can obtain a session on next sign-in; existing sessions for removed emails expire or are invalidated on the next request.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST persist every visitor message and twin reply as individual records within a conversation, ordered chronologically.
- **FR-002**: System MUST assign each new visitor session a stable conversation identifier returned to the client and reusable on subsequent requests.
- **FR-003**: System MUST return the full message history for a conversation to authorized visitor clients that present the conversation identifier.
- **FR-004**: System MUST support three speaker roles in storage and APIs: visitor, twin (assistant), and owner (human).
- **FR-005**: System MUST authenticate admin users via Google account sign-in; unauthenticated access to admin capabilities MUST be denied.
- **FR-005a**: System MUST maintain a hardcoded allowlist of permitted Google account email addresses; only sign-ins whose verified email is on the allowlist MAY receive an admin session.
- **FR-005b**: System MUST reject allowlist failures after successful Google authentication (fail closed); MUST NOT issue admin sessions to non-allowlisted emails.
- **FR-005c**: Admin sessions MUST expire after a reasonable period; expired sessions MUST require re-authentication via Google sign-in.
- **FR-006**: System MUST provide an admin inbox listing all conversations with summary fields: identifier, optional display name, preview, last activity time, message count, unread indicator, and needs-attention indicator.
- **FR-007**: System MUST allow the owner to open a conversation and view the complete transcript.
- **FR-008**: System MUST allow the owner to post a message into a conversation that is stored with the owner role and visible to the visitor.
- **FR-009**: System MUST allow the owner to clear the needs-attention flag on a conversation (resolve) without deleting the transcript.
- **FR-010**: System MUST flag a conversation as needs-attention when the twin escalates (unknown answer, contact capture, or equivalent owner-handoff intent).
- **FR-011**: System MUST send an email alert to the owner when a conversation becomes needs-attention, including enough context to identify the conversation and the visitor's request (distinct from the scheduled idle-session digest email).
- **FR-011a**: Escalation emails MUST be debounced so repeated unresolved attention on the same conversation does not spam the owner within a reasonable window.
- **FR-011b** (future, out of scope): Push notifications via Pushover or similar MAY be added later as an optional channel; this feature does not require them.
- **FR-012**: System MUST expose an incremental fetch mechanism so visitors can retrieve messages newer than a given message id (polling).
- **FR-013**: Visitor polling intervals MUST follow a tiered backoff schedule during idle periods and reset to the fastest tier on new activity.
- **FR-014**: On each new visitor message, the twin MUST receive a transcript that includes prior owner messages and MUST treat owner messages as authoritative over conflicting twin statements.
- **FR-015**: System MUST continue to support the existing public chat send/receive flow used by the portfolio frontend (streaming twin replies).
- **FR-016**: System MUST emit structured operational logs for persistence failures, auth failures, and notification failures with correlation to conversation identifier.
- **FR-017**: System MUST cap individual visitor message length to prevent abuse, with a clear truncation or rejection behavior.
- **FR-018**: System MUST rate-limit chat submissions per conversation to mitigate abuse.
- **FR-019**: System MUST store owner additional instructions as a single editable Markdown document (initially empty) in durable storage separate from per-conversation messages.
- **FR-020**: System MUST expose admin read and write access to additional instructions only to authenticated owners.
- **FR-021**: System MUST load additional instructions fresh on every twin generation turn so admin edits take effect on the next visitor message without redeploy.
- **FR-022**: System MUST inject additional instructions into the twin's system context as a distinct section placed after all static prompt/knowledge content (editable block last, for cache-friendly static prefix ordering per docs/MORE.md post-build refinement).
- **FR-022a**: The admin experience MUST provide a main navigation tab for Instructions alongside Conversations (and Archive when P3 ships), sharing the same authenticated admin session.
- **FR-023** (P3): System MUST allow the owner to export active conversations to a downloadable archive file.
- **FR-024** (P3): System MUST support archiving and restoring whole conversations, and bulk-archiving conversations idle longer than a configurable threshold (default 72 hours).

### Key Entities

- **Conversation**: A thread between one visitor and the twin/owner; identified by a unique id; optional visitor display name; aggregate flags (needs-attention, unread for owner); last activity timestamp.
- **Message**: A single utterance in a conversation; attributes include conversation reference, speaker role (visitor | twin | owner), text content, optional tool-use metadata, read/attention flags, creation timestamp, and monotonic message id for polling.
- **Owner session**: Authenticated admin session established after Google sign-in and allowlist validation; grants access to inbox, reply, resolve, export, and archive capabilities.
- **Admin allowlist**: Fixed set of permitted Google account email addresses configured with the application; sole gate for who may use admin capabilities.
- **Escalation event**: Logical signal that a conversation requires owner attention, linked to one conversation and triggering an email alert to the owner.
- **Additional instructions**: A single global Markdown document owned by the site owner; not tied to a conversation; version is whatever was last saved; consumed on each twin turn.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of successfully completed chat turns are retrievable in the conversation history immediately after the twin finishes replying.
- **SC-002**: Owner can locate any conversation from the last 7 days in the inbox within 30 seconds of login.
- **SC-003**: Owner replies appear in the visitor chat within 15 seconds under normal polling during active sessions.
- **SC-004**: 95% of escalation events deliver an owner email alert within 60 seconds.
- **SC-005**: After an owner reply, 90% of follow-up visitor messages receive twin responses that do not contradict the owner's prior statement (evaluated by owner review sample).
- **SC-006**: Idle polling reduces request volume by at least 50% compared with fixed 10-second polling over a 30-minute inactive session.
- **SC-007**: Admin authentication blocks 100% of unauthenticated inbox/reply attempts in testing.
- **SC-007a**: 100% of Google sign-in attempts from non-allowlisted emails are denied admin access in testing.
- **SC-007b**: 100% of Google sign-in attempts from allowlisted emails succeed in obtaining admin access in testing.
- **SC-008**: After saving additional instructions, the next twin reply reflects the new content in 100% of tested cases (sample of representative prompts).
- **SC-009**: Additional instruction changes take effect on the next chat turn without API redeploy or container restart.

## Assumptions

- The public chat UI remains in the separate **ak47.github.io** (`no_ego`) repository; this feature defines API contracts and admin experience requirements that both repos must satisfy.
- Admin access is limited to Google accounts on a hardcoded email allowlist (initially the site owner; additional addresses require a configuration change and deploy). No shared password; no multi-tenant role model beyond allowlist membership in this phase.
- Visitors are anonymous; identity is limited to an optional display name and browser-stored conversation id.
- The existing Vertex-based twin and optional RAG retrieval remain the generation backend; this feature changes persistence and human-in-the-loop workflow, not the core model provider.
- The current constitution restricts storage to GCS for sessions; adopting message-level relational storage **requires a constitution amendment** during planning (Technology & Platform Constraints). Until amended, this spec describes required behavior, not a specific storage product.
- Escalation alerts are delivered by **email** (reusing or extending the existing Gmail/Workspace sending path used for idle session digests). The idle digest remains for inactive threads; escalation email is immediate on needs-attention.
- **Pushover** (or similar mobile push), as in the ed-donner/avatar reference, is a **future optional** channel—not in scope for 001.
- P3 export/archive capabilities are explicitly deferred; P1–P2 deliver the human-in-the-loop MVP including additional instructions.
- Additional instructions use a single-row settings pattern (one global document, not per-conversation), matching docs/MORE.md.
- Features from docs/MORE.md not listed here (FAQ database editor, web-fetch tool, OG image, `?m=` deep link, Pushover push notifications) are out of scope for this spec and may be specified separately.
- Local development and production both target the owner's GCP project; the reference project's "local Docker only / single shared Supabase" constraint does not apply to this repository.

## Dependencies

- Portfolio frontend (`ak47.github.io/no_ego`) must adopt conversation id handling, role-aware message rendering (visitor / twin / owner), polling for owner messages, and admin UI including an Instructions tab. Coordinated adoption plan: **`ak47.github.io/docs/digital-twin-001-frontend-requirements.md`**.
- Infrastructure planning must provision durable structured storage (constitution amendment), Google OAuth client configuration, hardcoded admin email allowlist, settings row for additional instructions, and escalation email recipient configuration (may align with existing digest recipients).
- Existing `GET/POST /api/chat` contract may require extension or parallel endpoints; backward compatibility for session header clients should be preserved during migration.

## Reference Comparison (context)

| Capability | ed-donner/avatar (`more`) | docs/MORE.md | digital_twin (today) | This spec |
|------------|---------------------------|--------------|----------------------|-----------|
| Message persistence | Supabase `messages` rows | + `archive`, settings, `faq` tables | GCS JSON per session | Per-message durable store (P1) |
| Owner inbox | Admin API + UI | + Archive/Instructions/FAQ tabs | None (email digest only) | Inbox + thread view (P1) |
| Owner reply | `human` role via admin POST | Same | Not supported | Owner role + visitor visibility (P1) |
| Escalation | `push_tool` → Pushover | + security hardening | Not supported | Flag + email alert (P2); Pushover future |
| Visitor sync | Poll `after_id` | Tiered polling ladder | Load history on mount only | Incremental poll + backoff (P2) |
| Additional instructions | In MORE (settings row) | Single-row Markdown; fresh per turn; last in system prompt | Static `system.md` only | Editable admin Instructions tab (P2) |
| Export / archive | Partial in MORE | JSONL download, 72h bulk | Digest email attachment | Export + archive (P3) |
| Auth | Cookie + password | Fail-closed password | None on API | Google sign-in + email allowlist (P1) |
