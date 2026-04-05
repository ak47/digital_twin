# Follow-ups — widget, RAG corpus updates, Terraform remote state

Most of this is **implemented in-repo**; what’s left is **your GCP/GitHub configuration** and occasional operations.

---

## 1. Widget on About — **done in `ak47.github.io`**

**Changes shipped**

- **`no_ego/src/utils/digitalTwinApi.js`** — In **`NODE_ENV === "production"`**, if `GATSBY_DIGITAL_TWIN_API_BASE` is unset, the client defaults to **`https://digital-twin.no-ego.net`**.
- **`.github/workflows/deploy-pages.yml`** — Export defaults the same URL when the repo Variable is empty.
- **`no_ego/.env.production.example`** — Documents optional override.

**What you do**

- Push **`ak47.github.io`** `main` so GitHub Pages rebuilds.
- Optional: set Actions Variable **`GATSBY_DIGITAL_TWIN_API_BASE`** if the API URL ever changes.

The About page already mounts **`DigitalTwinChat`** (`about.js`); **`GET` / `POST` / `X-Session-Id` / SSE** were already implemented.

---

## 2. When corpus files change — **script + CI in `digital_twin`**

**Changes shipped**

- **`scripts/ingest_rag_corpus.py`** — **`--corpus-resource-name`** imports into an **existing** corpus (no new id; **no** `RAG_CORPUS_RESOURCE` rotation). Vertex location is inferred from the resource name when possible.
- **`.github/workflows/ingest-rag-corpus.yml`** — **`workflow_dispatch`**: re-import from **`gs://…/rag-sources/`** with **`--skip-upload`** (upload files with **`gsutil`** first).

**What you do**

1. Upload updated objects to the corpus bucket, e.g.  
   `gsutil cp rag-sources/* gs://YOUR_CORPUS_BUCKET/rag-sources/`
2. In **digital_twin** repo → **Actions** → **Ingest RAG corpus** → **Run workflow**.

**Repository Variables** (same repo):

| Variable | Example |
|----------|---------|
| `CORPUS_BUCKET_NAME` | `digital-twin-corpus-eef009` |
| `RAG_CORPUS_RESOURCE` | `projects/597516825296/locations/europe-west4/ragCorpora/…` |
| `RAG_INGEST_REGION` (optional) | `europe-west4` if the corpus name doesn’t contain `/locations/…/` |

**Secrets:** same as Deploy API (`GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT_EMAIL`, `GCP_PROJECT_ID`).

---

## 3. Remote Terraform state — **partial GCS backend in `digital_twin`**

**Changes shipped**

- **`terraform/versions.tf`** — **`backend "gcs" {}`** (config via **`-backend-config`**).
- **`terraform/backend.hcl.example`** — Copy to **`terraform/backend.hcl`** (gitignored).
- **`.gitignore`** — **`terraform/backend.hcl`**

**What you do**

1. Create a **versioning-enabled** GCS bucket for state (not the corpus bucket).
2. `cp terraform/backend.hcl.example terraform/backend.hcl` and set **`bucket`** (and **`prefix`** if you want).
3. From **`terraform/`**:  
   `terraform init -backend-config=backend.hcl -migrate-state`  
   (or **`init -backend-config=backend.hcl`** on a fresh clone with no local state).
4. **Local-only / no bucket yet:**  
   `terraform init -backend=false`

---

## Related docs

- **`docs/WORKING.md`** — Runbook, curl checks.
- **`terraform/README.md`** — RAG, init, secrets.
