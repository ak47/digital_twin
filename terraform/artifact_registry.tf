resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = var.artifact_registry_repository_id
  description   = "Docker images for digital_twin Cloud Run service"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}
