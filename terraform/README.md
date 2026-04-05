# Terraform — digital_twin

## Minimal flow

1. **One env var** (or use gitignored `terraform.tfvars` with `project_id = "..."`):

   ```bash
   export TF_VAR_project_id="YOUR_PROJECT_ID"
   ```

2. **Apply** (creates GCP resources; GitHub deploy wiring defaults to repo `ak47/digital_twin`):

   ```bash
   terraform init
   terraform apply
   ```

3. **GitHub secrets** (once per project / after WIF changes). From repo root:

   ```bash
   ./scripts/print-github-actions-secrets.sh
   ```

   Paste the three lines into **Settings → Secrets and variables → Actions**.

4. **CI** (`.github/workflows/deploy-api.yml`) only builds and deploys the container; it does not run Terraform.

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
