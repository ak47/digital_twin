# Idle session digest: Cloud Scheduler → Cloud Run Job → scan GCS sessions + Gmail.
# API service (cloud_run.tf) does not run digest logic.

locals {
  session_digest_ready = (
    var.session_digest_enabled
    && trimspace(var.session_digest_gmail_secret_id) != ""
    && trimspace(var.session_digest_delegated_user) != ""
    && trimspace(var.session_digest_email_to) != ""
  )
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_service_account" "scheduler_digest" {
  count = local.session_digest_ready ? 1 : 0

  account_id   = "${var.name_prefix}-digest-scheduler"
  display_name = "Cloud Scheduler → session digest job"
  project      = var.project_id
}

# Cloud Scheduler must mint OAuth tokens for the target SA.
resource "google_service_account_iam_member" "scheduler_agent_token_creator" {
  count = local.session_digest_ready ? 1 : 0

  service_account_id = google_service_account.scheduler_digest[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
}

resource "google_secret_manager_secret_iam_member" "digest_gmail_accessor" {
  count = local.session_digest_ready ? 1 : 0

  project   = var.project_id
  secret_id = var.session_digest_gmail_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_cloud_run_v2_job" "session_digest" {
  count = local.session_digest_ready ? 1 : 0

  name     = "${var.name_prefix}-session-digest"
  location = var.region
  project  = var.project_id

  template {
    template {
      timeout     = "900s"
      max_retries = 0

      service_account = google_service_account.cloud_run_api.email

      containers {
        image   = var.container_image
        command = ["python", "-m", "digital_twin.run_session_digest"]

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "GCP_REGION"
          value = var.region
        }
        env {
          name  = "GCS_SESSIONS_BUCKET"
          value = google_storage_bucket.sessions.name
        }
        env {
          name  = "RESUME_BOT_DIGEST_EMAIL_TO"
          value = var.session_digest_email_to
        }
        env {
          name  = "GMAIL_DELEGATED_USER"
          value = var.session_digest_delegated_user
        }
        env {
          name  = "RESUME_BOT_DIGEST_IDLE_MINUTES"
          value = tostring(var.session_digest_idle_minutes)
        }
        env {
          name  = "RESUME_BOT_DIGEST_TIMEZONE"
          value = var.session_digest_display_timezone
        }
        env {
          name = "GMAIL_SERVICE_ACCOUNT_JSON"
          value_source {
            secret_key_ref {
              secret  = var.session_digest_gmail_secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.digest_gmail_accessor,
    google_storage_bucket_iam_member.sessions_admin,
  ]
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invokes_digest_job" {
  count = local.session_digest_ready ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.session_digest[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_digest[0].email}"
}

resource "google_cloud_scheduler_job" "session_digest" {
  count = local.session_digest_ready ? 1 : 0

  name      = "${var.name_prefix}-session-digest"
  region    = var.region
  project   = var.project_id
  schedule  = var.session_digest_schedule
  time_zone = var.session_digest_scheduler_timezone

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.session_digest[0].name}:run"
    body        = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler_digest[0].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_project_service.required,
    google_cloud_run_v2_job_iam_member.scheduler_invokes_digest_job,
    google_service_account_iam_member.scheduler_agent_token_creator,
  ]
}
