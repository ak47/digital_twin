locals {
  monitoring_enabled = trimspace(var.alert_email) != ""
}

resource "google_monitoring_notification_channel" "email" {
  count = local.monitoring_enabled ? 1 : 0

  project      = var.project_id
  display_name = "${var.name_prefix} alerts (email)"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [
    google_project_service.required,
  ]
}

