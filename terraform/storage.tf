resource "random_id" "bucket_suffix" {
  byte_length = 3
}

locals {
  corpus_bucket_name   = "${var.name_prefix}-corpus-${random_id.bucket_suffix.hex}"
  sessions_bucket_name = "${var.name_prefix}-sessions-${random_id.bucket_suffix.hex}"
}

# RAG / curated documents (upload via CI or gsutil; not world-readable)
resource "google_storage_bucket" "corpus" {
  name          = local.corpus_bucket_name
  location      = var.region
  project       = var.project_id
  force_destroy = var.bucket_force_destroy

  uniform_bucket_level_access = true

  depends_on = [google_project_service.required]
}

# Ephemeral chat session JSON (per X-Session-Id)
resource "google_storage_bucket" "sessions" {
  name          = local.sessions_bucket_name
  location      = var.region
  project       = var.project_id
  force_destroy = var.bucket_force_destroy

  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = var.session_retention_days
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}
