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

