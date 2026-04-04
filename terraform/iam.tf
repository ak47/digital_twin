resource "google_service_account" "cloud_run_api" {
  account_id   = "${var.name_prefix}-api"
  display_name = "Digital twin API (Cloud Run)"
  project      = var.project_id
}

# Read corpus files for RAG ingestion jobs + runtime if needed
resource "google_storage_bucket_iam_member" "corpus_admin" {
  bucket = google_storage_bucket.corpus.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_storage_bucket_iam_member" "sessions_admin" {
  bucket = google_storage_bucket.sessions.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

# Vertex AI: generate content + RAG retrieval
resource "google_project_iam_member" "vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.cloud_run_api.email}"
}
