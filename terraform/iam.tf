data "google_project" "project" {
  project_id = var.project_id
}

resource "google_service_account" "cloud_run_api" {
  account_id   = "${var.name_prefix}-api"
  display_name = "Digital twin API (Cloud Run)"
  project      = var.project_id
}

# Vertex (incl. RAG ingest) reads GCS sources with the Vertex AI Service Agent. We avoid
# @gcp-sa-aiplatform-rag here: that SA is often not provisioned until first RAG use and Terraform
# then fails with "does not exist" on bucket IAM.
resource "google_storage_bucket_iam_member" "corpus_vertex_service_agent" {
  bucket = google_storage_bucket.corpus.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-aiplatform.iam.gserviceaccount.com"

  depends_on = [
    google_project_service.required,
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
