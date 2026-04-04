# Project-level Vertex AI RAG Engine managed DB tier (prerequisite for corpora).
# Corpus/file resources are created via API/CI (gcloud or google-genai) until first-class
# Terraform resources cover your exact flow; this keeps the durable RAG plane in IaC.
#
# Docs: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/vertex_ai_rag_engine_config

resource "google_vertex_ai_rag_engine_config" "main" {
  project = var.project_id
  region  = var.region

  rag_managed_db_config {
    dynamic "basic" {
      for_each = var.rag_engine_tier == "BASIC" ? [1] : []
      content {}
    }
    dynamic "scaled" {
      for_each = var.rag_engine_tier == "SCALED" ? [1] : []
      content {}
    }
  }

  depends_on = [google_project_service.required]
}
