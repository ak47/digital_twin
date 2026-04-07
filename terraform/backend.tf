# Keep bucket name in sync with gha_terraform_state_bucket in terraform.tfvars (and TERRAFORM_TFVARS on GitHub).
# This file is tracked so `terraform init` in GitHub Actions uses the same remote state as local runs.
terraform {
  backend "gcs" {
    bucket = "ak47-digital-twin-terraform-state"
    prefix = "digital-twin/terraform"
  }
}
