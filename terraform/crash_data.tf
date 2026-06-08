# Motor vehicle crash datasets (NYC + California) for digital-twin BigQuery tool queries.

locals {
  crash_data_bucket_name = "${var.name_prefix}-crash-data-${random_id.bucket_suffix.hex}"
  crash_data_bq_dataset  = var.crash_data_bq_dataset
}

resource "google_storage_bucket" "crash_data" {
  count = var.enable_crash_data ? 1 : 0

  name          = local.crash_data_bucket_name
  location      = var.region
  project       = var.project_id
  force_destroy = var.bucket_force_destroy

  uniform_bucket_level_access = true

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "crash_data" {
  count = var.enable_crash_data ? 1 : 0

  dataset_id                 = local.crash_data_bq_dataset
  friendly_name              = "Vehicle crash data (NYC + California)"
  description                = "NYC Open Data and California CCRS crash CSVs loaded for digital-twin SQL queries."
  location                   = var.region
  project                    = var.project_id
  delete_contents_on_destroy = var.bucket_force_destroy

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "crash_data_admin" {
  count = var.enable_crash_data ? 1 : 0

  bucket = google_storage_bucket.crash_data[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_bigquery_dataset_iam_member" "crash_data_viewer" {
  count = var.enable_crash_data ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.crash_data[0].dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_project_iam_member" "crash_data_job_user" {
  count = var.enable_crash_data ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_storage_bucket_iam_member" "crash_data_github_deploy" {
  count = local.github_wif_enabled && var.enable_crash_data ? 1 : 0

  bucket = google_storage_bucket.crash_data[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

resource "google_bigquery_dataset_iam_member" "crash_data_github_editor" {
  count = local.github_wif_enabled && var.enable_crash_data ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.crash_data[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

resource "google_project_iam_member" "crash_data_github_job_user" {
  count = local.github_wif_enabled && var.enable_crash_data ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.github_deploy[0].email}"
}
