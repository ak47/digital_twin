# RAG corpus: upload and ingest (Vertex AI)

This runbook is for operators who need to **put new source documents into production** and have them **indexed in Vertex RAG** so the Cloud Run API can retrieve them.

## Concepts

- **Corpus bucket** — GCS bucket created by Terraform; curated files are stored under the object prefix **`rag-sources/`** (configurable in `scripts/ingest_rag_corpus.py` via `--prefix`).
- **RagCorpus** — A Vertex RAG resource. The API env var **`RAG_CORPUS_RESOURCE`** is the full resource name (`projects/…/locations/…/ragCorpora/…`).
- **Ingest / import** — Calling Vertex **`import_files`** for one or more `gs://` URIs. Until you import, the bucket contents are **not** searchable by RAG.
- **Re-import** — Uploading new blobs under `rag-sources/` and running import again **into the same corpus** refreshes indexed content. You do **not** need a new corpus name or a new `RAG_CORPUS_RESOURCE` for routine content updates.

Terraform provisions the bucket, IAM for the Vertex service agent, and (unless **`rag_engine_deployment_mode = "SERVERLESS"`**) the regional **RAG Engine** `google_vertex_ai_rag_engine_config` (Spanner tiers). It does **not** create the RagCorpus or run imports; that is done by **`scripts/ingest_rag_corpus.py`** or the console/API.

## Serverless RAG (optional, us-central1)

To avoid Terraform-managed **Cloud Spanner** for RAG, set **`rag_engine_deployment_mode = "SERVERLESS"`** and **`rag_corpus_ingest_region = ""`**. Run ingest with **`TF_VAR_rag_engine_deployment_mode=SERVERLESS`** or **`--rag-engine-deployment-mode SERVERLESS`** so **`ingest_rag_corpus.py`** applies **Serverless** via `vertexai.preview.rag` before **`create_corpus`**. Google documents Serverless as **preview** and **us-central1-only**; moving from Spanner in another region needs a **new** corpus in **`us-central1`** and an updated **`rag_corpus_resource_name`**. See [terraform/README.md](../terraform/README.md) → *Serverless RAG*.

## First-time: create corpus, upload, import

From the **repository root**, with Application Default Credentials:

```bash
uv sync
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"

uv run python scripts/ingest_rag_corpus.py \
  --project-id YOUR_PROJECT_ID \
  --files ./path/to/knowledge.txt ./path/to/Profile.pdf
```

- Omit **`--bucket`** to use `terraform output -raw corpus_bucket_name` (run from a clone where `terraform apply` has been done).
- **`--region`** defaults to **`us-central1`**. If RAG Engine creation is blocked there, use Terraform **`rag_corpus_ingest_region`** and ingest with **`--region`** set to that region; see [terraform/README.md](../terraform/README.md) → *RAG backup region*.

The script uploads objects to `gs://<bucket>/rag-sources/<filename>`, creates a corpus (unless **`--corpus-resource-name`** is passed), runs **`import_files`**, then prints **`RAG_CORPUS_RESOURCE`**.

Wire the API:

- **Terraform:** `rag_corpus_resource_name` in `terraform.tfvars` (or `TF_VAR_rag_corpus_resource_name`), then `terraform apply`. This is the **single source of truth** for Cloud Run **`RAG_CORPUS_RESOURCE`** and for **`terraform output rag_corpus_resource_name`** (used by the ingest workflow).
- **GitHub Actions (optional):** repository **Variable** `RAG_CORPUS_RESOURCE` on deploy **only** if you intentionally override Terraform without applying; leave it unset to avoid drift.

## Production content updates (existing corpus)

### 1. Upload to GCS

Put files under **`rag-sources/`** in the corpus bucket, for example:

```bash
BUCKET="$(terraform -chdir=terraform output -raw corpus_bucket_name)"
gcloud storage cp ./knowledge.txt "gs://${BUCKET}/rag-sources/"
# add or overwrite PDFs, markdown, etc.
```

Use the same bucket Terraform outputs as **`corpus_bucket_name`**.

### 2. Re-import into Vertex (same `RAG_CORPUS_RESOURCE`)

**Option A — GitHub Actions (recommended for prod)**

1. Repository **Secrets** (same as Deploy API): `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT_EMAIL`, `GCP_PROJECT_ID`.
2. **Terraform:** set **`gha_terraform_state_bucket`** in `terraform.tfvars` to the **same GCS bucket** as `terraform/backend.tf` (remote state), then **`terraform apply`**. That grants the GitHub deploy service account **`storage.objectViewer`** on the state bucket so CI can run **`terraform init`** and read **`corpus_bucket_name`** + **`rag_corpus_resource_name`** from state — **no** duplicate repository Variables `CORPUS_BUCKET_NAME` / `RAG_CORPUS_RESOURCE`.
3. In GitHub: **Actions** → workflow **Ingest RAG corpus** → **Run workflow** (**workflow_dispatch**).

The workflow runs `terraform init` / `terraform output`, then `ingest_rag_corpus.py` with **`--skip-upload`**. The job **fails** if Vertex reports any **failed** imports or the script exits on API/permission errors. An all-skipped import (**`imported=0`**, **`skipped>0`**) is **success** (idempotent re-import). With **`--skip-upload`**, the script imports the **entire prefix** `gs://<bucket>/rag-sources/`; the **`--files`** argument in the workflow exists only to satisfy the CLI parser and does **not** limit which bucket objects are imported.

**Option B — Local**

```bash
uv sync
gcloud auth application-default login

uv run python scripts/ingest_rag_corpus.py \
  --project-id YOUR_PROJECT_ID \
  --region REGION_MATCHING_CORPUS \
  --bucket YOUR_CORPUS_BUCKET \
  --corpus-resource-name 'projects/PROJECT/locations/REGION/ragCorpora/CORPUS_ID' \
  --skip-upload \
  --files .
```

`--files` is required by the parser but ignored when **`--skip-upload`** is set; any path is fine.

After a successful re-import, **Cloud Run does not need a new revision** for content-only changes.

### 3. If the API still looks stale

- Confirm **`RAG_CORPUS_RESOURCE`** on the service **exactly matches** **`rag_corpus_resource_name`** in Terraform state (and avoid setting the deploy workflow’s **`RAG_CORPUS_RESOURCE`** repository Variable unless you mean to override Terraform). A typo or an old corpus id means the app queries a different index than CI updates.
- After ingest, read **`Vertex import result: imported=…, skipped=…, failed=…`** in the Actions log. **`imported=0` with `skipped>0`** usually means Vertex treated GCS URIs as unchanged — overwriting a blob in place often **does not** re-embed; rename the object or delete the RagFile in the Vertex console, then re-import.
- Retrieval uses the **location embedded in the corpus resource name**; Gemini generation uses **`GEMINI_LOCATION` / `GCP_REGION`**. The API initializes Vertex retrieval using the **project in the corpus resource name** so it stays aligned even if **`GCP_PROJECT_ID`** on Cloud Run is wrong. See [architecture.md](architecture.md).

## Troubleshooting

- **`import_files` 500** — Run **`terraform apply`** so RAG Engine config and corpus bucket IAM for the Vertex AI service agent are present, then retry.
- **Allowlist / RAG Engine region** — See [terraform/README.md](../terraform/README.md) → *RAG* and *RAG backup region*.
- **CI ingest fails at `terraform init`** — Ensure **`gha_terraform_state_bucket`** matches **`backend.tf`** and **`terraform apply`** has granted the deploy SA read access to state. See [.github/workflows/ingest-rag-corpus.yml](../.github/workflows/ingest-rag-corpus.yml).

## Related

- [architecture.md](architecture.md) — diagrams and component notes.
- [terraform/README.md](../terraform/README.md) — bucket outputs, `rag_corpus_ingest_region`, `rag_engine_deployment_mode` (Spanner vs Serverless).
- `scripts/ingest_rag_corpus.py` — full CLI (`--import-result-sink`, retries, embedding model).
