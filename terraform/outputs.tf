output "region" {
  value = var.region
}

output "corpus_bucket_name" {
  description = "Upload curated Markdown/PDF corpus here; RAG ingest jobs read from this bucket."
  value       = google_storage_bucket.corpus.name
}

output "sessions_bucket_name" {
  description = "Cloud Run stores per-session JSON under a prefix (e.g. sessions/)."
  value       = google_storage_bucket.sessions.name
}

output "artifact_registry_repository" {
  description = "docker push ... then deploy Cloud Run with this image."
  value       = "${var.region}-docker.pkg.dev/${nonsensitive(var.project_id)}/${google_artifact_registry_repository.docker.repository_id}/api"
}

output "cloud_run_service_account" {
  value       = google_service_account.cloud_run_api.email
  description = "Attach this SA to the Cloud Run service."
}

output "rag_engine_config_name" {
  value       = google_vertex_ai_rag_engine_config.main.name
  description = "RAG Engine config resource name (managed DB tier provisioned)."
}

output "cors_allowed_origins" {
  value = var.cors_allowed_origins
}

output "cloud_run_uri" {
  description = "HTTPS URL for the API (map digital_twin.no-ego.net here)."
  value       = google_cloud_run_v2_service.api.uri
}

output "github_actions_wif_provider" {
  description = "Repository secret GCP_WORKLOAD_IDENTITY_PROVIDER (full resource name). Null if github_repository is unset."
  value       = one(google_iam_workload_identity_pool_provider.github[*].name)
}

output "github_actions_deployer_email" {
  description = "Repository secret GCP_SERVICE_ACCOUNT_EMAIL. Null if github_repository is unset."
  value       = one(google_service_account.github_deploy[*].email)
}
