locals {
  required_apis = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "iamcredentials.googleapis.com",
    "compute.googleapis.com", # Cloud Run dependencies
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_apis

  project = var.project_id
  service = each.key

  disable_on_destroy = false
}
