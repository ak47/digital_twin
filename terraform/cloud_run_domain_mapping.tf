# Optional: map a verified hostname to the API Cloud Run service (same as Console → Custom domains).
# Set var.cloud_run_custom_domain (e.g. digital-twin.no-ego.net). The registrable domain must be
# verified for this GCP project first (Search Console or `gcloud domains verify`).

resource "google_cloud_run_domain_mapping" "api" {
  count = var.cloud_run_custom_domain != "" ? 1 : 0

  location = var.region
  name     = var.cloud_run_custom_domain
  project  = var.project_id

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = google_cloud_run_v2_service.api.name
  }

  depends_on = [
    google_cloud_run_v2_service.api,
  ]
}
