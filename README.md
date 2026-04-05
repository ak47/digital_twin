# digital_twin

Private GCP backend for the **no-ego** “career chat” widget (Vertex AI RAG + Gemini Flash, Cloud Run, GCS sessions).  
Public UI lives in **ak47.github.io**; this repo holds **Terraform**, application code, corpus, and prompts.

## Requirements

- Terraform **≥ 1.5**
- `gcloud` authenticated with permissions to enable APIs and create resources in your GCP project
- **New dedicated GCP project** (isolated from other workloads)

### Troubleshooting: `invalid_grant` / `invalid_rapt` / “reauth related error”

The Terraform Google provider uses **Application Default Credentials** (ADC). If your saved refresh token is stale or your org requires **re-auth** (RAPT), API calls fail with OAuth errors when enabling services.

**Fix (run locally in a terminal — browser may open):**

```bash
# 1) Refresh user login used by gcloud
gcloud auth login

# 2) Refresh ADC (what Terraform usually picks up)
gcloud auth application-default login

# 3) Confirm project and account
gcloud auth list
gcloud config get-value project
```

If it still fails: revoke and sign in again:

```bash
gcloud auth revoke
gcloud auth login
gcloud auth application-default login
```

**Workspace / admin note:** Some Google Workspace policies force periodic re-auth or block “less secure” flows. If errors persist, use an allowlisted account or a **service account key** (JSON) only for Terraform, with `GOOGLE_APPLICATION_CREDENTIALS` pointing to the key file — never commit the key.

**Project ID sanity check:** Your error referenced `gen-lang-client-0457840462`. IDs like `gen-lang-client-*` are often tied to **Google AI Studio / consumer Gemini** flows, not a normal empty project you created in Cloud Console. For this stack you typically want a **standard GCP project** where you are **Owner** or have **Service Usage Admin** + **Project IAM Admin** + billing. If Terraform targets the wrong project, set `TF_VAR_project_id` / `terraform.tfvars` to the intended project.

## Region

**`us-central1`** — set in `terraform/variables.tf` (default) or override via `terraform.tfvars`.

## Project ID (never commit)

Terraform does **not** read `.env`. Use one of:

1. **Environment variable (good for local apply):**
   ```bash
   export TF_VAR_project_id="your-real-project-id"
   cd terraform && terraform init && terraform plan
   ```
2. **Gitignored tfvars:** copy `terraform/terraform.tfvars.example` → `terraform.tfvars` and set `project_id`.

Optional: keep `GCP_PROJECT_ID` in `.env` for **local app runs** only (see `.env.example`). You can sync with shell:  
`export TF_VAR_project_id="$GCP_PROJECT_ID"` after `source .env`.

## What Terraform manages

| Area | Resources |
|------|-------------|
| APIs | Run, Artifact Registry, Storage, Vertex (aiplatform), Secret Manager, IAM Credentials, Compute |
| Storage | Corpus bucket (RAG source files) + sessions bucket (3-day lifecycle default) |
| Vertex RAG | `google_vertex_ai_rag_engine_config` — **BASIC** tier by default (variable `rag_engine_tier`) |
| IAM | Cloud Run service account: GCS object admin on both buckets, `roles/aiplatform.user` |
| Registry | Docker Artifact Registry repo `${name_prefix}-api` |
| Cloud Run | Service `${name_prefix}-api` (default image: public hello; override `container_image` after your first build) |
| Access | `allUsers` **run.invoker** — app enforces CORS + rate limits |

**RAG corpora / file ingestion:** The managed RAG *database tier* is in Terraform. Creating **corpora** and **importing files** is often done via API/CI (`gcloud`, Vertex RAG API, or ingestion scripts) so you can iterate without large Terraform churn. Outputs include bucket names for wiring ingest jobs.

## Custom domain

After apply, map **`digital_twin.no-ego.net`** to the Cloud Run service (domain mapping in console or `gcloud run domain-mappings create`). CORS allowlist is already parameterized (`cors_allowed_origins`).

## Remote state (optional)

Default is **local** `terraform.tfstate`. For GCS state, copy **`terraform/backend.tf.example`** → **`terraform/backend.tf`**, set **`bucket`** / **`prefix`**, then **`terraform init -migrate-state`** from **`terraform/`** (see **`terraform/README.md`**).

## Layout

```
terraform/          # All infrastructure
corpus/             # Curated documents for RAG (upload to corpus bucket)
prompts/            # Notes; bundled prompt at src/digital_twin/prompts/system.md
src/digital_twin/   # FastAPI Cloud Run app
Dockerfile
```

## Deploy the API container

**Infra + GitHub Actions secrets (short path):** **[`terraform/README.md`](terraform/README.md)** — then `./scripts/print-github-actions-secrets.sh`.  
**Longer runbook / smoke tests:** [`docs/WORKING.md`](docs/WORKING.md) if present.

Terraform may still reference a placeholder image until you push your image and run `terraform apply -var="container_image=..."` (or refresh after CI).

## What’s next (product order)

1. **Deploy fresh image** — **`docs/WORKING.md`** (`linux/amd64` + Terraform). While **custom DNS** propagates, use **`terraform output -raw cloud_run_uri`**.
2. **Custom domain** — `digital-twin.no-ego.net` (optional for dev; see WORKING).
3. **Shipped in v0.2:** **GCS sessions** (with `GCS_SESSIONS_BUCKET`), **Vertex Gemini Flash** (needs `GCP_PROJECT_ID` + ADC), **per-IP rate limit**, first-person **`system.md`**.
4. **RAG** — Set **`RAG_CORPUS_RESOURCE`** and ingest **`summary.txt` / PDF** from the corpus bucket (see **`docs/WORKING.md`**); personal files are **not** bundled in the image.
5. **no-ego widget** — Static JS on About (CORS already allowlisted).

**Tests:** `pip install ".[dev]" && pytest`

## Docs

Alignment and product decisions: **ak47.github.io** → `docs/resume-bot-gcp-github-pages-plan.md`.
