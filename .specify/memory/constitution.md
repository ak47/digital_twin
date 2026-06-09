<!--
Sync Impact Report
- Version change: (unversioned template) → 1.0.0
- Modified principles: initial adoption — all template placeholders filled
- Added sections: Technology & Platform Constraints; Development Workflow & Quality Gates
- Removed sections: none
- Templates requiring updates:
  - .specify/templates/plan-template.md ✅ updated (Constitution Check gates)
  - .specify/templates/spec-template.md ✅ no changes required
  - .specify/templates/tasks-template.md ✅ no changes required
  - .specify/templates/commands/*.md ⚠ not present in repo (skipped)
- Follow-up TODOs: none
-->

# digital_twin Constitution

## Core Principles

### I. Infrastructure as Code (Terraform-First)

All GCP resources (Cloud Run, GCS, Vertex RAG, IAM, Scheduler, alerting) MUST be
defined and changed through Terraform in `terraform/`. Manual console changes that
drift from Terraform state are prohibited unless followed immediately by a
Terraform commit that restores the desired state. GitHub Actions workflows MUST
align with Terraform outputs (WIF, remote state bucket, CORS, corpus resource
names).

**Rationale**: Prevents environment drift between local, CI, and production; keeps
deploy and ingest workflows reproducible.

### II. Structured Observability

API and job code MUST emit structured JSON logs with correlation fields
(`request_id`, `session_id`, `trace_id` where applicable). Error paths MUST log
named events including `error_type`, `error_code`, and `where`. New failure
modes MUST use identifiable event names compatible with Cloud Logging alert
policies provisioned in Terraform.

**Rationale**: Cloud Run instances are ephemeral; structured logs are the primary
production debugging and alerting surface.

### III. CI-Validated Changes

Any change to `src/` or `tests/` MUST pass `uv run pytest -q tests` locally and
in GitHub Actions CI before merge. Dependencies MUST remain pinned via
`uv.lock`; CI MUST use `uv sync --frozen --extra dev`.

**Rationale**: The API serves live chat traffic; regressions must be caught before
deploy to Cloud Run.

### IV. RAG Content Lifecycle Separation

Knowledge-base files MUST NOT be baked into the container image. Curated sources
live in GCS under the `rag-sources/` prefix and are imported via
`scripts/ingest_rag_corpus.py` or the **Ingest RAG corpus** GitHub Action.
Content-only updates MUST NOT require API redeploy when `RAG_CORPUS_RESOURCE` is
unchanged.

**Rationale**: Decouples content freshness from application releases and reduces
deploy risk for copy or knowledge updates.

### V. Simplicity & Minimal Scope

Features and pull requests MUST solve the stated problem with the smallest
correct diff. YAGNI applies: do not add abstractions, environment variables, or
infrastructure until a concrete need exists. Complexity that violates these
principles MUST be documented in the plan's **Complexity Tracking** table with
rejected simpler alternatives.

**Rationale**: Keeps the Cloud Run + Vertex operational surface manageable for a
small team.

## Technology & Platform Constraints

- **Language**: Python ≥3.13; package management via **uv** (`uv sync`, `uv run`)
- **API**: FastAPI on Cloud Run (`linux/amd64` images via Artifact Registry)
- **AI**: Vertex AI Gemini for generation; optional Vertex RAG Engine for retrieval
- **Storage**: GCS for sessions and RAG corpus (no alternate database without an
  explicit constitution amendment)
- **Frontend**: Out of repository; CORS origins required via Terraform variable
  `cors_allowed_origins` and deploy variable `CORS_ALLOWED_ORIGINS`
- **Region defaults**: `us-central1` unless a documented multi-region exception
  applies (for example RAG ingest backup region)
- **Secrets**: Prefer GCP-native secret delivery (Secret Manager, WIF); avoid
  committing credentials

## Development Workflow & Quality Gates

- Feature work follows Spec Kit flow: `/speckit-specify` → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-implement`
- Plans MUST include **Constitution Check** gates before Phase 0 research and
  after Phase 1 design
- Terraform changes run through `.github/workflows/terraform.yml` (plan on PR;
  apply per workflow policy)
- API deploy via `.github/workflows/deploy-api.yml`; requires repository variable
  `CORS_ALLOWED_ORIGINS`
- Documentation MUST be updated when behavior, environment variables, or operator
  workflows change (`README.md`, `docs/`, `terraform/README.md` as applicable)

## Governance

- This constitution supersedes ad-hoc practices for the **digital_twin**
  repository
- Amendments are made via `/speckit-constitution` with a semver version bump:
  - **MAJOR**: backward-incompatible principle removals or redefinitions
  - **MINOR**: new principles or materially expanded guidance
  - **PATCH**: clarifications, wording, or non-semantic refinements
- All feature plans and pull requests SHOULD verify compliance with Core
  Principles; violations require explicit justification in **Complexity Tracking**
- Runtime development guidance lives in `README.md`, `docs/architecture.md`, and
  `terraform/README.md`

**Version**: 1.0.0 | **Ratified**: 2026-06-09 | **Last Amended**: 2026-06-09
