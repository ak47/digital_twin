resource "google_cloud_run_v2_service" "api" {
  name                 = "${var.name_prefix}-api"
  location             = var.region
  project              = var.project_id
  deletion_protection  = false
  ingress              = "INGRESS_TRAFFIC_ALL"

  # CD owns the container image (GitHub Actions deploy-api workflow).
  # Prevent `terraform apply` from reverting to the bootstrap/default image.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }

  template {
    service_account = google_service_account.cloud_run_api.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = var.container_image

      ports {
        container_port = 8080
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

      dynamic "env" {
        for_each = var.rag_corpus_resource_name != "" ? [1] : []
        content {
          name  = "RAG_CORPUS_RESOURCE"
          value = var.rag_corpus_resource_name
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.vertex_user,
    google_storage_bucket_iam_member.corpus_admin,
    google_storage_bucket_iam_member.sessions_admin,
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
