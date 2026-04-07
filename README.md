# digital_twin

[![CI](https://github.com/ak47/digital_twin/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ak47/digital_twin/actions/workflows/ci.yml)

Backend for the **no-ego** career chat experience: a **FastAPI** service on **Cloud Run** that streams replies with **Vertex AI Gemini**, optional **Vertex RAG Engine** retrieval over a **GCS** corpus bucket, and optional **GCS-backed chat sessions** (with an optional **idle session digest** job).

The public widget and marketing site live on **GitHub Pages** ([ak47.github.io](https://ak47.github.io)); this repository contains **Terraform**, the API source, ingestion tooling, and prompts.

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/architecture.md](docs/architecture.md) | System diagram, request flow, deployment and RAG lifecycle (high level) |
| [docs/rag-ingestion.md](docs/rag-ingestion.md) | **How to publish new RAG source files and ingest them into Vertex RAG in production** |
| [terraform/README.md](terraform/README.md) | First-time GCP setup, Terraform apply, GitHub Actions secrets, custom domain, remote state |
| [docs/session-digest.md](docs/session-digest.md) | Optional email transcript job (Workspace, Gmail API, Terraform variables) |
| [docs/troubleshooting-gcp-auth.md](docs/troubleshooting-gcp-auth.md) | `invalid_grant` / ADC / Terraform provider auth |

Product alignment notes (widget + Pages plan): [`ak47.github.io` / `docs/resume-bot-gcp-github-pages-plan.md`](https://github.com/ak47/ak47.github.io/blob/main/docs/resume-bot-gcp-github-pages-plan.md).

## Updating RAG knowledge in production

Vertex does **not** watch the bucket automatically. After content is in **GCS**, you run an **import** into the existing **RagCorpus** (same `RAG_CORPUS_RESOURCE`).

1. **Upload** new or changed files under `gs://<corpus-bucket>/rag-sources/` (for example with `gcloud storage cp` or any GCS client). Bucket name: `terraform output -raw corpus_bucket_name` from `terraform/`.
2. **Ingest** — either run the GitHub Action **“Ingest RAG corpus”** (manual dispatch) or locally `python scripts/ingest_rag_corpus.py … --skip-upload` so Vertex re-imports the **`rag-sources/`** prefix into the corpus already wired to Cloud Run.
3. **No API redeploy** is required for content-only updates if `RAG_CORPUS_RESOURCE` is already set; retrieval uses the same corpus resource name.

Full prerequisites (WIF, Actions variables, regions, first-time corpus creation) are in **[docs/rag-ingestion.md](docs/rag-ingestion.md)**.

## Quick start (local)

```bash
pip install ".[dev]"
pytest -q
```

Run the API locally with variables from [`.env.example`](.env.example). Terraform does **not** read `.env`; use `TF_VAR_project_id` or `terraform/terraform.tfvars` for infrastructure (see [terraform/README.md](terraform/README.md)).

## Deploy API to Cloud Run

1. Apply Terraform in `terraform/` (creates buckets, RAG engine config, Artifact Registry, Cloud Run service, WIF for GitHub, etc.).
2. Add the three GitHub Actions **secrets** printed by `./scripts/print-github-actions-secrets.sh`.
3. Push to `main` (or run **Deploy API** manually); [.github/workflows/deploy-api.yml](.github/workflows/deploy-api.yml) builds `linux/amd64`, pushes the image, and updates the service.

Optional repository **Variables** (for example `RAG_CORPUS_RESOURCE`, `CORS_ALLOWED_ORIGINS`) are described in `terraform/README.md` and [docs/architecture.md](docs/architecture.md).

**Region:** Default compute / primary Terraform region is **`us-central1`** ([terraform/variables.tf](terraform/variables.tf)). RAG ingest may use a different region if you configured `rag_corpus_ingest_region` (see [docs/rag-ingestion.md](docs/rag-ingestion.md)).

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
| Vertex | RAG Engine config (tier via `rag_engine_tier`), Gemini/RAG APIs enabled |
| Cloud Run | API service; optional session-digest **job** + **Scheduler** |
| IAM | Runtime service account, bucket access, `aiplatform.user`, GitHub WIF |

Details and tables: [terraform/README.md](terraform/README.md) and [docs/architecture.md](docs/architecture.md).

## Optional: custom domain

Set `cloud_run_custom_domain` in Terraform (see [terraform/README.md](terraform/README.md)). CORS is configured with `cors_allowed_origins`.

## Optional: remote Terraform state

Copy [terraform/backend.tf.example](terraform/backend.tf.example) to `backend.tf`, set bucket and prefix, then `terraform init -migrate-state`. Use a **dedicated** state bucket, not the RAG corpus bucket.
