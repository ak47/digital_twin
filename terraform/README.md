# Terraform — digital_twin

**Backend:** **`terraform/backend.tf`** commits shared GCS backend settings (`prefix`) and expects bucket injection per environment. Set **`TF_STATE_BUCKET`** and run **`terraform init -backend-config="bucket=${TF_STATE_BUCKET}"`** (see **[GCS remote state](#gcs-remote-state-dedicated-bucket)**). **`terraform init -migrate-state`** moves existing local state into that bucket when you adopt remote state.

## Minimal flow

1. **Env var and gitignored `terraform.tfvars`** — at minimum set **`project_id`** and required **`cors_allowed_origins`** (see **`terraform.tfvars.example`**). Example:

   ```bash
   export TF_VAR_project_id="YOUR_PROJECT_ID"
   ```

   **`cors_allowed_origins`** has **no default** in **`variables.tf`** so you never apply with accidental example origins. When **`gha_terraform_state_bucket`** is set, keep it equal to your backend bucket (**`TF_STATE_BUCKET`**) so CI IAM and backend init point at the same state.

2. **Init** (first time / new clone):

   ```bash
   cd terraform
   export TF_STATE_BUCKET="YOUR_UNIQUE_TF_STATE_BUCKET"
   terraform init -backend-config="bucket=${TF_STATE_BUCKET}"
   ```

   **Remote state:** see **[GCS remote state](#gcs-remote-state-dedicated-bucket)** below.

3. **Apply** (creates GCP resources). Set **`github_repository`** in **`terraform.tfvars`** to **`owner/name`** when you want GitHub Actions OIDC (WIF); leave default **`""`** to skip the deployer SA until you are ready.

   ```bash
   terraform apply
   ```

4. **GitHub secrets** (once per project / after WIF changes). From repo root:

   ```bash
   ./scripts/print-github-actions-secrets.sh
   ```

   Paste into **Settings → Secrets and variables → Actions** (see script output and [`docs/github-actions-terraform-config.md`](../docs/github-actions-terraform-config.md)).

5. **CI** — `deploy-api.yml` builds and deploys the container; `ingest-rag-corpus.yml` re-imports from GCS; `terraform.yml` can **plan** (every PR / push to `main` touching `terraform/**`) and **apply** (manual dispatch only). See **[GitHub Actions Terraform](#github-actions-terraform)** below.

### 409: resource already exists

If Terraform tries to **create** something that is already in GCP (e.g. after **migrating state** to a new bucket, or a partial apply), **import** the live object into state instead of creating it. Use **`terraform import`** with the resource address and the provider’s expected id (see the Terraform Google provider docs for each resource type).

Then **`terraform plan`** in **`terraform/`**. If **`google_cloud_run_domain_mapping`** returns **409** (custom domain already mapped), import:

```bash
cd terraform
terraform import 'google_cloud_run_domain_mapping.api[0]' \
  "locations/${REGION}/namespaces/YOUR_PROJECT_ID/domainmappings/YOUR_HOSTNAME"
```

(Hostname is your **`cloud_run_custom_domain`**, e.g. **`api.example.com`**; **`REGION`** is **`var.region`**, default **`us-central1`**.) Repeat for any other **409** with the matching **`terraform import`** id from the provider docs.

### GitHub Actions Terraform

Run infrastructure from GitHub — **no monolithic `TERRAFORM_TFVARS` secret**. Each setting is its own repository **Variable** or **Secret** (auditable, visible names).

**Full reference:** [`docs/github-actions-terraform-config.md`](../docs/github-actions-terraform-config.md)

**Required Variables:** `CORS_ALLOWED_ORIGINS`, `TF_STATE_BUCKET`, `TF_GITHUB_REPOSITORY`  
**Required Secrets:** `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT_EMAIL` (same as Deploy API)

**Workflow:** [`.github/workflows/terraform.yml`](../.github/workflows/terraform.yml) runs `scripts/gha-export-terraform-vars.sh` (prints a **config summary** in the log), then `plan` / `apply`. On PR / push to `terraform/**` it plans; **apply** on push to `main` or manual dispatch with **apply** checked.

**IAM:** set `TF_GITHUB_ACTIONS_TERRAFORM_ROLES` and `TF_STATE_BUCKET` (same as `gha_terraform_state_bucket`) before the first GHA apply.

Local `terraform/terraform.tfvars` remains for optional laptop use only; CI ignores it.

### Custom domain on the API (Terraform)

Set **`cloud_run_custom_domain`** (e.g. `api.example.com`) in **`terraform.tfvars`**. Terraform creates **`google_cloud_run_domain_mapping`** to route that hostname to **`${name_prefix}-api`** in **`var.region`**.

**Before apply:** verify **ownership of the base domain** (e.g. `example.com`) for this GCP project — [Search Console](https://search.google.com/search-console) or `gcloud domains verify`.

**After apply:** run **`terraform output cloud_run_custom_domain_dns_records`** and add every record at your DNS host. Then check **`curl -sS "https://<hostname>/health"`** returns **`{"status":"ok"}`** (not HTML).

If the mapping already exists in GCP, import it before managing with Terraform:

```text
terraform import 'google_cloud_run_domain_mapping.api[0]' locations/REGION/namespaces/PROJECT_ID/domainmappings/HOSTNAME
```

Example: `locations/us-central1/namespaces/my-proj/domainmappings/api.example.com`

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

3. **Wire Terraform** — keep **`terraform/backend.tf`** unchanged and pass bucket at init time:

   ```bash
   export TF_STATE_BUCKET="YOUR_UNIQUE_TF_STATE_BUCKET"
   terraform init -reconfigure -backend-config="bucket=${TF_STATE_BUCKET}"
   ```

4. **Migrate existing local state** (one time per working copy that already has `terraform.tfstate`):

   ```bash
   rm -rf .terraform
   terraform init -migrate-state -backend-config="bucket=${TF_STATE_BUCKET}"
   ```

   Answer **`yes`** when Terraform asks to copy state to GCS. After that, **`terraform.tfstate`** in this directory is no longer used; back up or delete it only after you confirm **`terraform state list`** works from a **fresh** `terraform init` on another machine.

5. **New clone** (no local state): **`terraform init -backend-config="bucket=${TF_STATE_BUCKET}"`** (no `-migrate-state`).

### Renaming the state bucket (e.g. typo fix)

GCS **cannot** rename a bucket. To move state from **`digital-twien-terraform-state`** (or any old name) to **`digital-twin-terraform-state`**:

1. **Create** the new bucket (versioning + uniform access) in the same GCP project — same **`gcloud storage buckets create`** / **`update --versioning`** steps as in [GCS remote state](#gcs-remote-state-dedicated-bucket), with the **new** name. If **`digital-twin-terraform-state`** is already taken globally, pick another unique name and use it for both **`TF_STATE_BUCKET`** and **`gha_terraform_state_bucket`**.
2. **Grant** identities that will run **`terraform init -migrate-state`** **`roles/storage.objectAdmin`** on the **new** bucket (your user or bootstrap SA). The GitHub deploy SA already has **`objectAdmin`** on the **old** bucket from Terraform; add the same on the **new** bucket (temporary **`gcloud storage buckets add-iam-policy-binding`** is fine) so CI can use the new backend after you switch.
3. Update **`TF_STATE_BUCKET`** (GitHub repository Variable and local env) and **`gha_terraform_state_bucket`** in **`terraform.tfvars`** to the new name; re-run **`./scripts/gha-migrate-tfvars-to-variables.sh`** if you sync tfvars → GitHub Variables.
4. From a machine with **read** access to the **old** state and **write** access to the **new** bucket: **`cd terraform`**, **`rm -rf .terraform`**, **`terraform init -migrate-state -backend-config="bucket=${TF_STATE_BUCKET}"`**, confirm copying state into the new backend when prompted. Then **`terraform plan`** — expect at most IAM updates for the state-bucket binding until you **apply**.
5. **Apply** (GitHub Actions **Terraform** workflow with **apply**, or local) so **`google_storage_bucket_iam_member.github_deploy_terraform_state_access`** attaches to the **new** bucket.
6. When satisfied, empty and delete the **old** bucket.

### If `WorkloadIdentityPool` returns **409 already exists**

An old pool id may exist in GCP but not in Terraform state. This stack now uses pool id **`{name_prefix}-gha-wif`** (default `digital-twin-gha-wif`) so a fresh apply can succeed. You may delete the unused pool **`digital-twin-github`** in the GCP console (IAM → Workload Identity Federation) if it is still there.

### RAG: upload `knowledge.txt` / `Profile.pdf` and ingest

End-to-end operator flow (production updates, CI ingest): **[`docs/rag-ingestion.md`](../docs/rag-ingestion.md)**.

Terraform creates the **corpus GCS bucket**, provisions the **Vertex AI service identity** for `aiplatform.googleapis.com`, then grants that principal **`storage.objectViewer`** on the corpus bucket. Unless **`rag_engine_deployment_mode = "SERVERLESS"`**, it also creates **`google_vertex_ai_rag_engine_config`** in **`var.region`** (and in **`rag_corpus_ingest_region`** when set) with **SPANNER_BASIC** or **SPANNER_SCALED**. Optional **`rag_corpus_ingest_region`** adds a second RAG Engine region for non-default ingest layouts (**must be empty when SERVERLESS**). You still **upload files** and **create a RAG corpus + import** (Vertex does not auto-read the bucket).

1. **Bucket name** (after `terraform apply`):

   ```bash
   terraform output -raw corpus_bucket_name
   ```

2. **One-shot (upload + create corpus + import)** from the **repo root**, with local files (paths are examples):

   ```bash
   uv sync
   gcloud auth application-default login
   export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"   # or --project-id

   uv run python scripts/ingest_rag_corpus.py \
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

**Inactive RAG Engine:** `scripts/ingest_rag_corpus.py` calls **`UpdateRagEngineConfig`** before **`create_corpus`** when needed: **Spanner** Basic/Scaled from **`TF_VAR_rag_engine_deployment_mode`** (**SPANNER_BASIC** default, **SPANNER_SCALED**) or **Serverless** from **`TF_VAR_rag_engine_deployment_mode=SERVERLESS`**. Legacy: **`TF_VAR_rag_engine_tier`** (BASIC/SCALED) still maps to **SPANNER_*** for local one-offs.

#### Serverless RAG (preview, `us-central1`)

- Set **`rag_engine_deployment_mode = "SERVERLESS"`** and **`rag_corpus_ingest_region = ""`**. Terraform **omits** `google_vertex_ai_rag_engine_config` (the HashiCorp **google** provider does not expose Serverless on that resource as of v7.27).
- **Migrate from Spanner** (e.g. corpus in `europe-west4`): (1) Switch **`us-central1`** to Serverless in the [Vertex console](https://console.cloud.google.com/vertex-ai/rag/corpus) or run **`ingest_rag_corpus.py`** with **`TF_VAR_rag_engine_deployment_mode=SERVERLESS`** before creating a **new** corpus; (2) **`terraform apply`** to drop extra regional configs if you clear **`rag_corpus_ingest_region`**; (3) **Re-ingest** `rag-sources/` into a new **`locations/us-central1/...`** corpus and set **`rag_corpus_resource_name`**. Corpora are **not** shared between Spanner and Serverless [deployment modes](https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/deployment-modes).
- If **`terraform plan`** shows **destroy** of `google_vertex_ai_rag_engine_config` when switching to SERVERLESS, review impact. To **stop Terraform from deleting** a live config you still need in GCP, **`terraform state rm`** those instances first, then apply — see [Terraform state](https://developer.hashicorp.com/terraform/cli/commands/state/rm) and Google’s [switching modes](https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/switching-modes) docs.

**Re-import into the same corpus** (after upload to `rag-sources/`): with **`--skip-upload`**, the script imports the **whole** `gs://<bucket>/rag-sources/` prefix; pass any **`--files`** value to satisfy the CLI (the workflow uses a placeholder). Example:  
`uv run python scripts/ingest_rag_corpus.py --project-id … --corpus-resource-name 'projects/…/ragCorpora/…' --skip-upload --files .`  
Or use GitHub Actions **Ingest RAG corpus** (see **`.github/workflows/ingest-rag-corpus.yml`**): it runs **`terraform init`** / **`terraform output`** for **`corpus_bucket_name`** and **`rag_corpus_resource_name`** so bucket + corpus stay aligned with **`terraform.tfvars`** / Cloud Run — set both **`gha_terraform_state_bucket`** and repository Variable **`TF_STATE_BUCKET`** to the same bucket, then **`terraform apply`** so the deploy SA can read state (**`github_deploy_terraform_state_viewer`**). Repository **Secrets** **`GCP_PROJECT_ID`**, **`GCP_SERVICE_ACCOUNT_EMAIL`**, and **`GCP_WORKLOAD_IDENTITY_PROVIDER`** must refer to the **same** project as the corpus (use **`terraform output -raw github_actions_deployer_email`** and **`project_id_for_github`**). Terraform also grants **`roles/aiplatform.user`** and corpus-bucket **`roles/storage.objectViewer`** (**`github_deploy_vertex_user`**, **`corpus_github_deploy_object_viewer`**). If **`aiplatform.ragFiles.import` denied**, fix secrets or IAM on the token’s SA.

3. **Wire Cloud Run** with the printed resource name:

   - Local / Terraform: `TF_VAR_rag_corpus_resource_name=projects/.../ragCorpora/...`
   - Then `terraform apply` (sets **`RAG_CORPUS_RESOURCE`** on the service; **Deploy API** does not override it).

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

**`terraform/digest_job.tf`** provisions an optional **`${name_prefix}-session-digest`** Cloud Run Job and a **Cloud Scheduler** HTTP target that calls **`:run`** on that job. The job uses the same **`container_image`** as the API and runs **`uv run python -m digital_twin.run_session_digest`**.

In **`terraform.tfvars`** (or `TF_VAR_*`):

- **`session_digest_enabled`** — `true` to create job + scheduler + IAM
- **`session_digest_gmail_secret_id`** — Secret Manager **secret id** (short name) with the Gmail SA JSON
- **`session_digest_delegated_user`** — Workspace sender (**`GMAIL_DELEGATED_USER`**)
- **`session_digest_email_to`** — comma-separated recipients (**`RESUME_BOT_DIGEST_EMAIL_TO`**)

Optional: **`session_digest_schedule`** (cron, default `*/15 * * * *`), **`session_digest_scheduler_timezone`**, **`session_digest_idle_minutes`**, **`session_digest_display_timezone`**.

After apply, run **`./scripts/print-github-actions-secrets.sh`** and set GitHub repository **Variable** **`SESSION_DIGEST_JOB_NAME`** to **`terraform output -raw session_digest_job_name`** so **`.github/workflows/deploy-api.yml`** updates the job image on every deploy.

See **[`docs/session-digest.md`](../docs/session-digest.md)** for Workspace / domain-wide delegation and broader context.

### Cloud SQL conversation database (feature 001)

**Infrastructure is applied only via the [Terraform](../../.github/workflows/terraform.yml) GitHub Actions workflow** — not local `terraform apply`. Configure **individual repository Variables** (see [`docs/github-actions-terraform-config.md`](../docs/github-actions-terraform-config.md)); set **`TF_ENABLE_CONVERSATION_DB=true`**.

**GHA-only bootstrap:**

1. Ensure GCP WIF secrets, **`TF_STATE_BUCKET`**, **`TF_GITHUB_REPOSITORY`**, and other **`TF_*`** Variables are set (see config doc).
2. Set **`TF_ENABLE_CONVERSATION_DB=true`** (repository Variable).
3. Run **Actions → Terraform** (auto on push `terraform/**` to `main`, or workflow_dispatch + apply).
4. Terraform creates Cloud SQL, DB user, password secret, and **`DATABASE_URL`** secret (managed automatically when secret id vars are empty).
5. **Deploy API** reads **`cloud_sql_connection_name`** and **`conversation_database_url_secret_id`** from **remote Terraform state** and runs Alembic migrations before updating Cloud Run — **no manual GitHub Variables** for the database.

**Two workflows:**

| Workflow | When | What |
|----------|------|------|
| **Terraform** | Push `terraform/**` to `main` (or dispatch + apply) | Creates/updates Cloud SQL, secrets, Cloud Run env |
| **Deploy API** | Push `src/**`, `alembic/**`, etc. to `main` | Tests → reads TF state → Alembic migrate → deploy image |

After the first Terraform apply with conversation DB enabled, check the workflow log **Post-apply outputs** for `cloud_sql_connection_name` (optional sanity check).

**Schema migrations** (Alembic): automatic in Deploy API when conversation DB exists in state. Local dev only: `uv run alembic upgrade head` with `DATABASE_URL` set.
