terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.12.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.12.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0"
    }
  }

  # Remote state: copy backend.hcl.example → backend.hcl (gitignored), then:
  #   terraform init -backend-config=backend.hcl -migrate-state
  # Local state without backend.hcl: terraform init -backend=false
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}
