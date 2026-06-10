resource "google_cloud_run_v2_service" "api" {
  name                = "${var.name_prefix}-api"
  location            = var.region
  project             = var.project_id
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  # CD owns the container image (GitHub Actions deploy-api workflow).
  # Prevent `terraform apply` from reverting to the bootstrap/default image.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  template {
    service_account = google_service_account.cloud_run_api.email

    dynamic "volumes" {
      for_each = local.conversation_db_enabled ? [1] : []
      content {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.conversations[0].connection_name]
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = var.container_image

      ports {
        container_port = 8080
      }

      dynamic "volume_mounts" {
        for_each = local.conversation_db_enabled ? [1] : []
        content {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 2
        timeout_seconds       = 5
        period_seconds        = 5
        failure_threshold     = 12
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "GCS_CORPUS_BUCKET"
        value = google_storage_bucket.corpus.name
      }
      env {
        name  = "GCS_SESSIONS_BUCKET"
        value = google_storage_bucket.sessions.name
      }
      env {
        name  = "CORS_ALLOWED_ORIGINS"
        value = join(",", var.cors_allowed_origins)
      }
      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }
      env {
        name  = "MAX_OUTPUT_TOKENS"
        value = tostring(var.max_output_tokens)
      }

      env {
        name  = "RAG_ENGINE_DEPLOYMENT_MODE"
        value = var.rag_engine_deployment_mode
      }

      dynamic "env" {
        for_each = var.rag_corpus_resource_name != "" ? [1] : []
        content {
          name  = "RAG_CORPUS_RESOURCE"
          value = var.rag_corpus_resource_name
        }
      }

      dynamic "env" {
        for_each = var.enable_crash_data ? [1] : []
        content {
          name  = "CRASH_DATA_BQ_DATASET"
          value = var.crash_data_bq_dataset
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_enabled ? [1] : []
        content {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = local.conversation_database_url_secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready ? [1] : []
        content {
          name  = "GOOGLE_OAUTH_CLIENT_ID"
          value = var.google_oauth_client_id
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready ? [1] : []
        content {
          name = "GOOGLE_OAUTH_CLIENT_SECRET"
          value_source {
            secret_key_ref {
              secret  = var.google_oauth_client_secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready ? [1] : []
        content {
          name = "ADMIN_SESSION_SECRET"
          value_source {
            secret_key_ref {
              secret  = local.admin_session_secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready ? [1] : []
        content {
          name  = "ADMIN_ALLOWED_EMAILS"
          value = join(",", var.admin_allowed_emails)
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready && trimspace(var.admin_oauth_redirect_uri) != "" ? [1] : []
        content {
          name  = "ADMIN_OAUTH_REDIRECT_URI"
          value = var.admin_oauth_redirect_uri
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready && trimspace(var.admin_ui_redirect_url) != "" ? [1] : []
        content {
          name  = "ADMIN_UI_REDIRECT_URL"
          value = var.admin_ui_redirect_url
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready && trimspace(var.escalation_email_to) != "" ? [1] : []
        content {
          name  = "ESCALATION_EMAIL_TO"
          value = var.escalation_email_to
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready && trimspace(var.session_digest_gmail_secret_id) != "" ? [1] : []
        content {
          name = "GMAIL_SERVICE_ACCOUNT_JSON"
          value_source {
            secret_key_ref {
              secret  = var.session_digest_gmail_secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = local.conversation_db_app_ready && trimspace(var.session_digest_delegated_user) != "" ? [1] : []
        content {
          name  = "GMAIL_DELEGATED_USER"
          value = var.session_digest_delegated_user
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.vertex_user,
    google_storage_bucket_iam_member.corpus_admin,
    google_storage_bucket_iam_member.sessions_admin,
    google_project_iam_member.crash_data_job_user,
    google_bigquery_dataset_iam_member.crash_data_viewer,
    google_project_iam_member.cloud_run_cloud_sql_client,
    google_secret_manager_secret_iam_member.conversation_db_password_accessor,
    google_secret_manager_secret_iam_member.conversation_database_url_accessor,
    google_secret_manager_secret_iam_member.admin_session_secret_accessor,
    google_secret_manager_secret_iam_member.google_oauth_client_secret_accessor,
  ]
}

# Public HTTP access (rate limiting is app-level per plan)
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
