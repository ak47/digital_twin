#!/usr/bin/env bash
# After: cd terraform && terraform apply
# Prints values for GitHub → Settings → Secrets and variables → Actions.
set -euo pipefail
cd "$(dirname "$0")/../terraform"

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
echo "=== Optional: idle digest job (Terraform digest_job.tf + README) ==="
digest_job=""
if dj_json="$(terraform output -json session_digest_job_name 2>/dev/null)"; then
  digest_job="$(printf '%s' "${dj_json}" | python3 -c "import json,sys; v=json.load(sys.stdin); print('' if v is None else str(v))")"
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
