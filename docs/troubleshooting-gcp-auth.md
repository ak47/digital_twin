# Troubleshooting: GCP auth for Terraform and ADC

The Terraform Google provider uses **Application Default Credentials** (ADC). If your refresh token is stale or your organization requires **re-auth** (RAPT), API calls can fail with OAuth errors (for example `invalid_grant`, `invalid_rapt`, “reauth related error”) when enabling services.

## Refresh credentials

```bash
gcloud auth login
gcloud auth application-default login
gcloud auth list
gcloud config get-value project
```

If it still fails, revoke and sign in again:

```bash
gcloud auth revoke
gcloud auth login
gcloud auth application-default login
```

## Workspace / admin policies

Some Google Workspace policies force periodic re-auth or restrict certain flows. If errors persist, use an allowlisted account or a **service account key** (JSON) **only for Terraform**, with **`GOOGLE_APPLICATION_CREDENTIALS`** pointing to the key file — **never commit the key**.

## Wrong project ID

IDs like **`gen-lang-client-*`** are often tied to **Google AI Studio / consumer Gemini** flows, not a normal empty project in Cloud Console. This stack expects a **standard GCP project** where you have **Owner** or roles such as **Service Usage Admin** and **Project IAM Admin** plus billing.

If Terraform targets the wrong project, set **`TF_VAR_project_id`** or **`terraform/terraform.tfvars`** to the intended **`project_id`**.

Optional: keep **`GCP_PROJECT_ID`** in `.env` for **local app runs** only. You can sync with:

```bash
export TF_VAR_project_id="$GCP_PROJECT_ID"
```

after `source .env`.
