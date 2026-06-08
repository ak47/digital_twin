variable "project_id" {
  description = "GCP project ID. Set via TF_VAR_project_id, terraform.tfvars (gitignored), or -var flag — never commit."
  type        = string
  sensitive   = true
}

variable "region" {
  description = "Default region for regional resources (Cloud Run, Vertex, buckets)."
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Prefix for resource names (buckets must be globally unique)."
  type        = string
  default     = "digital-twin"
}

variable "artifact_registry_repository_id" {
  description = "Artifact Registry Docker repository id (path segment in docker.pkg.dev URLs). GCP allows only lowercase letters, digits, and hyphens (no underscores). Cloud Run service name stays name_prefix-api."
  type        = string
  default     = "digital-twin"
}

variable "container_image" {
  description = "Cloud Run container image (Artifact Registry after first build, or placeholder for bootstrap)."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "gemini_model" {
  description = "Vertex AI Gemini model id passed to Cloud Run as GEMINI_MODEL (see GCP model versions doc)."
  type        = string
  default     = "gemini-2.5-flash"
}

variable "max_output_tokens" {
  description = "Hard cap for model output length (MAX_OUTPUT_TOKENS). Lower values reduce verbosity."
  type        = number
  default     = 1024
}

variable "rag_corpus_resource_name" {
  description = "Full Vertex RAG corpus resource name for retrieval (empty disables RAG in the app). Example: projects/ID/locations/us-central1/ragCorpora/UUID"
  type        = string
  default     = ""
}

variable "cors_allowed_origins" {
  description = <<-EOT
    Origins allowed by the Cloud Run API (browser CORS). Required — no default — so applies never silently use example.com.
    Must match what you pass as CORS_ALLOWED_ORIGINS on deploy (e.g. GitHub Actions Variable). Include every real frontend origin.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.cors_allowed_origins) > 0
    error_message = "cors_allowed_origins must contain at least one origin."
  }

  validation {
    condition     = alltrue([for o in var.cors_allowed_origins : length(trimspace(o)) > 0])
    error_message = "Each cors_allowed_origins entry must be a non-empty string."
  }
}

variable "cloud_run_custom_domain" {
  description = <<-EOT
    Full hostname to map to the API service (e.g. api.example.com). Empty string skips this resource.
    The registrable domain (e.g. example.com) must be verified for this GCP project before apply succeeds.
    After apply, create the DNS records from output cloud_run_custom_domain_dns_records; TLS may take extra minutes.
  EOT
  type        = string
  default     = ""
}

variable "alert_email" {
  description = "Email address for Cloud Monitoring alert notifications (pass via TERRAFORM_TFVARS / TF_VAR_alert_email). Empty disables monitoring resources."
  type        = string
  default     = ""
}

variable "session_retention_days" {
  description = "GCS lifecycle: delete session JSON objects after N days."
  type        = number
  default     = 3
}

variable "bucket_force_destroy" {
  description = "If true, Terraform may delete corpus and sessions buckets even when non-empty. Use only for teardown or project moves; risky for the corpus bucket (curated data)."
  type        = bool
  default     = false
}

variable "rag_engine_deployment_mode" {
  description = <<-EOT
    Vertex AI RAG Engine deployment mode for regional google_vertex_ai_rag_engine_config resources.
    SPANNER_BASIC / SPANNER_SCALED provision dedicated Spanner (Terraform-managed). SERVERLESS omits
    that resource entirely — switch the region to Serverless via Console or scripts/ingest_rag_corpus.py
    (UpdateRagEngineConfig); Serverless is documented as us-central1-only (preview). Use with
    rag_corpus_ingest_region = "" unless all RAG lives in var.region.
  EOT
  type        = string
  default     = "SPANNER_BASIC"

  validation {
    condition     = contains(["SPANNER_BASIC", "SPANNER_SCALED", "SERVERLESS"], var.rag_engine_deployment_mode)
    error_message = "rag_engine_deployment_mode must be SPANNER_BASIC, SPANNER_SCALED, or SERVERLESS."
  }
}

variable "rag_corpus_ingest_region" {
  description = <<-EOT
    Second Vertex region for RAG Engine managed DB when ingest cannot use var.region (e.g. us-central1
    RAG allowlist). Typical backup: europe-west4 — set this, terraform apply, then run ingest with
    --region matching this value. Default "" = RAG Engine only in var.region.
  EOT
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "GitHub repo allowed to deploy via OIDC (owner/name). Set to your fork (e.g. my-org/digital_twin) or \"\" to skip WIF + deployer SA (JSON-key deploy only)."
  type        = string
  default     = ""

  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be empty or owner/name (alphanumeric, dots, hyphens, underscores)."
  }
}

variable "gha_terraform_state_bucket" {
  description = <<-EOT
    GCS bucket used for Terraform remote state (`terraform init -backend-config="bucket=..."`). When non-empty and GitHub WIF is enabled,
    grants the GitHub deploy SA storage access for terraform init. Use roles/storage.objectViewer when
    github_actions_terraform_roles is empty (ingest + plan read-only); objectAdmin when non-empty (apply writes state).
  EOT
  type        = string
  default     = ""
}

variable "github_actions_terraform_roles" {
  description = <<-EOT
    Extra project IAM roles for the GitHub deploy SA so .github/workflows/terraform.yml can run terraform apply.
    Typical for a dedicated GCP project: ["roles/editor", "roles/resourcemanager.projectIamAdmin"].
    Leave empty (default) if you only run terraform from your laptop — ingest still works with gha_terraform_state_bucket + viewer.
    Bootstrap: add these roles and apply once locally before the first successful GHA apply.
  EOT
  type        = list(string)
  default     = []
}

variable "session_digest_enabled" {
  description = "Provision Cloud Run Job + Cloud Scheduler for idle session transcript emails (GCS + Gmail)."
  type        = bool
  default     = false
}

variable "session_digest_gmail_secret_id" {
  description = "Secret Manager secret id (short name, not project number) holding the Gmail service account JSON key."
  type        = string
  default     = ""
  sensitive   = true
}

variable "session_digest_delegated_user" {
  description = "Workspace user to impersonate when sending mail (GMAIL_DELEGATED_USER)."
  type        = string
  default     = ""
}

variable "session_digest_email_to" {
  description = "Comma-separated digest recipients (RESUME_BOT_DIGEST_EMAIL_TO)."
  type        = string
  default     = ""
}

variable "session_digest_schedule" {
  description = "Cloud Scheduler cron (interpreted in session_digest_scheduler_timezone)."
  type        = string
  default     = "*/15 * * * *"
}

variable "session_digest_scheduler_timezone" {
  description = "IANA timezone for the scheduler cron (e.g. America/Los_Angeles or Etc/UTC)."
  type        = string
  default     = "Etc/UTC"
}

variable "session_digest_idle_minutes" {
  description = "RESUME_BOT_DIGEST_IDLE_MINUTES — idle window before emailing a session."
  type        = number
  default     = 60
}

variable "session_digest_display_timezone" {
  description = "RESUME_BOT_DIGEST_TIMEZONE — IANA tz for email subject / attachment timestamps."
  type        = string
  default     = "America/Los_Angeles"
}

variable "enable_crash_data" {
  description = "Provision GCS bucket + BigQuery dataset for NYC/CA motor vehicle crash CSVs (digital-twin SQL tool)."
  type        = bool
  default     = true
}

variable "crash_data_bq_dataset" {
  description = "BigQuery dataset id for crash tables (Cloud Run CRASH_DATA_BQ_DATASET)."
  type        = string
  default     = "vehicle_crashes"
}
