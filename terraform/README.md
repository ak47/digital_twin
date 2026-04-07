# Terraform — digital_twin

**Backend:** Default is **local state** (`terraform.tfstate` in this directory). For **GCS remote state**, copy **`backend.tf.example`** → **`backend.tf`** (gitignored), edit `bucket` / `prefix`, then **`terraform init -migrate-state`** once.

## Minimal flow

1. **One env var** (or use gitignored `terraform.tfvars` with `project_id = "..."`):

   ```bash
   export TF_VAR_project_id="YOUR_PROJECT_ID"
   ```

2. **Init** (first time / new clone):

   ```bash
   cd terraform
   terraform init
   ```

   **Remote state:** see **[GCS remote state](#gcs-remote-state-dedicated-bucket)** below.

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

### Custom domain on the API (Terraform)

Set **`cloud_run_custom_domain`** (e.g. `digital-twin.no-ego.net`) in **`terraform.tfvars`**. Terraform creates **`google_cloud_run_domain_mapping`** to route that hostname to **`${name_prefix}-api`** in **`var.region`**.

**Before apply:** verify **ownership of the base domain** (e.g. `no-ego.net`) for this GCP project — [Search Console](https://search.google.com/search-console) or `gcloud domains verify`.

**After apply:** run **`terraform output cloud_run_custom_domain_dns_records`** and add every record at your DNS host. Then check **`curl -sS "https://<hostname>/health"`** returns **`{"status":"ok"}`** (not HTML).

If the mapping already exists in GCP, import it before managing with Terraform:

```text
terraform import 'google_cloud_run_domain_mapping.api[0]' locations/REGION/namespaces/PROJECT_ID/domainmappings/HOSTNAME
```

Example: `locations/us-central1/namespaces/my-proj/domainmappings/digital-twin.no-ego.net`

### GCS remote state (dedicated bucket)

Use a **separate** bucket from the RAG corpus bucket. State bucket name must be **globally unique** across GCS.

1. **Create the bucket** (pick a region; `US` multi-region is common for state):

   ```bash
   export GCP_PROJECT="YOUR_PROJECT_ID"
   export TF_STATE_BUCKET="YOUR_UNIQUE_TF_STATE_BUCKET"

   gcloud storage buckets create "gs://${TF_STATE_BUCKET}" \
     --project="${GCP_PROJECT}" \
     --location=US \
     --uniform-bucket-level-access

   gcloud storage buckets update "gs://${TF_STATE_BUCKET}" --versioning
   ```

2. **Grant Terraform’s identity** `roles/storage.objectAdmin` on that bucket only (use the account you run `terraform` with — your user or a deploy SA):

   ```bash
   export TERRAFORM_ACTOR="you@example.com"   # or service-XXXX@PROJECT.iam.gserviceaccount.com

   gcloud storage buckets add-iam-policy-binding "gs://${TF_STATE_BUCKET}" \
     --member="user:${TERRAFORM_ACTOR}" \
     --role="roles/storage.objectAdmin"
   ```

   For a **service account**, use `--member="serviceAccount:${TERRAFORM_ACTOR}"` instead.

3. **Wire Terraform** — from **`terraform/`**:

   ```bash
   cp backend.tf.example backend.tf
   # Edit backend.tf: set bucket = "${TF_STATE_BUCKET}" (and prefix if you want)
   ```

4. **Migrate existing local state** (one time per working copy that already has `terraform.tfstate`):

   ```bash
   rm -rf .terraform
   terraform init -migrate-state
   ```

   Answer **`yes`** when Terraform asks to copy state to GCS. After that, **`terraform.tfstate`** in this directory is no longer used; back up or delete it only after you confirm **`terraform state list`** works from a **fresh** `terraform init` on another machine.

5. **New clone** (no local state): same `backend.tf`, then **`terraform init`** (no `-migrate-state`).

### If `WorkloadIdentityPool` returns **409 already exists**

An old pool id may exist in GCP but not in Terraform state. This stack now uses pool id **`{name_prefix}-gha-wif`** (default `digital-twin-gha-wif`) so a fresh apply can succeed. You may delete the unused pool **`digital-twin-github`** in the GCP console (IAM → Workload Identity Federation) if it is still there.

### RAG: upload `knowledge.txt` / `Profile.pdf` and ingest

End-to-end operator flow (production updates, CI ingest): **[`docs/rag-ingestion.md`](../docs/rag-ingestion.md)**.

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

**Re-import into the same corpus** (after upload to `rag-sources/`): with **`--skip-upload`**, the script imports the **whole** `gs://<bucket>/rag-sources/` prefix; pass any **`--files`** value to satisfy the CLI (the workflow uses a placeholder). Example:  
`python3 scripts/ingest_rag_corpus.py --project-id … --corpus-resource-name 'projects/…/ragCorpora/…' --skip-upload --files .`  
Or use GitHub Actions **Ingest RAG corpus** (Variables **`CORPUS_BUCKET_NAME`**, **`RAG_CORPUS_RESOURCE`**; see **`.github/workflows/ingest-rag-corpus.yml`**). No change to **`RAG_CORPUS_RESOURCE`** on Cloud Run.

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

### Idle session digest (Cloud Run Job + Scheduler)

**`terraform/digest_job.tf`** provisions an optional **`${name_prefix}-session-digest`** Cloud Run Job and a **Cloud Scheduler** HTTP target that calls **`:run`** on that job. The job uses the same **`container_image`** as the API and runs **`python -m digital_twin.run_session_digest`**.

In **`terraform.tfvars`** (or `TF_VAR_*`):

- **`session_digest_enabled`** — `true` to create job + scheduler + IAM
- **`session_digest_gmail_secret_id`** — Secret Manager **secret id** (short name) with the Gmail SA JSON
- **`session_digest_delegated_user`** — Workspace sender (**`GMAIL_DELEGATED_USER`**)
- **`session_digest_email_to`** — comma-separated recipients (**`RESUME_BOT_DIGEST_EMAIL_TO`**)

Optional: **`session_digest_schedule`** (cron, default `*/15 * * * *`), **`session_digest_scheduler_timezone`**, **`session_digest_idle_minutes`**, **`session_digest_display_timezone`**.

After apply, run **`./scripts/print-github-actions-secrets.sh`** and set GitHub repository **Variable** **`SESSION_DIGEST_JOB_NAME`** to **`terraform output -raw session_digest_job_name`** so **`.github/workflows/deploy-api.yml`** updates the job image on every deploy.

See **[`docs/session-digest.md`](../docs/session-digest.md)** for Workspace / domain-wide delegation and broader context.
