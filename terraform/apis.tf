locals {
  required_apis = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "clouderrorreporting.googleapis.com",
    "cloudtrace.googleapis.com",
    "cloudprofiler.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "iamcredentials.googleapis.com",
    "iam.googleapis.com",
    "sts.googleapis.com",     # Workload Identity Federation (GitHub Actions OIDC)
    "compute.googleapis.com", # Cloud Run dependencies
    "cloudscheduler.googleapis.com",
    "gmail.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_apis

  project = var.project_id
  service = each.key

  disable_on_destroy = false
}
