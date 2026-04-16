#!/usr/bin/env bash
# After: cd terraform && terraform apply
# Prints values for GitHub → Settings → Secrets and variables → Actions.
# Requires [uv](https://docs.astral.sh/uv/) for JSON parsing (run from repo root: uv sync --extra dev).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}/terraform"

if [ -z "$(terraform state list 2>/dev/null || true)" ]; then
  echo "No Terraform state (nothing applied yet, or init/backend failed). Run:" >&2
  echo "  export TF_STATE_BUCKET='your-terraform-state-bucket'" >&2
  echo "  cd terraform && terraform init -reconfigure -backend-config=\"bucket=\${TF_STATE_BUCKET}\" && terraform plan && terraform apply" >&2
  exit 1
fi

terraform output -raw project_id_for_github >/dev/null

echo ""
echo "=== GitHub repository secrets (exact names) ==="
echo ""
echo "GCP_PROJECT_ID"
terraform output -raw project_id_for_github
echo ""
echo "GCP_WORKLOAD_IDENTITY_PROVIDER"
terraform output -raw github_actions_wif_provider
echo ""
echo "GCP_SERVICE_ACCOUNT_EMAIL"
terraform output -raw github_actions_deployer_email
echo ""
echo "TERRAFORM_TFVARS  (create as secret: full file body for terraform.yml)"
echo "  gh secret set TERRAFORM_TFVARS < terraform/terraform.tfvars"
echo ""
echo "TF_STATE_BUCKET  (create as repository variable)"
state_bucket="$(awk -F= '/^[[:space:]]*gha_terraform_state_bucket[[:space:]]*=/{v=$2} END{gsub(/["[:space:]]/, "", v); print v}' terraform.tfvars 2>/dev/null || true)"
if [ -n "${state_bucket}" ]; then
  echo "  gh variable set TF_STATE_BUCKET --body \"${state_bucket}\""
else
  echo "  gh variable set TF_STATE_BUCKET --body \"<same value as gha_terraform_state_bucket in terraform.tfvars>\""
fi
echo ""
echo "=== Ingest RAG corpus workflow (no extra GitHub Variables) ==="
echo "Bucket + RagCorpus come from terraform output (remote state)."
echo "Set in terraform.tfvars: gha_terraform_state_bucket = same value as TF_STATE_BUCKET"
echo "then terraform apply so the GitHub deploy SA can run terraform init/output in CI."
echo ""
echo "corpus_bucket_name (reference)"
terraform output -raw corpus_bucket_name
echo ""
echo "rag_corpus_resource_name (reference — must match rag_corpus_resource_name in tfvars / state)"
terraform output -raw rag_corpus_resource_name
echo ""
echo "=== Optional: idle digest job (Terraform digest_job.tf + README) ==="
digest_job=""
if dj_json="$(terraform output -json session_digest_job_name 2>/dev/null)"; then
  digest_job="$(printf '%s' "${dj_json}" | (cd "${REPO_ROOT}" && uv run python -c "import json,sys; v=json.load(sys.stdin); print('' if v is None else str(v))"))"
fi
if [ -n "${digest_job}" ]; then
  echo "GitHub Actions Variable: SESSION_DIGEST_JOB_NAME (deploy-api.yml updates this job's image)"
  echo "${digest_job}"
else
  echo "Digest job not provisioned (session_digest_enabled=false) or output missing — see README."
fi
echo ""
echo "=== Done ==="
echo ""
