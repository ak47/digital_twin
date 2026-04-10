# Observability (errors + alerts)

This project uses **GCP-native** observability for production:

- **Cloud Logging**: all app/job logs (stdout/stderr from Cloud Run).
- **Cloud Error Reporting**: groups exceptions into error groups with stack traces.
- **Cloud Monitoring**: alerting policies + notification channels (email).

## What’s configured (Terraform)

Terraform provisions (when `alert_email` is set):

- An email notification channel: `google_monitoring_notification_channel.email`
- Log-based metrics:
  - `${name_prefix}_api_errors` (Cloud Run service `${name_prefix}-api`, `severity>=ERROR`)
  - `${name_prefix}_digest_job_errors` (Cloud Run job `${name_prefix}-session-digest`, `severity>=ERROR`)
- Alert policies:
  - `${name_prefix} API errors` (any errors in 5 minutes)
  - `${name_prefix} digest job failures` (any errors in 15 minutes)

To enable in a given environment, pass `alert_email` via GitHub Actions (recommended) or Terraform CLI:

- GitHub Actions: include `alert_email="you@domain.com"` in `TERRAFORM_TFVARS` (see [`README.md`](../README.md)).
- CLI: `terraform apply -var 'alert_email=you@domain.com'`

If `alert_email` is empty, monitoring resources are skipped.

## Where to look in GCP

- **Cloud Logging**:
  - Cloud Run service logs: filter to service `${name_prefix}-api`
  - Cloud Run job logs: filter to job `${name_prefix}-session-digest`
- **Error Reporting**:
  - Look for error groups and stack traces for the service/job
- **Cloud Monitoring**:
  - Alerting → Policies: `${name_prefix} API errors`, `${name_prefix} digest job failures`
  - Alerting → Notification channels: `${name_prefix} alerts (email)`

## Custom latency metrics (RAG + Gemini)

The API writes custom Cloud Monitoring metrics (Cloud Run SA needs `roles/monitoring.metricWriter` from Terraform). Points use monitored resource type **`global`** (project id only). Cloud Run service/revision are **metric labels** (`cloud_run_service`, `cloud_run_revision`, `deploy_region`) because user-defined metrics **cannot** be written to `cloud_run_revision`.

- `custom.googleapis.com/digital_twin/rag_retrieval_latency_ms`
- `custom.googleapis.com/digital_twin/gemini_generate_latency_ms`
- `custom.googleapis.com/digital_twin/chat_model_latency_ms`
- `custom.googleapis.com/digital_twin/chat_total_latency_ms`

In **Metrics Explorer**, search for `custom.googleapis.com/digital_twin/`. Chart **P50/P95** and group/breakdown by labels like:

- `rag_mode` (spanner/serverless/unknown). Set **`RAG_ENGINE_DEPLOYMENT_MODE`** on the service (`SPANNER_BASIC`, `SPANNER_SCALED`, or `SERVERLESS`) so comparisons are meaningful.
- `rag_location`
- `gemini_model`
- `status`

Local smoke: `pip install -e .`, `export GOOGLE_CLOUD_PROJECT=...`, optional `METRICS_DEBUG=1 python3 scripts/emit_test_metric.py`.

### If metrics do not appear in Metrics Explorer

1. **Confirm the write API succeeded** (not just “ok” printed):
   - `METRICS_DEBUG=1 python3 scripts/emit_test_metric.py --verbose` — should log `metrics ok:` or a full exception.
   - Exit code **2** means the Monitoring API rejected the write.

2. **Correct GCP project in the console** — metrics land in the project passed to `create_time_series` (`GOOGLE_CLOUD_PROJECT` / metadata project id), not necessarily the org/folder you have selected elsewhere.

3. **Wait 2–5 minutes** after the first successful point for a new `custom.googleapis.com/...` type to show up in the metric picker.

4. **List metric descriptors** (after a successful write):

   ```bash
   gcloud monitoring metrics-descriptors list \
     --project=YOUR_PROJECT_ID \
     --filter='metric.type=starts_with("custom.googleapis.com/digital_twin/")' \
     --format='table(type)'
   ```

5. **Production: rebuild and redeploy the image** so the container includes `google-cloud-monitoring` from `pyproject.toml`. An old image will import-fail and skip writes (use `METRICS_DEBUG=1` on the service to see errors in logs).

6. **Production IAM**: Cloud Run uses its **service account**, not your user. Ensure Terraform applied `roles/monitoring.metricWriter` for that SA.

## App-level reporting behavior

The application uses:

- `google-cloud-logging` to integrate Python logging with Cloud Logging on GCP
- `google-cloud-error-reporting` for explicit reporting of **caught-but-important** exceptions

You’ll still see stack traces in logs via `logger.exception(...)`.

## How to test (suggested)

- **API**: in a non-prod environment, deliberately trigger an exception path and confirm:
  - a log entry with `severity>=ERROR`
  - a corresponding Error Reporting entry (if applicable)
  - an email notification from the alert policy
- **Digest job**: run the Cloud Run Job with intentionally invalid configuration (non-prod) and confirm the same.

