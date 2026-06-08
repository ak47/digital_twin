# digital_twin

**CI:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) (GitHub Actions on push / PR).

Backend for a **career / profile chat** experience: a **FastAPI** service on **Cloud Run** that streams replies with **Vertex AI Gemini**, optional **Vertex RAG Engine** retrieval over a **GCS** corpus bucket, and optional **GCS-backed chat sessions** (with an optional **idle session digest** job).

Pair this API with any static frontend (for example **GitHub Pages**). **`cors_allowed_origins`** is a **required** Terraform variable (no default); set **`gha_terraform_state_bucket`** to the same value as backend init bucket (**`TF_STATE_BUCKET`**) so Terraform IAM and CI state access stay aligned. This repository contains **Terraform**, the API source, ingestion tooling, and prompts.

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/architecture.md](docs/architecture.md) | System diagram, request flow, deployment and RAG lifecycle (high level) |
| [docs/rag-ingestion.md](docs/rag-ingestion.md) | **How to publish new RAG source files and ingest them into Vertex RAG in production** |
| [terraform/README.md](terraform/README.md) | First-time GCP setup, Terraform apply, GitHub Actions secrets, custom domain, remote state |
| [docs/session-digest.md](docs/session-digest.md) | Optional email transcript job (Workspace, Gmail API, Terraform variables) |
| [docs/troubleshooting-gcp-auth.md](docs/troubleshooting-gcp-auth.md) | `invalid_grant` / ADC / Terraform provider auth |
| [docs/observability.md](docs/observability.md) | Error monitoring + alerting (Cloud Logging, Error Reporting, Monitoring) |

## Updating RAG knowledge in production

Vertex does **not** watch the bucket automatically. After content is in **GCS**, you run an **import** into the existing **RagCorpus** (same `RAG_CORPUS_RESOURCE`).

1. **Upload** new or changed files under `gs://<corpus-bucket>/rag-sources/` (for example with `gcloud storage cp` or any GCS client). Bucket name: `terraform output -raw corpus_bucket_name` from `terraform/`.
2. **Ingest** — either run the GitHub Action **“Ingest RAG corpus”** (manual dispatch) or locally `uv run python scripts/ingest_rag_corpus.py … --skip-upload` so Vertex re-imports the **`rag-sources/`** prefix into the corpus already wired to Cloud Run.
3. **No API redeploy** is required for content-only updates if `RAG_CORPUS_RESOURCE` is already set; retrieval uses the same corpus resource name.

Full prerequisites (WIF, Actions variables, regions, first-time corpus creation) are in **[docs/rag-ingestion.md](docs/rag-ingestion.md)**.

## Python toolchain

Use **[uv](https://docs.astral.sh/uv/)** for environments and commands (`uv sync`, `uv run python`, `uv run pytest`). Commit **`uv.lock`** is the source of truth for CI and Docker builds.

## Quick start (local)

```bash
uv sync --extra dev
uv run pytest -q
```

Run the API locally with variables from [`.env.example`](.env.example). Terraform does **not** read `.env`; use `TF_VAR_project_id` or `terraform/terraform.tfvars` for infrastructure (see [terraform/README.md](terraform/README.md)).

## Deploy API to Cloud Run

1. Apply Terraform in `terraform/` (creates buckets, RAG engine config, Artifact Registry, Cloud Run service, and optionally **WIF for GitHub** when **`github_repository`** is set in **`terraform.tfvars`**).
2. Add the GitHub Actions **secrets** from `./scripts/print-github-actions-secrets.sh` once WIF outputs exist (**GCP** trio + **`TERRAFORM_TFVARS`** if you use [`.github/workflows/terraform.yml`](.github/workflows/terraform.yml)). If you left **`github_repository`** empty, use another deploy auth path (for example JSON keys) instead of those outputs.
3. Set repository **Variable** **`CORS_ALLOWED_ORIGINS`** (comma-separated, same origins as Terraform **`cors_allowed_origins`**). **Deploy API** fails fast if it is missing so the workflow cannot drift to generic defaults.
4. Push to `main` (or run **Deploy API** manually); [.github/workflows/deploy-api.yml](.github/workflows/deploy-api.yml) builds `linux/amd64`, pushes the image, and updates the service.

Optional repository **Variables** for deploy (for example **`GEMINI_MODEL`**, **`CORS_ALLOWED_ORIGINS`**) are described in `terraform/README.md` and [docs/architecture.md](docs/architecture.md). **`RAG_CORPUS_RESOURCE`** is Terraform-only. **Ingest RAG corpus** reads **`corpus_bucket_name`** and **`rag_corpus_resource_name`** from remote Terraform state — no separate GitHub Variables for those.

**Region:** Default compute / primary Terraform region is **`us-central1`** ([terraform/variables.tf](terraform/variables.tf)). RAG ingest may use a different region if you configured `rag_corpus_ingest_region` (see [docs/rag-ingestion.md](docs/rag-ingestion.md)).

## Structured logging and error monitoring

The API now emits **structured JSON logs** across app handlers and uvicorn output, with request/session correlation fields for easier triage.

- Shared schema includes `event`, `severity`, `service`, `env`, `timestamp`, `request_id`, `trace_id`, `session_id`
- Error events include `error_type`, `error_code`, `where`, `exception_message`, and `stacktrace`
- `POST /api/chat` emits named events such as:
  - `chat_model_invocation_failed`
  - `chat_session_persist_failed`
  - `chat_request_completed`

Terraform keeps coarse fallback alerts and now also provisions event-focused policies:

- `${name_prefix} API errors` (existing broad `severity>=ERROR`)
- `${name_prefix} API critical events` (structured event failures)
- `${name_prefix} API sustained errors` (elevated error volume window)
- `${name_prefix} digest job failures`

See [docs/observability.md](docs/observability.md) for Cloud Logging query examples, rollout checks, and rollback guidance.

## Repository layout

| Path | Role |
|------|------|
| `terraform/` | GCP infrastructure (Cloud Run, GCS, Vertex RAG engine, IAM, optional domain mapping, digest job) |
| `src/digital_twin/` | FastAPI app, LLM + RAG, sessions, rate limits |
| `scripts/ingest_rag_corpus.py` | Upload corpus files to GCS and/or import into Vertex RAG |
| `.github/workflows/` | CI, deploy API, manual RAG ingest |
| `prompts/` | Notes; packaged system prompt lives in `src/digital_twin/prompts/system.md` |

Curated **RAG source files** are typically kept in-repo (for example under a folder you choose) or produced elsewhere, then **uploaded** to `gs://…/rag-sources/` for ingestion — they are **not** baked into the container image.

## What Terraform manages (summary)

| Area | Notes |
|------|--------|
| GCS | Corpus bucket (RAG sources under `rag-sources/`) and sessions bucket (optional lifecycle) |
| Vertex | RAG Engine mode via `rag_engine_deployment_mode` (Spanner tiers or SERVERLESS), Gemini/RAG APIs enabled |
| Cloud Run | API service; optional session-digest **job** + **Scheduler** |
| IAM | Runtime service account, bucket access, `aiplatform.user`, GitHub WIF |

Details and tables: [terraform/README.md](terraform/README.md) and [docs/architecture.md](docs/architecture.md).

## Optional: custom domain

Set `cloud_run_custom_domain` in Terraform (see [terraform/README.md](terraform/README.md)). CORS is configured with required variable **`cors_allowed_origins`** (and the **`CORS_ALLOWED_ORIGINS`** Actions variable on deploy).

## Terraform remote state

[terraform/backend.tf](terraform/backend.tf) configures shared **GCS** backend settings; provide the bucket at init time with `terraform init -backend-config="bucket=${TF_STATE_BUCKET}"` (same for GitHub Actions via repository Variable `TF_STATE_BUCKET`). Create the bucket and migrate once if needed — see [terraform/README.md](terraform/README.md). Use a **dedicated** state bucket, not the RAG corpus bucket. [terraform/backend.tf.example](terraform/backend.tf.example) is an optional full-backend template.
