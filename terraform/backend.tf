# Keep bucket name in sync with gha_terraform_state_bucket in terraform.tfvars (plan checks this; see checks.tf).
# This file is tracked so `terraform init` in GitHub Actions uses the same remote state as local runs.
terraform {
  backend "gcs" {
    bucket = "YOUR_UNIQUE_TF_STATE_BUCKET"
    prefix = "digital-twin/terraform"
  }
}
