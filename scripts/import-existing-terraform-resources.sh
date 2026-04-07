#!/usr/bin/env bash
# Import GCP objects that already exist but are missing from Terraform state (409 on apply).
# Run from repo root with credentials that can read the project. Uses the same TF_VAR_* as terraform apply.
#
#   export TF_VAR_project_id="digital-twin-492318"
#   # Optional if non-default:
#   # export TF_VAR_region="us-central1"
#   # export TF_VAR_name_prefix="digital-twin"
#   # export TF_VAR_artifact_registry_repository_id="digital-twin"
#
# Usage:
#   ./scripts/import-existing-terraform-resources.sh          # phase1 + phase2 (first-time bootstrap)
#   ./scripts/import-existing-terraform-resources.sh phase1   # AR + SAs + WIF pool only
#   ./scripts/import-existing-terraform-resources.sh phase2   # Cloud Run service + job + WIF provider (after partial apply)
#
# If an import fails with "already managed", skip that resource — it is already in state.

set -euo pipefail

PROJECT_ID="${TF_VAR_project_id:?Set TF_VAR_project_id to your GCP project id}"
REGION="${TF_VAR_region:-us-central1}"
PREFIX="${TF_VAR_name_prefix:-digital-twin}"
REPO="${TF_VAR_artifact_registry_repository_id:-digital-twin}"

cd "$(dirname "$0")/../terraform"

phase1() {
  echo "=== Phase 1: Artifact Registry, service accounts, WIF pool ==="
  terraform import google_artifact_registry_repository.docker \
    "projects/${PROJECT_ID}/locations/${REGION}/repositories/${REPO}"

  terraform import google_service_account.cloud_run_api \
    "projects/${PROJECT_ID}/serviceAccounts/${PREFIX}-api@${PROJECT_ID}.iam.gserviceaccount.com"

  terraform import 'google_service_account.github_deploy[0]' \
    "projects/${PROJECT_ID}/serviceAccounts/${PREFIX}-gha-deploy@${PROJECT_ID}.iam.gserviceaccount.com"

  terraform import 'google_service_account.scheduler_digest[0]' \
    "projects/${PROJECT_ID}/serviceAccounts/${PREFIX}-digest-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

  terraform import 'google_iam_workload_identity_pool.github[0]' \
    "projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${PREFIX}-gha-wif"
}

phase2() {
  echo "=== Phase 2: Cloud Run service, session-digest job, WIF OIDC provider ==="
  terraform import google_cloud_run_v2_service.api \
    "projects/${PROJECT_ID}/locations/${REGION}/services/${PREFIX}-api"

  terraform import 'google_cloud_run_v2_job.session_digest[0]' \
    "projects/${PROJECT_ID}/locations/${REGION}/jobs/${PREFIX}-session-digest"

  terraform import 'google_iam_workload_identity_pool_provider.github[0]' \
    "projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${PREFIX}-gha-wif/providers/github-oidc"
}

case "${1:-all}" in
  phase1) phase1 ;;
  phase2) phase2 ;;
  all)
    phase1
    phase2
    ;;
  *)
    echo "Usage: $0 [phase1|phase2|all]" >&2
    exit 1
    ;;
esac

echo "Done. Run: cd terraform && terraform plan"
