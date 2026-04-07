# GitHub Actions deployer SA + WIF. Default github_repository is ak47/digital_twin; set to "" to skip.
# After apply, set repo secrets from outputs github_actions_wif_provider and github_actions_deployer_email.

locals {
  github_wif_enabled = var.github_repository != ""
}

resource "google_service_account" "github_deploy" {
  count = local.github_wif_enabled ? 1 : 0

  account_id   = "${var.name_prefix}-gha-deploy"
  display_name = "GitHub Actions (deploy, ingest, optional terraform)"
  project      = var.project_id
}

# Project-level writer avoids per-repository getIamPolicy/setIamPolicy (some principals lack that).
# Scope is all Artifact Registry repos in the project; acceptable for a dedicated deploy SA.
resource "google_project_iam_member" "github_deploy_ar_writer" {
  count = local.github_wif_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

resource "google_project_iam_member" "github_deploy_run_admin" {
  count = local.github_wif_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

# Ingest RAG corpus workflow calls rag.import_files (aiplatform.ragFiles.import); same role as runtime API.
resource "google_project_iam_member" "github_deploy_vertex_user" {
  count = local.github_wif_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

# Import may validate the caller can read gs:// corpus URIs (Vertex still ingests via its service agent).
resource "google_storage_bucket_iam_member" "corpus_github_deploy_object_viewer" {
  count = local.github_wif_enabled ? 1 : 0

  bucket = google_storage_bucket.corpus.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

# Remote state: read for ingest/plan; read+write when GitHub runs terraform apply (github_actions_terraform_roles non-empty).
resource "google_storage_bucket_iam_member" "github_deploy_terraform_state_access" {
  count = local.github_wif_enabled && trimspace(var.gha_terraform_state_bucket) != "" ? 1 : 0

  bucket = var.gha_terraform_state_bucket
  role   = length(var.github_actions_terraform_roles) > 0 ? "roles/storage.objectAdmin" : "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

resource "google_project_iam_member" "github_deploy_terraform_roles" {
  for_each = (
    local.github_wif_enabled && length(var.github_actions_terraform_roles) > 0
    ? toset(var.github_actions_terraform_roles)
    : toset([])
  )

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

# Allow gcloud run services update to keep using the runtime service account on the revision.
resource "google_service_account_iam_member" "github_deploy_act_as_runtime" {
  count = local.github_wif_enabled ? 1 : 0

  service_account_id = google_service_account.cloud_run_api.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_deploy[0].email}"
}

# Pool id was "${name_prefix}-github" originally; GCP still has that name if a past apply failed mid-flight.
# Using "-gha-wif" avoids perpetual 409 "already exists" when the old pool is orphaned outside Terraform state.
resource "google_iam_workload_identity_pool" "github" {
  count = local.github_wif_enabled ? 1 : 0

  workload_identity_pool_id = "${var.name_prefix}-gha-wif"
  display_name              = "GitHub Actions"
  project                   = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count = local.github_wif_enabled ? 1 : 0

  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"
  project                            = var.project_id

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
  }

  attribute_condition = "assertion.repository == '${var.github_repository}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_wif_impersonation" {
  count = local.github_wif_enabled ? 1 : 0

  service_account_id = google_service_account.github_deploy[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repository}"
}
