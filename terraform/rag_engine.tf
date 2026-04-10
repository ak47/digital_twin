# Project-level Vertex AI RAG Engine managed DB tier (prerequisite for corpora).
# Corpus/file resources are created via API/CI (gcloud or google-genai) until first-class
# Terraform resources cover your exact flow; this keeps the durable RAG plane in IaC.
#
# Docs: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/vertex_ai_rag_engine_config
#
# RAG corpora are regional: ingest must run in a region where this config exists.
# rag_corpus_ingest_region adds a second config (backup when var.region RAG is allowlist-blocked).

locals {
  rag_engine_regions = toset(compact(distinct([var.region, var.rag_corpus_ingest_region])))
  # HashiCorp google provider 7.x supports only Spanner tiers on this resource (basic/scaled/unprovisioned).
  # SERVERLESS is applied via UpdateRagEngineConfig in scripts/ingest_rag_corpus.py (vertexai.preview.rag).
  rag_engine_config_regions = var.rag_engine_deployment_mode == "SERVERLESS" ? toset([]) : local.rag_engine_regions
}

resource "google_vertex_ai_rag_engine_config" "main" {
  for_each = local.rag_engine_config_regions
  project  = var.project_id
  region   = each.key

  rag_managed_db_config {
    dynamic "basic" {
      for_each = var.rag_engine_deployment_mode == "SPANNER_BASIC" ? [1] : []
      content {}
    }
    dynamic "scaled" {
      for_each = var.rag_engine_deployment_mode == "SPANNER_SCALED" ? [1] : []
      content {}
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_service_identity.vertex_ai,
  ]
}

check "rag_serverless_single_region" {
  assert {
    condition = (
      var.rag_engine_deployment_mode != "SERVERLESS"
      || var.rag_corpus_ingest_region == ""
    )
    error_message = "rag_engine_deployment_mode SERVERLESS requires rag_corpus_ingest_region = \"\" (second RAG region is incompatible with Serverless in this stack)."
  }
}

