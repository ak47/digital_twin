output "region" {
  value = var.region
}

output "project_id_for_github" {
  description = "GitHub secret GCP_PROJECT_ID — copy after apply (same as TF_VAR_project_id)."
  value       = nonsensitive(var.project_id)
}

output "corpus_bucket_name" {
  description = "Upload curated Markdown/PDF corpus here; RAG ingest jobs read from this bucket."
  value       = google_storage_bucket.corpus.name
}

output "rag_corpus_resource_name" {
  description = "Full Vertex RagCorpus resource wired to Cloud Run RAG_CORPUS_RESOURCE (same as var.rag_corpus_resource_name)."
  value       = var.rag_corpus_resource_name
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
  value = (
    var.rag_engine_deployment_mode == "SERVERLESS"
    ? "projects/${nonsensitive(var.project_id)}/locations/${var.region}/ragEngineConfig"
    : nonsensitive(google_vertex_ai_rag_engine_config.main[var.region].name)
  )
  description = "RAG Engine singleton resource name in var.region. When SERVERLESS, this is the conventional name (config is not Terraform-managed)."
}

output "rag_engine_config_names_by_region" {
  value = (
    var.rag_engine_deployment_mode == "SERVERLESS"
    ? { (var.region) = "projects/${nonsensitive(var.project_id)}/locations/${var.region}/ragEngineConfig" }
    : { for r, cfg in google_vertex_ai_rag_engine_config.main : r => nonsensitive(cfg.name) }
  )
  description = "All Terraform-managed RAG Engine configs, or the primary region name when SERVERLESS."
}

output "cors_allowed_origins" {
  value = var.cors_allowed_origins
}

output "cloud_run_uri" {
  description = "HTTPS URL for the API (map your custom hostname here when using cloud_run_custom_domain)."
  value       = google_cloud_run_v2_service.api.uri
}

output "cloud_run_custom_domain_url" {
  description = "HTTPS URL when cloud_run_custom_domain is set; use after DNS records propagate."
  value       = var.cloud_run_custom_domain != "" ? "https://${var.cloud_run_custom_domain}" : null
}

output "cloud_run_custom_domain_dns_records" {
  description = "DNS records for the domain mapping (type, name, rrdata). Add at your DNS provider."
  value = var.cloud_run_custom_domain != "" ? try(
    google_cloud_run_domain_mapping.api[0].status[0].resource_records,
    []
  ) : []
}

output "github_actions_wif_provider" {
  description = "Repository secret GCP_WORKLOAD_IDENTITY_PROVIDER (full resource name). Null if github_repository is empty (WIF disabled)."
  value       = one(google_iam_workload_identity_pool_provider.github[*].name)
}

output "github_actions_deployer_email" {
  description = "Repository secret GCP_SERVICE_ACCOUNT_EMAIL. Null if github_repository is empty (WIF disabled)."
  value       = one(google_service_account.github_deploy[*].email)
}

output "session_digest_job_name" {
  description = "Set GitHub Actions variable SESSION_DIGEST_JOB_NAME to this so deploy-api.yml updates the job image after each push."
  value       = local.session_digest_ready ? google_cloud_run_v2_job.session_digest[0].name : null
}

output "crash_data_bucket_name" {
  description = "Upload NYC/CA crash CSVs here under crash-sources/ before running scripts/load_crash_data.py."
  value       = var.enable_crash_data ? google_storage_bucket.crash_data[0].name : null
}

output "crash_data_bq_dataset" {
  description = "BigQuery dataset id for crash tables (matches CRASH_DATA_BQ_DATASET on Cloud Run)."
  value       = var.enable_crash_data ? google_bigquery_dataset.crash_data[0].dataset_id : null
}
