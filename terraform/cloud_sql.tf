# Cloud SQL PostgreSQL for conversation persistence + admin (feature 001).
# Disabled by default; set enable_conversation_db = true in terraform.tfvars.

locals {
  conversation_db_ready = (
    var.enable_conversation_db
    && trimspace(var.conversation_db_password_secret_id) != ""
    && trimspace(var.conversation_database_url_secret_id) != ""
    && trimspace(var.admin_session_secret_id) != ""
    && trimspace(var.google_oauth_client_id) != ""
    && trimspace(var.google_oauth_client_secret_id) != ""
    && length(var.admin_allowed_emails) > 0
  )
}

resource "google_sql_database_instance" "conversations" {
  count = local.conversation_db_ready ? 1 : 0

  name             = "${var.name_prefix}-conversations"
  database_version = "POSTGRES_15"
  region           = var.region
  project          = var.project_id

  settings {
    tier = var.conversation_db_tier

    ip_configuration {
      ipv4_enabled    = false
      private_network = null
    }

    backup_configuration {
      enabled = true
    }

    database_flags {
      name  = "max_connections"
      value = "50"
    }
  }

  deletion_protection = false

  depends_on = [
    google_project_service.required,
    google_project_service.sqladmin,
  ]
}

resource "google_sql_database" "conversations" {
  count = local.conversation_db_ready ? 1 : 0

  name     = var.conversation_db_name
  instance = google_sql_database_instance.conversations[0].name
  project  = var.project_id
}

resource "google_sql_user" "conversations" {
  count = local.conversation_db_ready ? 1 : 0

  name     = var.conversation_db_user
  instance = google_sql_database_instance.conversations[0].name
  project  = var.project_id
  password = data.google_secret_manager_secret_version.conversation_db_password[0].secret_data
}

data "google_secret_manager_secret_version" "conversation_db_password" {
  count = local.conversation_db_ready ? 1 : 0

  project = var.project_id
  secret  = var.conversation_db_password_secret_id
}

resource "google_secret_manager_secret_iam_member" "conversation_db_password_accessor" {
  count = local.conversation_db_ready ? 1 : 0

  project   = var.project_id
  secret_id = var.conversation_db_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_secret_manager_secret_iam_member" "admin_session_secret_accessor" {
  count = local.conversation_db_ready ? 1 : 0

  project   = var.project_id
  secret_id = var.admin_session_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_secret_manager_secret_iam_member" "google_oauth_client_secret_accessor" {
  count = local.conversation_db_ready ? 1 : 0

  project   = var.project_id
  secret_id = var.google_oauth_client_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_secret_manager_secret_iam_member" "conversation_database_url_accessor" {
  count = local.conversation_db_ready ? 1 : 0

  project   = var.project_id
  secret_id = var.conversation_database_url_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_project_iam_member" "cloud_run_cloud_sql_client" {
  count = local.conversation_db_ready ? 1 : 0

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_project_iam_member" "github_deploy_cloud_sql_client" {
  count = local.conversation_db_ready && local.github_wif_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

resource "google_secret_manager_secret_iam_member" "github_deploy_database_url_accessor" {
  count = local.conversation_db_ready && local.github_wif_enabled ? 1 : 0

  project   = var.project_id
  secret_id = var.conversation_database_url_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

resource "google_project_service" "sqladmin" {
  count = var.enable_conversation_db ? 1 : 0

  project = var.project_id
  service = "sqladmin.googleapis.com"

  disable_on_destroy = false
}
