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

variable "container_image" {
  description = "Cloud Run container image (Artifact Registry after first build, or placeholder for bootstrap)."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
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
