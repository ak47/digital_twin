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
echo "=== Optional: idle digest email (see README) ==="
echo "Gmail digest: Variables RESUME_BOT_DIGEST_EMAIL_TO, GMAIL_DELEGATED_USER, GMAIL_SECRET_NAME (GCP Secret Manager id)"
echo ""
echo "=== Done ==="
echo ""
