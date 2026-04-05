resource "google_service_account" "cloud_run_api" {
  account_id   = "${var.name_prefix}-api"
  display_name = "Digital twin API (Cloud Run)"
  project      = var.project_id
}

# Vertex (incl. RAG ingest) reads GCS corpus objects with the Vertex AI Service Agent.
resource "google_storage_bucket_iam_member" "corpus_vertex_service_agent" {
  bucket = google_storage_bucket.corpus.name
  role   = "roles/storage.objectViewer"
  member = google_project_service_identity.vertex_ai.member

  depends_on = [
    google_project_service_identity.vertex_ai,
    google_vertex_ai_rag_engine_config.main,
  ]
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
