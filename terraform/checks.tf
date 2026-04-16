# Root-module checks (Terraform >= 1.5). Run on plan/apply when variables are set.

check "gha_state_bucket_valid" {
  assert {
    condition     = trimspace(var.gha_terraform_state_bucket) == "" || can(regex("^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$", trimspace(var.gha_terraform_state_bucket)))
    error_message = <<-EOT
      gha_terraform_state_bucket must be empty or a valid GCS bucket name.
      GitHub Actions should pass the same value to `terraform init -backend-config="bucket=..."`.
    EOT
  }
}
