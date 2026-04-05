# Terraform — digital_twin

**Backend:** This stack uses a **partial `gcs` backend** (`backend "gcs" {}`). Use **`terraform init -backend-config=backend.hcl`** after copying **`backend.hcl.example`**, or **`terraform init -backend=false`** to keep local state (no remote bucket).

## Minimal flow

1. **One env var** (or use gitignored `terraform.tfvars` with `project_id = "..."`):

   ```bash
   export TF_VAR_project_id="YOUR_PROJECT_ID"
   ```

2. **Init** (first time / new clone):

   ```bash
   cd terraform
   # Pick one:
   # A) Remote state — cp backend.hcl.example backend.hcl, edit bucket, then:
   #    terraform init -backend-config=backend.hcl
   #    # First migration from local state:
   #    terraform init -backend-config=backend.hcl -migrate-state
   # B) Local state only:
   terraform init -backend=false
   ```

3. **Apply** (creates GCP resources; GitHub deploy wiring defaults to repo `ak47/digital_twin`):

   ```bash
   terraform apply
   ```

4. **GitHub secrets** (once per project / after WIF changes). From repo root:

   ```bash
   ./scripts/print-github-actions-secrets.sh
   ```

   Paste the three lines into **Settings → Secrets and variables → Actions**.

5. **CI** — `deploy-api.yml` builds and deploys the container; `ingest-rag-corpus.yml` re-imports an existing corpus from GCS (manual upload first). Neither job runs `terraform apply` by default.

### If `WorkloadIdentityPool` returns **409 already exists**

An old pool id may exist in GCP but not in Terraform state. This stack now uses pool id **`{name_prefix}-gha-wif`** (default `digital-twin-gha-wif`) so a fresh apply can succeed. You may delete the unused pool **`digital-twin-github`** in the GCP console (IAM → Workload Identity Federation) if it is still there.

### RAG: upload `knowledge.txt` / `Profile.pdf` and ingest

Terraform creates the **corpus GCS bucket**, **RAG engine config** in **`var.region`** (default `us-central1`), provisions the **Vertex AI service identity** for `aiplatform.googleapis.com`, then grants that principal **`storage.objectViewer`** on the corpus bucket. Optional **`rag_corpus_ingest_region`** adds a second RAG Engine region for non-default ingest layouts. You still **upload files** and **create a RAG corpus + import** (Vertex does not auto-read the bucket).

1. **Bucket name** (after `terraform apply`):

   ```bash
   terraform output -raw corpus_bucket_name
   ```

2. **One-shot (upload + create corpus + import)** from the **repo root**, with local files (paths are examples):

   ```bash
   pip install -e .
   gcloud auth application-default login
   export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"   # or --project-id

   python3 scripts/ingest_rag_corpus.py \
     --project-id YOUR_PROJECT_ID \
     --files ./knowledge.txt ./Profile.pdf
   ```

   Omit `--bucket` to pull the bucket name from `terraform output corpus_bucket_name`. Objects land under `gs://<bucket>/rag-sources/`.

   **Region:** RAG corpus create/import uses **`us-central1`** by default (same as **`var.region`**). The app resolves retrieval from **`RAG_CORPUS_RESOURCE`**; Gemini uses **`GCP_REGION`** on Cloud Run. If corpus creation fails with an allowlist error, request **RAG Engine access in `us-central1`** for your project from Google Cloud support (see error text for the support channel).

#### RAG backup region (when `us-central1` corpus creation is blocked)

Google may block **RAG Engine** in `us-central1` for new projects until allowlisted. You can still run the **API and Gemini in `us-central1`** while hosting the **RAG corpus in another [supported region](https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-overview#supported-regions)** (commonly **`europe-west4`**).

1. In **`terraform.tfvars`**: `rag_corpus_ingest_region = "europe-west4"`
2. **`terraform apply`** (creates a second `google_vertex_ai_rag_engine_config` there; corpus bucket stays in `us-central1`)
3. Ingest with **`--region europe-west4`** (same as `ingest_rag_corpus.py` / stderr instructions)
4. Set **`rag_corpus_resource_name`** / **`RAG_CORPUS_RESOURCE`** to the printed name (it will contain `locations/europe-west4/`). **`rag_vertex.py`** initializes Vertex in that location for retrieval only.

**Unprovisioned RAG Engine:** `scripts/ingest_rag_corpus.py` calls **`UpdateRagEngineConfig`** (Basic or Scaled, from **`TF_VAR_rag_engine_tier`**, default BASIC) before **`create_corpus`** when the regional tier is still inactive — no manual `-replace` step.

**Re-import into the same corpus** (after `gsutil` upload to `rag-sources/`):  
`python3 scripts/ingest_rag_corpus.py --project-id … --corpus-resource-name 'projects/…/ragCorpora/…' --skip-upload --files README.md`  
(or GitHub Actions **Ingest RAG corpus** — set Variables **`CORPUS_BUCKET_NAME`** and **`RAG_CORPUS_RESOURCE`**; see **`.github/workflows/ingest-rag-corpus.yml`**). No change to **`RAG_CORPUS_RESOURCE`** on Cloud Run.

3. **Wire Cloud Run** with the printed resource name:

   - Local / Terraform: `TF_VAR_rag_corpus_resource_name=projects/.../ragCorpora/...`
   - GitHub Actions: repository **Variable** `RAG_CORPUS_RESOURCE` (same string)
   - Then `terraform apply` and/or push a deploy so the revision gets the env var.

**Manual alternative:** `gsutil cp knowledge.txt Profile.pdf gs://$(terraform output -raw corpus_bucket_name)/rag-sources/` then create/import a corpus in the [Vertex RAG console](https://console.cloud.google.com/vertex-ai/studio) or via the [RAG API](https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/rag-api-v1).

If `import_files` fails with **500 Internal error** after a successful upload, run **`terraform apply`** so RAG Engine and corpus bucket IAM are present, then retry ingest.

**State move (upgrading an existing stack):** RAG Engine is now keyed by region. If state still has the old address `google_vertex_ai_rag_engine_config.main` (no `for_each`), run once before apply (replace `us-central1` with your `var.region`):

```bash
terraform state mv \
  'google_vertex_ai_rag_engine_config.main' \
  'google_vertex_ai_rag_engine_config.main["us-central1"]'
```

### New image for Cloud Run

After building and pushing to Artifact Registry:

```bash
terraform apply -var="container_image=us-central1-docker.pkg.dev/YOUR_PROJECT_ID/digital-twin/api:TAG"
```

See repository root `README.md` for broader context.
