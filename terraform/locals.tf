locals {
  # Used by checks.tf: keep gha_terraform_state_bucket aligned with the GCS backend bucket string.
  backend_tf_raw     = file("${path.module}/backend.tf")
  backend_gcs_bucket = try(regex("bucket\\s*=\\s*\"([^\"]+)\"", local.backend_tf_raw)[0], "")
}
