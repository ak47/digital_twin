# Private family photo/video archive (spec 002-site-refresh in ak47.github.io).
# Never public: uniform bucket-level access + enforced public-access prevention.
# Clients only ever receive V4 signed URLs (GET, <= 15 min) from the family API.

locals {
  family_media_bucket_name = "${var.name_prefix}-family-media-${random_id.bucket_suffix.hex}"
}

resource "google_storage_bucket" "family_media" {
  name          = local.family_media_bucket_name
  location      = var.region
  project       = var.project_id
  force_destroy = var.bucket_force_destroy

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "family_media_viewer" {
  bucket = google_storage_bucket.family_media.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

# V4 signed URLs on Cloud Run: the runtime SA has no exportable key, so the API
# signs via IAM signBlob by impersonating itself (family_routes._signing_credentials).
resource "google_service_account_iam_member" "cloud_run_api_self_token_creator" {
  service_account_id = google_service_account.cloud_run_api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.cloud_run_api.email}"
}
