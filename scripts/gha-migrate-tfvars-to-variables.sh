#!/usr/bin/env bash
# Print `gh variable set` commands to migrate terraform/terraform.tfvars → GitHub Variables.
# Does not set secrets (GCP_*). Run from repo root. Safe to paste into a shell after review.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TFVARS="${REPO_ROOT}/terraform/terraform.tfvars"

if [ ! -f "${TFVARS}" ]; then
  echo "No ${TFVARS} — nothing to migrate." >&2
  exit 1
fi

_get_tfvar() {
  local key="$1"
  awk -v k="${key}" '
    $0 ~ "^[[:space:]]*" k "[[:space:]]*=" {
      sub(/^[^=]*=[[:space:]]*/, "")
      sub(/[[:space:]]+#.*$/, "")
      gsub(/^[[:space:]]+|[[:space:]]+$/, "")
      if ($0 ~ /^"/) { gsub(/^"|"$/, ""); print; exit }
      if ($0 ~ /^true$/) { print "true"; exit }
      if ($0 ~ /^false$/) { print "false"; exit }
      print; exit
    }
  ' "${TFVARS}"
}

_get_tfvar_list() {
  local key="$1"
  awk -v k="${key}" '
    $0 ~ "^[[:space:]]*" k "[[:space:]]*=" {
      sub(/^[^=]*=[[:space:]]*/, "")
      gsub(/^[[:space:]]*\[/, "")
      gsub(/\][[:space:]]*(#.*)?$/, "")
      gsub(/"/, "")
      gsub(/[[:space:]]+/, "")
      print; exit
    }
  ' "${TFVARS}"
}

_emit() {
  local tf_key="$1"
  local gh_name="$2"
  local val
  val="$(_get_tfvar "${tf_key}")"
  [ -z "${val}" ] && return 0
  printf 'gh variable set %s --body %q\n' "${gh_name}" "${val}"
}

echo "# Migrate terraform.tfvars → GitHub Variables (review before running)"
echo "# Docs: docs/github-actions-terraform-config.md"
echo "# Delete secret TERRAFORM_TFVARS after migration: gh secret delete TERRAFORM_TFVARS"
echo ""

_emit github_repository TF_GITHUB_REPOSITORY
_emit gha_terraform_state_bucket TF_STATE_BUCKET
_emit rag_corpus_resource_name TF_RAG_CORPUS_RESOURCE_NAME
_emit rag_engine_deployment_mode TF_RAG_ENGINE_DEPLOYMENT_MODE
_emit rag_corpus_ingest_region TF_RAG_CORPUS_INGEST_REGION
_emit gemini_model GEMINI_MODEL
_emit cloud_run_custom_domain TF_CLOUD_RUN_CUSTOM_DOMAIN
_emit alert_email TF_ALERT_EMAIL
_emit session_digest_enabled TF_SESSION_DIGEST_ENABLED
_emit session_digest_gmail_secret_id TF_SESSION_DIGEST_GMAIL_SECRET_ID
_emit session_digest_delegated_user TF_SESSION_DIGEST_DELEGATED_USER
_emit session_digest_email_to TF_SESSION_DIGEST_EMAIL_TO
_emit enable_conversation_db TF_ENABLE_CONVERSATION_DB
_emit enable_crash_data TF_ENABLE_CRASH_DATA
_emit region TF_REGION
_emit name_prefix TF_NAME_PREFIX
_emit max_output_tokens TF_MAX_OUTPUT_TOKENS

roles="$(_get_tfvar_list github_actions_terraform_roles)"
if [ -n "${roles}" ]; then
  printf 'gh variable set TF_GITHUB_ACTIONS_TERRAFORM_ROLES --body %q\n' "${roles}"
fi

cors="$(_get_tfvar_list cors_allowed_origins)"
if [ -n "${cors}" ]; then
  printf 'gh variable set CORS_ALLOWED_ORIGINS --body %q\n' "${cors}"
fi

echo ""
echo "# GCP_PROJECT_ID stays a Secret (from terraform output project_id_for_github):"
echo "#   gh secret set GCP_PROJECT_ID --body \"\$(cd terraform && terraform output -raw project_id_for_github)\""
