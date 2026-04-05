# Vertex AI’s Google-managed service account (service-…@gcp-sa-aiplatform.iam.gserviceaccount.com)
# is not always present for IAM bindings until the Service Identity API provisions it. Without this,
# bucket IAM returns: "Service account …@gcp-sa-aiplatform… does not exist".
resource "google_project_service_identity" "vertex_ai" {
  provider = google-beta

  project = var.project_id
  service = "aiplatform.googleapis.com"

  depends_on = [google_project_service.required["aiplatform.googleapis.com"]]
}
