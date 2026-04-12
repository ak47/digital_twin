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
  - `${name_prefix} API critical events` (structured `chat_model_invocation_failed` / `chat_session_persist_failed`)
  - `${name_prefix} API sustained errors` (>= 5 ERROR logs in 10 minutes)

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

Local smoke: `uv sync --extra dev`, `export GOOGLE_CLOUD_PROJECT=...`, optional `METRICS_DEBUG=1 uv run python scripts/emit_test_metric.py`.

### If metrics do not appear in Metrics Explorer

1. **Confirm the write API succeeded** (not just “ok” printed):
   - `METRICS_DEBUG=1 uv run python scripts/emit_test_metric.py --verbose` — should log `metrics ok:` or a full exception.
   - Exit code **2** means the Monitoring API rejected the write.

2. **Correct GCP project in the console** — metrics land in the project passed to `create_time_series` (`GOOGLE_CLOUD_PROJECT` / metadata project id), not necessarily the org/folder you have selected elsewhere.

3. **Wait 2–5 minutes** after the first successful point for a new `custom.googleapis.com/...` type to show up in the metric picker.

4. **List metric descriptors** (after a successful write). There is often **no GA `gcloud monitoring metrics-descriptors`** command; use the API instead:

   ```bash
   # Python (needs: uv sync — includes google-cloud-monitoring; ADC)
   uv run python - <<'PY'
   from google.cloud import monitoring_v3
   client = monitoring_v3.MetricServiceClient()
   project = "projects/YOUR_PROJECT_ID"
   prefix = "custom.googleapis.com/digital_twin/"
   for d in client.list_metric_descriptors(name=project):
       if d.type.startswith(prefix):
           print(d.type)
   PY
   ```

   ```bash
   # curl + jq (paginate with nextPageToken if needed)
   PROJECT_ID="YOUR_PROJECT_ID"
   curl -sS -H "Authorization: Bearer $(gcloud auth print-access-token)" \
     "https://monitoring.googleapis.com/v3/projects/${PROJECT_ID}/metricDescriptors" \
     | jq -r '.metricDescriptors[]?.type | select(startswith("custom.googleapis.com/digital_twin/"))'
   ```

5. **Production: rebuild and redeploy the image** so the container includes `google-cloud-monitoring` from `pyproject.toml`. An old image will import-fail and skip writes (use `METRICS_DEBUG=1` on the service to see errors in logs).

6. **Production IAM**: Cloud Run uses its **service account**, not your user. Ensure Terraform applied `roles/monitoring.metricWriter` for that SA.

## App-level reporting behavior

The application uses:

- `google-cloud-logging` to integrate Python logging with Cloud Logging on GCP
- `google-cloud-error-reporting` for explicit reporting of **caught-but-important** exceptions

Application and uvicorn logs are emitted as structured JSON with a shared schema. Core fields:

- Required: `event`, `severity`, `service`, `env`, `timestamp`, `request_id`, `trace_id`, `session_id`
- Error-focused: `error_type`, `error_code`, `where`, `exception_message`, `stacktrace`
- Runtime context examples: `status`, `http_path`, `status_code`, `rag_mode`, `gemini_model`

Example structured event names:

- `chat_model_invocation_failed`
- `chat_session_persist_failed`
- `chat_request_completed`
- `exception_reported`

## Query cookbook (Cloud Logging)

Look up API model failures:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="${name_prefix}-api"
jsonPayload.event="chat_model_invocation_failed"
```

Group all request logs for one request id:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="${name_prefix}-api"
jsonPayload.request_id="REQUEST_ID_HERE"
```

Find sessions that failed to persist:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="${name_prefix}-api"
jsonPayload.event="chat_session_persist_failed"
```

Find all reported exceptions by location:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="${name_prefix}-api"
jsonPayload.event="exception_reported"
jsonPayload.where="chat_post.run_model"
```

## Rollout verification checklist

- Deploy to non-prod and make one normal chat request.
- Verify logs include `jsonPayload.request_id` and `jsonPayload.session_id`.
- Trigger a controlled failure path (non-prod) and verify:
  - `chat_model_invocation_failed` or `chat_session_persist_failed` exists in logs
  - stack trace appears in `jsonPayload.stacktrace`
  - Error Reporting receives the grouped exception
  - `${name_prefix} API critical events` policy opens and resolves
- Verify broad fallback alert `${name_prefix} API errors` still fires for uncaught ERROR logs.

## Rollback strategy

- Keep broad `severity>=ERROR` log metrics and alerts enabled during rollout.
- If parser/format regressions happen, first remove `--log-config /app/uvicorn_logging.json` and redeploy.
- If needed, revert app-level structured event emission while keeping existing Terraform coarse alerts.
- Terraform alert additions can be reverted independently from app runtime changes.

## Billing (RAG / Spanner vs Serverless)

After changing Vertex AI RAG deployment mode, use **Billing → Reports** (or **Cost table**) to confirm costs moved as expected:

- **Spanner mode** (`rag_engine_deployment_mode` **SPANNER_BASIC** or **SPANNER_SCALED**): expect a **Cloud Spanner** line item for the RAG-managed instance while configs exist in those regions.
- **Serverless mode** (`rag_engine_deployment_mode` **SERVERLESS**): Terraform does **not** create `google_vertex_ai_rag_engine_config`; Spanner charges for RAG should **stop** after the old regional configs are removed and the project uses [Serverless RAG](https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/serverless-mode). You may still see **Vertex AI** / **Vector Search** usage for embeddings and retrieval — see [RAG Engine billing](https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-engine-billing).

## How to test (suggested)

- **API**: in a non-prod environment, deliberately trigger an exception path and confirm:
  - a log entry with `severity>=ERROR`
  - a corresponding Error Reporting entry (if applicable)
  - an email notification from the alert policy
- **Digest job**: run the Cloud Run Job with intentionally invalid configuration (non-prod) and confirm the same.

