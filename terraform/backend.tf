# Shared backend settings for all environments.
# Supply bucket per environment with:
#   terraform init -backend-config="bucket=<your-state-bucket>"
terraform {
  backend "gcs" {
    prefix = "digital-twin/terraform"
  }
}
