# GitHub Actions — Terraform configuration

Terraform in CI uses **individual repository Variables and Secrets**, mapped to `TF_VAR_*` by [`scripts/gha-export-terraform-vars.sh`](../scripts/gha-export-terraform-vars.sh).

**Do not use `TERRAFORM_TFVARS`.** That pattern is removed — opaque blobs are hard to audit and easy to break.

Non-secret values live in **Settings → Secrets and variables → Actions → Variables** (visible, editable one at a time).  
Sensitive values use **Secrets** (values hidden; names visible).

## Required

| Name | Kind | Terraform variable | Example |
|------|------|-------------------|---------|
| `GCP_PROJECT_ID` | Secret | `project_id` | `digital-twin-492318` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Secret | (auth only) | `projects/…/providers/github-oidc` |
| `GCP_SERVICE_ACCOUNT_EMAIL` | Secret | (auth only) | `…-gha-deploy@….iam.gserviceaccount.com` |
| `CORS_ALLOWED_ORIGINS` | Variable | `cors_allowed_origins` | `https://no-ego.net,https://www.no-ego.net` |
| `TF_STATE_BUCKET` | Variable | `gha_terraform_state_bucket` | `ak47-digital-twin-terraform-state` |
| `TF_GITHUB_REPOSITORY` | Variable | `github_repository` | `ak47/digital_twin` |

`CORS_ALLOWED_ORIGINS` and `TF_STATE_BUCKET` are shared with **Deploy API** and **Ingest RAG**.

## Optional Terraform variables

Set only what you need; unset variables use defaults from [`terraform/variables.tf`](../terraform/variables.tf).

| GitHub Variable | Terraform variable | Example |
|-----------------|-------------------|---------|
| `TF_REGION` | `region` | `us-central1` |
| `TF_NAME_PREFIX` | `name_prefix` | `digital-twin` |
| `TF_RAG_CORPUS_RESOURCE_NAME` | `rag_corpus_resource_name` | `projects/…/ragCorpora/…` |
| `TF_RAG_ENGINE_DEPLOYMENT_MODE` | `rag_engine_deployment_mode` | `SERVERLESS` |
| `TF_RAG_CORPUS_INGEST_REGION` | `rag_corpus_ingest_region` | `` |
| `TF_GEMINI_MODEL` | `gemini_model` | `gemini-3-flash-preview` |
| `GEMINI_MODEL` | `gemini_model` | (fallback if `TF_GEMINI_MODEL` unset; used by Deploy API) |
| `TF_MAX_OUTPUT_TOKENS` | `max_output_tokens` | `1024` |
| `TF_CLOUD_RUN_CUSTOM_DOMAIN` | `cloud_run_custom_domain` | `digital-twin.no-ego.net` |
| `TF_ALERT_EMAIL` | `alert_email` | `you@example.com` |
| `TF_SESSION_DIGEST_ENABLED` | `session_digest_enabled` | `true` |
| `TF_SESSION_DIGEST_GMAIL_SECRET_ID` | `session_digest_gmail_secret_id` | `GMAIL_SERVICE_ACCOUNT_KEY_FILE` |
| `TF_SESSION_DIGEST_DELEGATED_USER` | `session_digest_delegated_user` | `you@example.com` |
| `TF_SESSION_DIGEST_EMAIL_TO` | `session_digest_email_to` | `you@example.com` |
| `TF_GITHUB_ACTIONS_TERRAFORM_ROLES` | `github_actions_terraform_roles` | `roles/editor,roles/resourcemanager.projectIamAdmin` |
| `TF_ENABLE_CONVERSATION_DB` | `enable_conversation_db` | `true` |
| `TF_ENABLE_CRASH_DATA` | `enable_crash_data` | `true` |
| `TF_ADMIN_ALLOWED_EMAILS` | `admin_allowed_emails` | `you@example.com,other@example.com` |
| `TF_GOOGLE_OAUTH_CLIENT_ID` | `google_oauth_client_id` | OAuth client id |
| `TF_GOOGLE_OAUTH_CLIENT_SECRET_ID` | `google_oauth_client_secret_id` | Secret Manager **secret id** — **must pre-create** with OAuth client secret from Google Console |
| `TF_ADMIN_SESSION_SECRET_ID` | `admin_session_secret_id` | Leave empty or `digital-twin-admin-session-secret` for Terraform-managed; custom ids must pre-exist |
| `TF_ADMIN_OAUTH_REDIRECT_URI` | `admin_oauth_redirect_uri` | `https://…/admin/auth/google/callback` |
| `TF_ADMIN_UI_REDIRECT_URL` | `admin_ui_redirect_url` | `https://no-ego.net/digital-twin-admin` |
| `TF_ESCALATION_EMAIL_TO` | `escalation_email_to` | `you@example.com` |

Comma-separated lists (`CORS_ALLOWED_ORIGINS`, `TF_ADMIN_ALLOWED_EMAILS`, `TF_GITHUB_ACTIONS_TERRAFORM_ROLES`) are converted to JSON arrays for Terraform.

Booleans (`TF_ENABLE_CONVERSATION_DB`, etc.): `true` / `false` (also `1` / `0`, `yes` / `no`).

## Admin OAuth bootstrap

After `TF_ENABLE_CONVERSATION_DB=true`, wire Google sign-in:

1. **Google Cloud Console** → Credentials → OAuth 2.0 Client ID (Web):
   - Redirect URI: `https://<api-host>/admin/auth/google/callback` (must match `TF_ADMIN_OAUTH_REDIRECT_URI`)
2. **OAuth client secret** (manual — Terraform cannot generate this):

   ```bash
   echo -n 'YOUR_CLIENT_SECRET' | gcloud secrets create digital-twin-google-oauth-client-secret \
     --project=YOUR_PROJECT_ID --data-file=-
   ```

3. **Session signing secret** — either omit `TF_ADMIN_SESSION_SECRET_ID` or set it to `digital-twin-admin-session-secret`; Terraform creates the secret and a random value on apply. Do **not** set a custom secret id unless you created that secret first.
4. Set GitHub Variables (`TF_GOOGLE_OAUTH_CLIENT_ID`, `TF_GOOGLE_OAUTH_CLIENT_SECRET_ID`, `TF_ADMIN_*`, `TF_ADMIN_ALLOWED_EMAILS`) and run **Terraform** workflow (apply).
5. Verify: `curl -sS -o /dev/null -w '%{http_code}\n' https://<api-host>/admin/auth/google` → `302` (not `503` JSON).

## Workflow behaviour

1. **[`.github/workflows/terraform.yml`](../.github/workflows/terraform.yml)** runs `scripts/gha-export-terraform-vars.sh`, then `terraform plan` / `apply`.
2. The script prints a **config summary** in the job log (non-secret values only) so you can see what Terraform will use without opening secrets.
3. **[Deploy API](../.github/workflows/deploy-api.yml)** reads Cloud SQL connection info from **remote state** after Terraform has applied — no extra DB variables.

## Bootstrap from your current `terraform.tfvars`

Generate `gh variable set` commands from your local file (review before running):

```bash
./scripts/gha-migrate-tfvars-to-variables.sh
```

Or set manually. Example for this project:

```bash
gh variable set TF_GITHUB_REPOSITORY --body "ak47/digital_twin"
gh variable set TF_RAG_CORPUS_RESOURCE_NAME --body "projects/digital-twin-492318/locations/us-central1/ragCorpora/3491837823584043008"
gh variable set TF_RAG_ENGINE_DEPLOYMENT_MODE --body "SERVERLESS"
gh variable set TF_CLOUD_RUN_CUSTOM_DOMAIN --body "digital-twin.no-ego.net"
gh variable set TF_ALERT_EMAIL --body "andrew@no-ego.net"
gh variable set TF_SESSION_DIGEST_ENABLED --body "true"
gh variable set TF_SESSION_DIGEST_GMAIL_SECRET_ID --body "GMAIL_SERVICE_ACCOUNT_KEY_FILE"
gh variable set TF_SESSION_DIGEST_DELEGATED_USER --body "andrew@no-ego.net"
gh variable set TF_SESSION_DIGEST_EMAIL_TO --body "andrew@no-ego.net"
gh variable set TF_GITHUB_ACTIONS_TERRAFORM_ROLES --body "roles/editor,roles/resourcemanager.projectIamAdmin"
gh variable set TF_ENABLE_CONVERSATION_DB --body "true"
gh variable set GEMINI_MODEL --body "gemini-3-flash-preview"
```

Remove repository secret `TERRAFORM_TFVARS` if it exists.

## Local development

Use gitignored `terraform/terraform.tfvars` or export `TF_VAR_*` in your shell. CI does not use the local tfvars file.
