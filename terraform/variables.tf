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

variable "rag_corpus_resource_name" {
  description = "Full Vertex RAG corpus resource name for retrieval (empty disables RAG in the app). Example: projects/ID/locations/us-central1/ragCorpora/UUID"
  type        = string
  default     = ""
}

variable "cors_allowed_origins" {
  description = "Origins allowed by the Cloud Run API (mirrors no-ego.net site)."
  type        = list(string)
  default = [
    "https://no-ego.net",
    "https://www.no-ego.net",
  ]
}

variable "cloud_run_custom_domain" {
  description = <<-EOT
    Full hostname to map to the API service (e.g. digital-twin.no-ego.net). Empty string skips this resource.
    The registrable domain (e.g. no-ego.net) must be verified for this GCP project before apply succeeds.
    After apply, create the DNS records from output cloud_run_custom_domain_dns_records; TLS may take extra minutes.
  EOT
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

variable "rag_engine_tier" {
  description = "Vertex AI RAG managed DB tier: BASIC (cost-friendly) or SCALED (production)."
  type        = string
  default     = "BASIC"

  validation {
    condition     = contains(["BASIC", "SCALED"], var.rag_engine_tier)
    error_message = "rag_engine_tier must be BASIC or SCALED."
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
  description = "GitHub repo allowed to deploy via OIDC (owner/name). This project uses ak47/digital_twin. Set to \"\" to skip WIF + deployer SA (forks / JSON-key deploy only)."
  type        = string
  default     = "ak47/digital_twin"

  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be empty or owner/name (alphanumeric, dots, hyphens, underscores)."
  }
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
