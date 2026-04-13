# Root-module checks (Terraform >= 1.5). Run on plan/apply when variables are set.

check "gha_state_bucket_matches_backend" {
  assert {
    condition = (
      trimspace(var.gha_terraform_state_bucket) == ""
      || (
        trimspace(local.backend_gcs_bucket) != ""
        && trimspace(var.gha_terraform_state_bucket) == trimspace(local.backend_gcs_bucket)
      )
    )
    error_message = <<-EOT
      When gha_terraform_state_bucket is set, it must exactly match the bucket = "..." value in terraform/backend.tf
      (same bucket Terraform init uses for remote state). Parsed backend bucket: "${local.backend_gcs_bucket}".
    EOT
  }
}
