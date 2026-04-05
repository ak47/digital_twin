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

variable "cors_allowed_origins" {
  description = "Origins allowed by the Cloud Run API (mirrors no-ego.net site)."
  type        = list(string)
  default = [
    "https://no-ego.net",
    "https://www.no-ego.net",
  ]
}

variable "session_retention_days" {
  description = "GCS lifecycle: delete session JSON objects after N days."
  type        = number
  default     = 3
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

variable "github_repository" {
  description = "GitHub repo allowed to deploy via OIDC (owner/name), e.g. ak47/digital_twin. Empty skips WIF + deployer SA (use manual secrets)."
  type        = string
  default     = ""

  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be empty or owner/name (alphanumeric, dots, hyphens, underscores)."
  }
}
