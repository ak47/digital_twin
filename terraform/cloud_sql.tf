# Cloud SQL PostgreSQL for conversation persistence + admin (feature 001).
#
# Apply order (terraform-managed secrets — default):
#   1. Set enable_conversation_db = true in terraform.tfvars
#   2. terraform apply  → creates instance, DB user, password + DATABASE_URL secrets
#   3. terraform output cloud_sql_connection_name
#   4. terraform output conversation_database_url_secret_id  → GitHub Variable
#   5. (Optional) Add admin OAuth secrets + admin_allowed_emails for Cloud Run admin env

locals {
  conversation_db_enabled = var.enable_conversation_db

  # Password + DATABASE_URL: Terraform-managed when secret id vars are empty (default).
  conversation_db_use_managed_password = (
    local.conversation_db_enabled && trimspace(var.conversation_db_password_secret_id) == ""
  )
  conversation_db_use_managed_database_url = (
    local.conversation_db_enabled && trimspace(var.conversation_database_url_secret_id) == ""
  )

  conversation_db_password_secret_id = (
    local.conversation_db_use_managed_password
    ? google_secret_manager_secret.conversation_db_password[0].secret_id
    : var.conversation_db_password_secret_id
  )

  conversation_database_url_secret_id = (
    local.conversation_db_use_managed_database_url
    ? google_secret_manager_secret.conversation_database_url[0].secret_id
    : var.conversation_database_url_secret_id
  )

  conversation_db_password = (
    local.conversation_db_use_managed_password
    ? random_password.conversation_db[0].result
    : data.google_secret_manager_secret_version.conversation_db_password_external[0].secret_data
  )

  # Cloud Run admin OAuth env (optional — instance exists without these).
  conversation_db_app_ready = (
    local.conversation_db_enabled
    && trimspace(var.admin_session_secret_id) != ""
    && trimspace(var.google_oauth_client_id) != ""
    && trimspace(var.google_oauth_client_secret_id) != ""
    && length(var.admin_allowed_emails) > 0
  )
}

resource "google_project_service" "sqladmin" {
  count = local.conversation_db_enabled ? 1 : 0

  project = var.project_id
  service = "sqladmin.googleapis.com"

  disable_on_destroy = false
}

resource "google_sql_database_instance" "conversations" {
  count = local.conversation_db_enabled ? 1 : 0

  name             = "${var.name_prefix}-conversations"
  database_version = "POSTGRES_15"
  region           = var.region
  project          = var.project_id

  settings {
    tier = var.conversation_db_tier

    ip_configuration {
      # Cloud Run connects via the built-in Cloud SQL connector (/cloudsql/…). Public IP is
      # required by the API; without authorized_networks the instance is not open to the internet.
      ipv4_enabled = true
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
  count = local.conversation_db_enabled ? 1 : 0

  name     = var.conversation_db_name
  instance = google_sql_database_instance.conversations[0].name
  project  = var.project_id
}

resource "random_password" "conversation_db" {
  count = local.conversation_db_use_managed_password ? 1 : 0

  length  = 32
  special = true
}

resource "google_secret_manager_secret" "conversation_db_password" {
  count = local.conversation_db_use_managed_password ? 1 : 0

  project   = var.project_id
  secret_id = "${var.name_prefix}-conversation-db-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "conversation_db_password" {
  count = local.conversation_db_use_managed_password ? 1 : 0

  secret      = google_secret_manager_secret.conversation_db_password[0].id
  secret_data = random_password.conversation_db[0].result
}

data "google_secret_manager_secret_version" "conversation_db_password_external" {
  count = local.conversation_db_enabled && !local.conversation_db_use_managed_password ? 1 : 0

  project = var.project_id
  secret  = var.conversation_db_password_secret_id
}

resource "google_sql_user" "conversations" {
  count = local.conversation_db_enabled ? 1 : 0

  name     = var.conversation_db_user
  instance = google_sql_database_instance.conversations[0].name
  project  = var.project_id
  password = local.conversation_db_password
}

resource "google_secret_manager_secret" "conversation_database_url" {
  count = local.conversation_db_use_managed_database_url ? 1 : 0

  project   = var.project_id
  secret_id = "${var.name_prefix}-conversation-database-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "conversation_database_url" {
  count = local.conversation_db_use_managed_database_url ? 1 : 0

  secret = google_secret_manager_secret.conversation_database_url[0].id
  secret_data = format(
    "postgresql+psycopg://%s:%s@/%s?host=/cloudsql/%s",
    var.conversation_db_user,
    urlencode(local.conversation_db_password),
    var.conversation_db_name,
    google_sql_database_instance.conversations[0].connection_name,
  )

  depends_on = [
    google_sql_user.conversations,
    google_sql_database.conversations,
  ]
}

resource "google_secret_manager_secret_iam_member" "conversation_db_password_accessor" {
  count = local.conversation_db_enabled ? 1 : 0

  project   = var.project_id
  secret_id = local.conversation_db_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"

  depends_on = [
    google_secret_manager_secret_version.conversation_db_password,
    google_secret_manager_secret.conversation_db_password,
    google_project_iam_member.github_deploy_secret_manager_admin,
  ]
}

resource "google_secret_manager_secret_iam_member" "conversation_database_url_accessor" {
  count = local.conversation_db_enabled ? 1 : 0

  project   = var.project_id
  secret_id = local.conversation_database_url_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"

  depends_on = [
    google_secret_manager_secret_version.conversation_database_url,
    google_secret_manager_secret.conversation_database_url,
    google_project_iam_member.github_deploy_secret_manager_admin,
  ]
}

resource "google_secret_manager_secret_iam_member" "admin_session_secret_accessor" {
  count = local.conversation_db_app_ready ? 1 : 0

  project   = var.project_id
  secret_id = var.admin_session_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_secret_manager_secret_iam_member" "google_oauth_client_secret_accessor" {
  count = local.conversation_db_app_ready ? 1 : 0

  project   = var.project_id
  secret_id = var.google_oauth_client_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_project_iam_member" "cloud_run_cloud_sql_client" {
  count = local.conversation_db_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run_api.email}"
}

resource "google_project_iam_member" "github_deploy_cloud_sql_client" {
  count = local.conversation_db_enabled && local.github_wif_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

resource "google_secret_manager_secret_iam_member" "github_deploy_database_url_accessor" {
  count = local.conversation_db_enabled && local.github_wif_enabled ? 1 : 0

  project   = var.project_id
  secret_id = local.conversation_database_url_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.github_deploy[0].email}"

  depends_on = [
    google_secret_manager_secret_version.conversation_database_url,
    google_secret_manager_secret.conversation_database_url,
    google_project_iam_member.github_deploy_secret_manager_admin,
  ]
}
