# Idle session digest (email transcript)

When **GCS sessions** are enabled, you can send a **plain-text attachment** of each chat after **no activity for a configurable interval** (default 1 hour).

**Production:** Terraform can provision a **Cloud Run Job** and **Cloud Scheduler** ([`terraform/digest_job.tf`](../terraform/digest_job.tf)). The **API service does not** run a background scanner, so multiple API replicas do not duplicate digest sends.

**Email:** **`GMAIL_DELEGATED_USER`** and **`GMAIL_SERVICE_ACCOUNT_JSON`** (Secret Manager on the job). Mail is sent with the **Gmail API** as that Workspace user.

**Subject:** `resume bot chat YYYY-MM-DD HH:MM PST` (or PDT) — **US Pacific** by default (`RESUME_BOT_DIGEST_TIMEZONE`, default `America/Los_Angeles`). The body is short; the thread is in the `.txt` attachment.

## Google Workspace (no-ego.net)

1. **Workspace:** Create or choose a mailbox to send from, e.g. **`resume-bot@no-ego.net`**.
2. **GCP:** [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) is enabled by Terraform when using this stack ([`terraform/apis.tf`](../terraform/apis.tf)).
3. **Service account:** Create one in GCP → **IAM & Admin** → **Service accounts** → enable **Domain-wide delegation** (Google Workspace). Note the **numeric Client ID** (console or `client_id` in the JSON key).
4. **Workspace Admin** (admin.google.com) → **Security** → **Access and data control** → **API controls** → **Domain-wide delegation** → **Add new**:
   - **Client ID:** the SA’s numeric `client_id`
   - **OAuth scopes:** `https://www.googleapis.com/auth/gmail.send`
5. **Secret Manager:** Store the JSON key (once per project):

   ```bash
   gcloud secrets create gmail-digest-sa --data-file=./your-sa.json
   ```

   Terraform grants the Cloud Run runtime service account **`secretAccessor`** on that secret when digest is enabled.

6. **Terraform** ([`terraform/README.md`](../terraform/README.md) → *Idle session digest*): set **`session_digest_enabled = true`**, **`session_digest_gmail_secret_id`** (Secret Manager **secret id**, e.g. `gmail-digest-sa`), **`session_digest_delegated_user`**, and **`session_digest_email_to`**. Run **`terraform apply`**.

7. **GitHub Actions:** set repository **Variable** **`SESSION_DIGEST_JOB_NAME`** to Terraform output **`session_digest_job_name`** so **Deploy API** updates the job image on each deploy.

## Optional tuning (Terraform → job env)

- **`session_digest_idle_minutes`**
- **`session_digest_display_timezone`** → **`RESUME_BOT_DIGEST_TIMEZONE`**
- **`session_digest_schedule`** / **`session_digest_scheduler_timezone`** (Scheduler cron)

## Local one-shot

```bash
export GMAIL_SERVICE_ACCOUNT_KEY_FILE=/path/to/sa.json
export GMAIL_DELEGATED_USER='resume-bot@no-ego.net'
export RESUME_BOT_DIGEST_EMAIL_TO='you@example.com'
export GCS_SESSIONS_BUCKET='your-sessions-bucket'
python -m digital_twin.run_session_digest
```
