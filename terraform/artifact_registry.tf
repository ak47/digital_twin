resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = var.artifact_registry_repository_id
  description   = "Docker images for digital_twin Cloud Run service"
  format        = "DOCKER"

  # Every deploy pushes a uniquely SHA-tagged image and none are ever
  # superseded by a reused tag, so without cleanup the repo grows forever.
  cleanup_policy_dry_run = false

  # Always keep the most recent 10 tagged images regardless of age, as a
  # safety net (covers rollbacks and the image currently ignored by
  # cloud_run.tf / digest_job.tf's lifecycle.ignore_changes).
  cleanup_policies {
    id     = "keep-recent-tagged"
    action = "KEEP"

    most_recent_versions {
      keep_count = 10
    }
  }

  # Beyond that safety net, delete tagged images older than 30 days.
  cleanup_policies {
    id     = "delete-old-tagged"
    action = "DELETE"

    condition {
      tag_state  = "TAGGED"
      older_than = "2592000s" # 30 days
    }
  }

  # Untagged manifests (build cache/layer leftovers) older than 7 days.
  cleanup_policies {
    id     = "delete-old-untagged"
    action = "DELETE"

    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s" # 7 days
    }
  }

  depends_on = [google_project_service.required]
}
