# RAG corpus: upload and ingest (Vertex AI)

This runbook is for operators who need to **put new source documents into production** and have them **indexed in Vertex RAG** so the Cloud Run API can retrieve them.

## Concepts

- **Corpus bucket** — GCS bucket created by Terraform; curated files are stored under the object prefix **`rag-sources/`** (configurable in `scripts/ingest_rag_corpus.py` via `--prefix`).
- **RagCorpus** — A Vertex RAG resource. The API env var **`RAG_CORPUS_RESOURCE`** is the full resource name (`projects/…/locations/…/ragCorpora/…`).
- **Ingest / import** — Calling Vertex **`import_files`** for one or more `gs://` URIs. Until you import, the bucket contents are **not** searchable by RAG.
- **Re-import** — Uploading new blobs under `rag-sources/` and running import again **into the same corpus** refreshes indexed content. You do **not** need a new corpus name or a new `RAG_CORPUS_RESOURCE` for routine content updates.

Terraform provisions the bucket, RAG Engine config (managed DB tier), and IAM for the Vertex service agent. It does **not** create the RagCorpus or run imports; that is done by **`scripts/ingest_rag_corpus.py`** or the console/API.

## First-time: create corpus, upload, import

From the **repository root**, with Application Default Credentials:

```bash
pip install -e .
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"

python3 scripts/ingest_rag_corpus.py \
  --project-id YOUR_PROJECT_ID \
  --files ./path/to/knowledge.txt ./path/to/Profile.pdf
```

- Omit **`--bucket`** to use `terraform output -raw corpus_bucket_name` (run from a clone where `terraform apply` has been done).
- **`--region`** defaults to **`us-central1`**. If RAG Engine creation is blocked there, use Terraform **`rag_corpus_ingest_region`** and ingest with **`--region`** set to that region; see [terraform/README.md](../terraform/README.md) → *RAG backup region*.

The script uploads objects to `gs://<bucket>/rag-sources/<filename>`, creates a corpus (unless **`--corpus-resource-name`** is passed), runs **`import_files`**, then prints **`RAG_CORPUS_RESOURCE`**.

Wire the API:

- **Terraform:** `rag_corpus_resource_name` in `terraform.tfvars` (or `TF_VAR_rag_corpus_resource_name`), then `terraform apply`.
- **GitHub Actions:** repository **Variable** `RAG_CORPUS_RESOURCE` with the same string (deploy workflow can merge env into Cloud Run).

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
2. Repository **Variables**: **`CORPUS_BUCKET_NAME`**, **`RAG_CORPUS_RESOURCE`** (required). Optional **`RAG_INGEST_REGION`** if the corpus is not in `us-central1` and the name does not embed a location (workflow default is `europe-west4` when not inferable — align this with your corpus).
3. Run workflow **[Ingest RAG corpus](https://github.com/ak47/digital_twin/actions)** (**workflow_dispatch**).

The workflow runs `ingest_rag_corpus.py` with **`--skip-upload`**. With **`--skip-upload`**, the script imports the **entire prefix** `gs://<bucket>/rag-sources/`; the **`--files`** argument in the workflow exists only to satisfy the CLI parser and does **not** limit which bucket objects are imported.

**Option B — Local**

```bash
pip install -e .
gcloud auth application-default login

python3 scripts/ingest_rag_corpus.py \
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

- Confirm **`RAG_CORPUS_RESOURCE`** on the service matches the corpus you imported into (Terraform output / GitHub Variable / `gcloud run services describe`).
- Retrieval uses the **location embedded in the corpus resource name**; Gemini generation uses **`GCP_REGION`** on the service. See [architecture.md](architecture.md).

## Troubleshooting

- **`import_files` 500** — Run **`terraform apply`** so RAG Engine config and corpus bucket IAM for the Vertex AI service agent are present, then retry.
- **Allowlist / RAG Engine region** — See [terraform/README.md](../terraform/README.md) → *RAG* and *RAG backup region*.
- **CI ingest fails on secrets/variables** — The workflow checks for the same GCP secrets as deploy and for **`CORPUS_BUCKET_NAME`** and **`RAG_CORPUS_RESOURCE`**. See [.github/workflows/ingest-rag-corpus.yml](../.github/workflows/ingest-rag-corpus.yml).

## Related

- [architecture.md](architecture.md) — diagrams and component notes.
- [terraform/README.md](../terraform/README.md) — bucket outputs, `rag_corpus_ingest_region`, `rag_engine_tier`.
- `scripts/ingest_rag_corpus.py` — full CLI (`--import-result-sink`, retries, embedding model).
