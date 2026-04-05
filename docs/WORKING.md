# Digital twin — day-to-day commands

How to read this file:

- Blocks wrapped in **`==== … ====`** are **section headers** so you can scan quickly.
- The **first** big block under **“CURRENT RUNBOOK”** is the **up-to-date, end-to-end** path (rebuild **linux/amd64** image → push → Terraform). Prefer that when you are unsure.
- After deploy + custom domain, use **REFERENCE — Post-launch checklist** as an ordered verification list.
- Everything **below** the second `====` divider is **reference** material (one-off setup, CI, WIF, extra commands).

**While custom DNS propagates:** keep using the **`cloud_run_uri`** from `terraform output` (the `*.run.app` URL). The API and widget do not depend on `digital-twin.no-ego.net` until you point the front-end config at it.

================================================================================
## CURRENT RUNBOOK — Rebuild API image (linux/amd64) + Terraform → Cloud Run
================================================================================

Run from the **repository root** (`digital_twin/`). Set `PROJECT_ID` to your GCP project (example: `gen-lang-client-0457840462`).

### A. One-time per machine: Artifact Registry Docker auth

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev --quiet
```

### B. Ensure Buildx exists (no-op if already there)

```bash
docker buildx create --use 2>/dev/null || true
```

### C. Build for **amd64**, push, apply Terraform with the new image

`TAG` can be `v1`, `v2`, or `$(git rev-parse --short HEAD)`.

**Option 1 — build, load locally, then push** (handy if you want the image in local Docker too):

```bash
cd /path/to/digital_twin

export PROJECT_ID="YOUR_GCP_PROJECT_ID"
export REGION="us-central1"
export REPO="digital-twin"
export TAG="v1"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:${TAG}"

docker buildx build --platform linux/amd64 --load -t "${IMAGE}" .
docker push "${IMAGE}"

cd terraform
export TF_VAR_project_id="${PROJECT_ID}"
terraform apply -var="container_image=${IMAGE}"
```

**Option 2 — build and push in one step** (no local load):

```bash
cd /path/to/digital_twin

export PROJECT_ID="YOUR_GCP_PROJECT_ID"
export REGION="us-central1"
export REPO="digital-twin"
export TAG="v1"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:${TAG}"

docker buildx build --platform linux/amd64 --push -t "${IMAGE}" .

cd terraform
export TF_VAR_project_id="${PROJECT_ID}"
terraform apply -var="container_image=${IMAGE}"
```

### D. Smoke test

```bash
BASE="$(cd terraform && terraform output -raw cloud_run_uri)"
curl -sS "${BASE}/health"
curl -sS -N -X POST "${BASE}/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"hello"}'
```

**Why `--platform linux/amd64`:** Cloud Run runs **amd64**. Builds on **Apple Silicon** default to **arm64** → container exits → *“failed to start and listen on PORT=8080”*.

================================================================================
## REFERENCE — Prerequisites
================================================================================

- **GCP:** `gcloud` installed and logged in (`gcloud auth login`, `gcloud auth application-default login` if using Terraform locally).
- **Docker:** Desktop or Colima, etc.
- **Terraform:** ≥ 1.5 (for infra changes only).
- **Project ID:** Never commit it. Use shell env or gitignored `terraform/terraform.tfvars`.

================================================================================
## REFERENCE — Build / push (same as runbook, more detail)
================================================================================

From the **repository root** (`digital_twin/`):

**CPU architecture:** Cloud Run executes **`linux/amd64`**. Always build for amd64 when pushing from a Mac.

```bash
docker buildx create --use 2>/dev/null || true
```

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
export REPO="digital-twin"
export TAG="v1"   # or $(git rev-parse --short HEAD)

export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:${TAG}"

docker buildx build --platform linux/amd64 --push -t "${IMAGE}" .
```

If you prefer classic `docker build` (still set platform):

```bash
docker build --platform linux/amd64 -t "${IMAGE}" .
docker push "${IMAGE}"
```

================================================================================
## REFERENCE — Point Cloud Run at the new image (Terraform only)
================================================================================

From `terraform/` (after `IMAGE` is set and pushed):

```bash
export TF_VAR_project_id="${PROJECT_ID}"

terraform apply -var="container_image=${IMAGE}"
```

Service URL:

```bash
terraform output -raw cloud_run_uri
```

================================================================================
## REFERENCE — Custom domain → Cloud Run (`digital-twin.no-ego.net` example)
================================================================================

Map a hostname you control (e.g. **`digital-twin.no-ego.net`**) to the Cloud Run service **`digital-twin-api`** in **`us-central1`**.

**Subdomain name:** DNS hostnames almost always use **letters, digits, and hyphens**. Prefer **`digital-twin.no-ego.net`** (hyphen). A name like **`digital_twin.no-ego.net`** (underscore) is often **rejected** by registrars or TLS tooling—if you hit errors, switch to the hyphen form and use that everywhere (DNS, `gcloud`, widget config).

**Scope:** Cloud Run **domain mapping** is supported in **`us-central1`** (among other regions). Google also documents a **global external Application Load Balancer** as the long-term “recommended” custom-domain pattern; this section is the **direct domain mapping** path. Overview: [Mapping custom domains](https://cloud.google.com/run/docs/mapping-custom-domains).

### 1) Verify ownership of the **base** domain (`no-ego.net`)

For a hostname like `digital-twin.no-ego.net`, Google requires verification of **`no-ego.net`** (the registrable domain), unless the domain was bought through Google Domains / integrated flows.

Check what is already verified for your Google user / project:

```bash
gcloud domains list-user-verified
```

If **`no-ego.net`** is **not** listed, start verification (opens Search Console in the browser):

```bash
gcloud domains verify no-ego.net
```

Complete the steps in [Search Console domain verification](https://support.google.com/webmasters/answer/9008080). You need permission to change DNS at whoever hosts **`no-ego.net`** (registrar, Cloud DNS, Cloudflare, etc.).

### 2) Create the domain mapping (Console)

1. Open **[Cloud Run → Domain mappings](https://console.cloud.google.com/run/domains)** (pick project **`gen-lang-client-0457840462`** or yours).
2. **Add mapping** → choose **Cloud Run domain mappings**.
3. Select service **`digital-twin-api`**, region **`us-central1`**.
4. Enter the full hostname (e.g. **`digital-twin.no-ego.net`**), finish any verification prompts.
5. After creation, use **⋮ → DNS records** on that mapping and copy every record Cloud Run shows.

### 3) Create the domain mapping (`gcloud`)

Set variables, then create (command is **`beta`** in Google’s doc; newer `gcloud` may accept the same flags without `beta`):

```bash
export PROJECT_ID="YOUR_GCP_PROJECT_ID"
export REGION="us-central1"
export SERVICE="digital-twin-api"
export CUSTOM_DOMAIN="digital-twin.no-ego.net"

gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"

gcloud beta run domain-mappings create \
  --service="${SERVICE}" \
  --domain="${CUSTOM_DOMAIN}"
```

If `gcloud` reports that **`--region`** is required, add:

```bash
gcloud beta run domain-mappings create \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --service="${SERVICE}" \
  --domain="${CUSTOM_DOMAIN}"
```

### 4) Fetch the DNS records you must add at your DNS host

```bash
gcloud beta run domain-mappings describe \
  --domain="${CUSTOM_DOMAIN}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}"
```

In the output, find **`resourceRecords`** (usually **`A`**, **`AAAA`**, and/or **`CNAME`**). Add **every** record at the DNS provider for **`no-ego.net`**:

- **Name / host:** often the subdomain part only (e.g. `digital-twin`) or as your provider documents (`digital-twin.no-ego.net.` vs relative).
- **Type / value:** must match Cloud Run exactly.

If you use **[Cloud DNS](https://cloud.google.com/dns/docs/records#adding_a_record)**, create a **public** zone for `no-ego.net` (or use the existing zone) and add the records there; point the registrar’s **NS** to Cloud DNS if it is not already.

#### Gandi.net (DNS for `no-ego.net`)

1. Sign in at [Gandi](https://www.gandi.net/) → **Domains** → **no-ego.net** → open **DNS records** (wording may be **DNS / Zone file** depending on product).
2. For each row in Cloud Run’s **`resourceRecords`** (from `gcloud … describe` or Console **DNS records**):
   - **Name / hostname:** use the **subdomain only** when Gandi expects a relative name (e.g. `digital-twin` for `digital-twin.no-ego.net`). If the UI asks for the full name, use `digital-twin.no-ego.net` as Gandi documents for that screen.
   - **Type:** `A`, `AAAA`, or `CNAME` exactly as Google shows.
   - **Value / target:** paste **exactly** what Google gives. For a **CNAME** to Google hosting, the target must end up as **`ghs.googlehosted.com.`** (fully qualified). If Gandi **appends your domain** to whatever you type (the `ghs.googlehosted.com.no-ego.net` bug), use a **trailing dot** on the target (`ghs.googlehosted.com.`) or Gandi’s option for an **absolute / external** hostname if available.
3. Save the zone. Optionally lower **TTL** (e.g. 300 seconds) while testing; raise it again after things are stable.
4. Wait for propagation, then re-check with `dig +short digital-twin.no-ego.net` and `curl` to `https://digital-twin.no-ego.net/health`.

Gandi’s UI changes over time; if a record type or field is unclear, use their docs for **adding a DNS record** on your plan (Standard DNS vs LiveDNS).

#### Troubleshooting: `dig` shows `ghs.googlehosted.com.no-ego.net` (wrong)

That usually means the **CNAME target** was saved **without** a trailing dot, so your DNS provider treated it as **relative** to your zone and appended `.no-ego.net`.

- **Wrong (relative):** target `ghs.googlehosted.com` → resolves as `ghs.googlehosted.com.no-ego.net` (broken).
- **Right (absolute / FQDN):** target **`ghs.googlehosted.com.`** (note the **trailing dot**) so it points at Google’s real hostname.

Some UIs have a checkbox like “FQDN” or “absolute name”—use that, or paste the **exact** `rrdatas` values from:

```bash
gcloud beta run domain-mappings describe \
  --domain="${CUSTOM_DOMAIN}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="yaml(status.resourceRecords)"
```

After fixing, `dig +short digital-twin.no-ego.net` should show **`ghs.googlehosted.com.`** (possibly after a short TTL wait), not `ghs.googlehosted.com.no-ego.net`.

### 5) Wait for DNS + managed certificate

- Propagation: minutes to hours (TTL at the old DNS matters).
- Google provisions **managed TLS** for the mapping; HTTPS may take a few more minutes after DNS is correct.

Test:

```bash
dig +short "digital-twin.no-ego.net"
curl -sS -o /dev/null -w "%{http_code}\n" "https://digital-twin.no-ego.net/health"
```

### 6) Optional: remove a mapping

```bash
gcloud beta run domain-mappings delete \
  --domain="${CUSTOM_DOMAIN}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}"
```

### 7) Widget / CORS note

The **browser `Origin`** for your site stays **`https://no-ego.net`** or **`https://www.no-ego.net`**; the **API URL** becomes **`https://digital-twin.no-ego.net`**. You normally **do not** add the API hostname to **`cors_allowed_origins`**—only the **page** origins. If you later load the widget from another site, add that origin in Terraform and re-apply.

---

**Terraform:** You *can* manage mappings with [`google_cloud_run_domain_mapping`](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_run_domain_mapping) after the domain is verified; many teams keep the **first** mapping manual, then codify it once stable.

================================================================================
## REFERENCE — CORS / session header (widget preview)
================================================================================

```bash
BASE="$(cd terraform && terraform output -raw cloud_run_uri)"

curl -sS -D - -o /dev/null -X OPTIONS "${BASE}/api/chat" \
  -H "Origin: https://www.no-ego.net" \
  -H "Access-Control-Request-Method: POST"
```

Expect `access-control-allow-origin` matching the request origin when it is allowlisted.

================================================================================
## REFERENCE — GitHub Actions (automated deploy)
================================================================================

Yes — **this can be automated**. The workflow **`.github/workflows/deploy-api.yml`**:

1. Builds the Docker image on each push to `main` that touches the API (or on **Run workflow** manually).
2. Pushes to Artifact Registry as  
   `us-central1-docker.pkg.dev/<PROJECT>/<REPO>/api:<git-sha>`.
3. Updates the **existing** Cloud Run service **`digital-twin-api`** with `gcloud run services update`.

You must configure the repo (or org) with **Workload Identity Federation** so GitHub can authenticate to GCP without a long‑lived JSON key. Set:

| Name | Type | Purpose |
|------|------|---------|
| `GCP_PROJECT_ID` | **Repository secret** | Target project ID (`google-github-actions/auth` and deploy steps read `secrets.*` only) |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | **Repository secret** | Full WIF provider resource name |
| `GCP_SERVICE_ACCOUNT_EMAIL` | **Repository secret** | Deployer service account email |

If you put the project ID under **Variables** instead of **Secrets**, the workflow will see an empty value and **`auth@v2` fails** with *“must specify exactly one of workload_identity_provider or credentials_json”*. Use **Secrets** for all three, or change the workflow to use `vars.GCP_PROJECT_ID` for the project id only.

### Workload Identity: “attribute condition must reference one of the provider's claims”

That error means the **attribute condition** CEL expression references something that is **not** a claim on GitHub’s OIDC token, or uses the wrong name/syntax.

**Do this:**

1. **Attribute mapping** (minimum for GitHub):

   ```text
   google.subject=assertion.sub
   ```

   If you will filter by repo or owner in the condition, also map (comma-separated in `gcloud`, or one per row in console):

   ```text
   attribute.repository=assertion.repository
   attribute.repository_owner=assertion.repository_owner
   ```

2. **Attribute condition** — use **`assertion.<claim>`** and GitHub’s real claim names. Examples (note **single quotes** around string literals in CEL):

   - Restrict to your **GitHub org or user** (value is the `repository_owner` string, e.g. `ak47`):

     ```text
     assertion.repository_owner=='ak47'
     ```

   - Restrict to **one repo** (`owner/name`):

     ```text
     assertion.repository=='ak47/digital_twin'
     ```

   - Org + **main** only:

     ```text
     assertion.repository_owner=='ak47' && assertion.ref=='refs/heads/main'
     ```

   Claim names must match [GitHub’s OIDC token](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect#understanding-the-oidc-token) (e.g. `repository`, `repository_owner`, `ref`, `sub`). Do **not** invent field names.

3. **Easiest unblock:** leave **Attribute condition empty** when creating the provider (if the console allows), finish pool + provider + SA impersonation, then add a **tighter condition** later under **Edit provider** once things work.

4. **Personal repos:** there is no GitHub “organization” — use your **username** as `repository_owner` (e.g. `assertion.repository_owner=='yourusername'`).

Official reference: [Workload Identity Federation — attribute conditions](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines#conditions).

---

The deployer service account needs at least:

- **Artifact Registry:** `roles/artifactregistry.writer` on repo `digital-twin` (or project-level writer). Registry IDs cannot contain underscores.
- **Cloud Run:** `roles/run.admin` (or narrower if you tighten later)
- **IAM:** `roles/iam.serviceAccountUser` on **`digital-twin-api@<PROJECT>.iam.gserviceaccount.com`** (runtime SA) if required by your org policy

The workflow pins **`REGION: us-central1`**; edit `.github/workflows/deploy-api.yml` if your Terraform region differs.

### Terraform vs CI

- CI updates **live** Cloud Run with `gcloud`; it does **not** run Terraform (avoids putting Terraform state and full project credentials in GitHub unless you add a separate **infra** workflow with a **GCS backend**).
- After a CI deploy, keep local Terraform state honest with either:
  - **`terraform apply -var="container_image=<same-image-as-CI>"`**, or  
  - **`terraform refresh`** (pulls current Cloud Run image into state), then verify with **`terraform plan`**.

For **full** “everything through Terraform from CI,” add a second workflow later: remote state bucket + `terraform init -backend-config=...` + `terraform apply` with the same WIF (and broader IAM).

================================================================================
## REFERENCE — Infra-only changes (Terraform)
================================================================================

```bash
cd terraform
export TF_VAR_project_id="${PROJECT_ID}"
terraform plan
terraform apply
```

================================================================================
## REFERENCE — Useful Terraform outputs
================================================================================

```bash
cd terraform
terraform output
```

- `corpus_bucket_name` — upload RAG source files here (`gsutil rsync`, CI, etc.).
- `sessions_bucket_name` — app will store session JSON here.
- `artifact_registry_repository` — Docker push target prefix.
- `cloud_run_uri` — current service URL.

================================================================================
## REFERENCE — Post-launch checklist (work through in order)
================================================================================

Use your real **`PROJECT_ID`** (e.g. `digital-twin-492318`), **`REGION`** (`us-central1`), and **`CUSTOM_DOMAIN`** if you use one (e.g. `digital-twin.no-ego.net`). Treat the checkboxes as your own tracker (copy the section into an issue or tick mentally).

```bash
export PROJECT_ID="YOUR_GCP_PROJECT_ID"
export REGION="us-central1"
export CUSTOM_DOMAIN="digital-twin.no-ego.net"   # or skip sections that need it
```

### 1) CI deployed the service you expect

- [ ] GitHub Actions **Deploy API** workflow is green on `main`.
- [ ] Cloud Run revision and image look right:

```bash
gcloud run services describe digital-twin-api \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="yaml(status.latestReadyRevisionName,spec.template.spec.containers[0].image)"
```

### 2) Custom domain mapping is ready (skip if you only use `*.run.app`)

- [ ] Mapping exists and managed cert is active:

```bash
gcloud beta run domain-mappings describe \
  --domain="${CUSTOM_DOMAIN}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="yaml(status.conditions)"
```

- [ ] **`Ready`** and **`CertificateProvisioned`** are **`True`**.

### 3) DNS points at Google

- [ ] Registrar / DNS host has the **CNAME** (or records) Cloud Run showed when you created the mapping — usually **`digital-twin` → `ghs.googlehosted.com.`** (FQDN with trailing dot where the UI allows it).

```bash
dig +short "${CUSTOM_DOMAIN}" CNAME
dig +short "${CUSTOM_DOMAIN}"
```

### 4) HTTPS and `/health`

Set **`API_BASE`** to your public API URL (custom domain **or** `cloud_run_uri` from `terraform output -raw cloud_run_uri`).

```bash
export API_BASE="https://digital-twin.no-ego.net"
```

- [ ] **GET** returns **200**:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" "${API_BASE}/health"
curl -sS "${API_BASE}/health"
```

- [ ] **HEAD** returns **200** (requires a deploy that includes **`HEAD /health`** in the app):

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -I "${API_BASE}/health"
```

### 5) Core API paths

- [ ] **`${API_BASE}/docs`** loads in a browser (or you have intentionally disabled public docs).
- [ ] **Chat** responds (streaming):

```bash
curl -sS -N -X POST "${API_BASE}/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"hello"}'
```

### 6) CORS matches the real browser origin

The allowlist is **`cors_allowed_origins`** in Terraform (typically **`https://no-ego.net`** and **`https://www.no-ego.net`**). The **API hostname** is not an “origin” for CORS — the **page** URL is.

- [ ] Run the **OPTIONS** probe in **REFERENCE — CORS / session header** and confirm `access-control-allow-origin` for your site.
- [ ] From the real widget or site, **POST `/api/chat`** succeeds with no CORS errors in devtools.

### 7) Wire the front-end

- [ ] Widget / site config uses **`API_BASE`** for API calls.
- [ ] If you use **`X-Session-Id`**, confirm session create and reuse in the UI.

### 8) Runtime env and IAM (GCP console or `gcloud run services describe`)

- [ ] **`GCP_PROJECT_ID`** / **`GCP_REGION`** match the project and region where Vertex is used.
- [ ] Cloud Run **runtime** service account can call Vertex / Gemini (**`roles/aiplatform.user`** or equivalent for your setup).
- [ ] **`GCS_SESSIONS_BUCKET`** (if set): SA can read/write that bucket.
- [ ] **Corpus / RAG:** bucket populated and any ingest documented in your process.

### 9) Terraform vs live image (after CI deploys)

- [ ] From `terraform/`:

```bash
cd terraform
export TF_VAR_project_id="${PROJECT_ID}"
terraform refresh
terraform plan
```

- [ ] No unwanted drift; if only the image changed in CI, either **`apply -var="container_image=..."`** to match or treat CI as source of truth (see **Terraform vs CI** under GitHub Actions).

### 10) Optional next steps

- [ ] Lock down or remove **`/docs`** in production if you want a smaller attack surface.
- [ ] Uptime check on **`GET /health`**.
- [ ] Log/metric alerts for 5xx on Cloud Run.
- [ ] Manage **domain mapping** in Terraform (`google_cloud_run_domain_mapping`) once manual setup is stable.

================================================================================
## REFERENCE — Troubleshooting
================================================================================

- **`invalid_rapt` / OAuth errors:** See root **README.md** → *Troubleshooting: invalid_rapt*.
- **Cloud Run 403 on push:** Confirm `gcloud auth configure-docker us-central1-docker.pkg.dev`.
- **Terraform wants to change the image after CI:** Refresh or re-apply with the image tag CI used (see *Terraform vs CI* above).
- **Cloud Run: “failed to start and listen on PORT=8080”** after a **local** `docker build` on **Mac (M1/M2/M3):** use the **CURRENT RUNBOOK** (`--platform linux/amd64`). **GitHub Actions** `ubuntu-latest` is already amd64. Check revision logs in Cloud Console if it still fails (import errors, etc.).
- **`Vertex not configured: set GCP_PROJECT_ID` from `/api/chat`:** The Cloud Run revision has no **`GCP_PROJECT_ID`** (common if the service was created outside Terraform and CI only updates the image). **Fix now:**  
  `gcloud run services update digital-twin-api --region=us-central1 --project=YOUR_PROJECT --update-env-vars="GCP_PROJECT_ID=YOUR_PROJECT,GCP_REGION=us-central1"`  
  Or push **`main`** so the **Deploy API** workflow runs (it now sets those env vars on every deploy). The app also resolves the project from **metadata** on Cloud Run when **`K_SERVICE`** is set, after you deploy a build that includes the `llm.py` change.
- **Chat returns `Publisher Model … gemini-…` NOT_FOUND:** Your project may not expose that exact model id yet. Set **`GEMINI_MODEL`** to a current id (default in app/Terraform is **`gemini-2.5-flash`**). In Terraform use **`-var="gemini_model=gemini-2.5-flash"`** (or another id from [Model versions](https://cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions)), then **`terraform apply`**, or set the env var on the Cloud Run service in console. Confirm **Vertex AI API** is enabled and billing is active; open **Vertex → Model Garden** if Google prompts you to enable access.
