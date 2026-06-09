locals {
  # Metric + alert resources are optional so forks/dev environments can skip them
  # simply by not providing alert_email.
  alerts_enabled = local.monitoring_enabled
}

# -----------------------------
# Log-based metrics
# -----------------------------

resource "google_logging_metric" "api_errors" {
  count = local.alerts_enabled ? 1 : 0

  project = var.project_id
  name    = "${var.name_prefix}_api_errors"

  # Cloud Run service logs. This catches uncaught exceptions and error logs from app/uvicorn.
  filter = join(" ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${var.name_prefix}-api\"",
    "(severity>=ERROR)",
  ])

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "${var.name_prefix} API errors"
  }

  depends_on = [
    google_project_service.required,
  ]
}

resource "google_logging_metric" "digest_job_errors" {
  count = local.alerts_enabled ? 1 : 0

  project = var.project_id
  name    = "${var.name_prefix}_digest_job_errors"

  # Cloud Run Job logs.
  # Note: if the digest job is disabled, this metric remains harmless; it will just have no data.
  filter = join(" ", [
    "resource.type=\"cloud_run_job\"",
    "resource.labels.job_name=\"${var.name_prefix}-session-digest\"",
    "(severity>=ERROR)",
  ])

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "${var.name_prefix} digest job errors"
  }

  depends_on = [
    google_project_service.required,
  ]
}

resource "google_logging_metric" "escalation_email_failed" {
  count = local.alerts_enabled ? 1 : 0

  project = var.project_id
  name    = "${var.name_prefix}_escalation_email_failed"

  filter = join(" ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${var.name_prefix}-api\"",
    "jsonPayload.event=\"escalation_email_failed\"",
  ])

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "${var.name_prefix} escalation email failures"
  }

  depends_on = [
    google_project_service.required,
  ]
}

resource "google_logging_metric" "chat_model_invocation_failed" {
  count = local.alerts_enabled ? 1 : 0

  project = var.project_id
  name    = "${var.name_prefix}_chat_model_invocation_failed"

  filter = join(" ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${var.name_prefix}-api\"",
    "jsonPayload.event=\"chat_model_invocation_failed\"",
  ])

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "${var.name_prefix} chat model invocation failures"
  }

  depends_on = [
    google_project_service.required,
  ]
}

resource "google_logging_metric" "chat_session_persist_failed" {
  count = local.alerts_enabled ? 1 : 0

  project = var.project_id
  name    = "${var.name_prefix}_chat_session_persist_failed"

  filter = join(" ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${var.name_prefix}-api\"",
    "jsonPayload.event=\"chat_session_persist_failed\"",
  ])

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "${var.name_prefix} chat session persist failures"
  }

  depends_on = [
    google_project_service.required,
  ]
}

resource "time_sleep" "wait_for_logging_metrics" {
  count = local.alerts_enabled ? 1 : 0

  # Logging metrics can take several minutes to become queryable from Monitoring.
  create_duration = "2m"

  depends_on = [
    google_logging_metric.api_errors,
    google_logging_metric.digest_job_errors,
    google_logging_metric.chat_model_invocation_failed,
    google_logging_metric.chat_session_persist_failed,
  ]
}

# -----------------------------
# Alert policies
# -----------------------------

resource "google_monitoring_alert_policy" "api_errors" {
  count = local.alerts_enabled ? 1 : 0

  project      = var.project_id
  display_name = "${var.name_prefix} API errors"
  combiner     = "OR"

  notification_channels = [
    google_monitoring_notification_channel.email[0].name,
  ]

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      ## What happened
      The Cloud Run API service logged one or more ERROR-level entries.

      ## Where to look
      - Cloud Logging: filter to service `${var.name_prefix}-api`
      - Error Reporting: check error groups for stack traces
    EOT
  }

  # Per Monitoring metric descriptor, this log-based metric is only valid with
  # monitored resource type cloud_run_revision.
  conditions {
    display_name = "API errors (any in 5m)"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.api_errors[0].name}\" resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_DELTA"
      }

      trigger {
        count = 1
      }
    }
  }

  depends_on = [
    google_logging_metric.api_errors,
    google_monitoring_notification_channel.email,
    time_sleep.wait_for_logging_metrics,
  ]
}

resource "google_monitoring_alert_policy" "digest_job_errors" {
  count = local.alerts_enabled ? 1 : 0

  project      = var.project_id
  display_name = "${var.name_prefix} digest job failures"
  combiner     = "OR"

  notification_channels = [
    google_monitoring_notification_channel.email[0].name,
  ]

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      ## What happened
      The Cloud Run Job `${var.name_prefix}-session-digest` logged an ERROR-level entry (often indicates a failed run).

      ## Where to look
      - Cloud Run Jobs → Executions → logs
      - Cloud Logging: filter to job `${var.name_prefix}-session-digest`
    EOT
  }

  # Per Monitoring metric descriptor, this log-based metric is only valid with
  # monitored resource type cloud_run_job.
  conditions {
    display_name = "Digest job errors (any in 15m)"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.digest_job_errors[0].name}\" resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "900s"
        per_series_aligner = "ALIGN_DELTA"
      }

      trigger {
        count = 1
      }
    }
  }

  depends_on = [
    google_logging_metric.digest_job_errors,
    google_monitoring_notification_channel.email,
    time_sleep.wait_for_logging_metrics,
  ]
}

resource "google_monitoring_alert_policy" "api_critical_events" {
  count = local.alerts_enabled ? 1 : 0

  project      = var.project_id
  display_name = "${var.name_prefix} API critical events"
  combiner     = "OR"

  notification_channels = [
    google_monitoring_notification_channel.email[0].name,
  ]

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      ## What happened
      The API emitted one or more critical structured log events:
      - `chat_model_invocation_failed`
      - `chat_session_persist_failed`

      ## Where to look
      - Cloud Logging query:
        `resource.type="cloud_run_revision" resource.labels.service_name="${var.name_prefix}-api" (jsonPayload.event="chat_model_invocation_failed" OR jsonPayload.event="chat_session_persist_failed")`
      - Error Reporting: check grouped exceptions for stack traces
    EOT
  }

  conditions {
    display_name = "Chat model invocation failures (any in 5m)"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.chat_model_invocation_failed[0].name}\" resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_DELTA"
      }

      trigger {
        count = 1
      }
    }
  }

  conditions {
    display_name = "Chat session persist failures (any in 5m)"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.chat_session_persist_failed[0].name}\" resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_DELTA"
      }

      trigger {
        count = 1
      }
    }
  }

  depends_on = [
    google_logging_metric.chat_model_invocation_failed,
    google_logging_metric.chat_session_persist_failed,
    google_monitoring_notification_channel.email,
    time_sleep.wait_for_logging_metrics,
  ]
}

resource "google_monitoring_alert_policy" "api_errors_sustained" {
  count = local.alerts_enabled ? 1 : 0

  project      = var.project_id
  display_name = "${var.name_prefix} API sustained errors"
  combiner     = "OR"

  notification_channels = [
    google_monitoring_notification_channel.email[0].name,
  ]

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      ## What happened
      The API logged sustained ERROR-level volume over a 10-minute alignment window.

      ## Where to look
      - Cloud Logging: filter service `${var.name_prefix}-api` with `severity>=ERROR`
      - Recent deploys/config changes
    EOT
  }

  conditions {
    display_name = "API errors (>=5 in 10m)"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.api_errors[0].name}\" resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 4
      duration        = "0s"

      aggregations {
        alignment_period   = "600s"
        per_series_aligner = "ALIGN_DELTA"
      }

      trigger {
        count = 1
      }
    }
  }

  depends_on = [
    google_logging_metric.api_errors,
    google_monitoring_notification_channel.email,
    time_sleep.wait_for_logging_metrics,
  ]
}

