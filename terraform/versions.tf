terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.12.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0"
    }
  }

  # Remote state: uncomment after creating a state bucket (see README).
  # backend "gcs" {
  #   bucket = "YOUR_TF_STATE_BUCKET"
  #   prefix = "digital-twin/terraform"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
