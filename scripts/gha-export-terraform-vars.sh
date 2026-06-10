#!/usr/bin/env bash
# Export TF_VAR_* from individual GitHub Actions Variables / Secrets for terraform plan|apply.
# Never reads TERRAFORM_TFVARS. Logs a redacted config summary (visible in workflow logs).
#
# Required (repository):
#   Secrets:  GCP_PROJECT_ID, GCP_WORKLOAD_IDENTITY_PROVIDER, GCP_SERVICE_ACCOUNT_EMAIL
#   Variables: CORS_ALLOWED_ORIGINS, TF_STATE_BUCKET, TF_GITHUB_REPOSITORY
#
# Optional Terraform variables: TF_* prefixed repository Variables (see docs/github-actions-terraform-config.md).
#
# Local dev: use terraform/terraform.tfvars or export TF_VAR_* yourself — this script is for CI.
set -euo pipefail

_missing=""

_require() {
  local name="$1"
  local value="${2:-}"
  if [ -z "${value}" ]; then
    _missing="${_missing} ${name}"
  fi
}

_comma_to_json_list() {
  local raw="${1:-}"
  python3 - <<'PY' "${raw}"
import json, sys
raw = sys.argv[1] if len(sys.argv) > 1 else ""
items = [p.strip() for p in raw.split(",") if p.strip()]
print(json.dumps(items))
PY
}

_bool_tf() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1 | true | yes | on) echo "true" ;;
    0 | false | no | off | "") echo "false" ;;
    *) echo "false" ;;
  esac
}

_set_if_nonempty() {
  local tf_name="$1"
  local value="${2:-}"
  if [ -n "${value}" ]; then
    printf -v "TF_VAR_${tf_name}" '%s' "${value}"
    export "TF_VAR_${tf_name}"
  fi
}

# --- Required inputs (shared with Deploy API where noted) ---
_require "GCP_PROJECT_ID (secret)" "${GCP_PROJECT_ID:-}"
_require "CORS_ALLOWED_ORIGINS (variable)" "${CORS_ALLOWED_ORIGINS:-}"
_require "TF_STATE_BUCKET (variable)" "${TF_STATE_BUCKET:-}"
_require "TF_GITHUB_REPOSITORY (variable)" "${TF_GITHUB_REPOSITORY:-}"

if [ -n "${_missing}" ]; then
  echo "::error::Missing required GitHub configuration:${_missing}" >&2
  echo "See docs/github-actions-terraform-config.md" >&2
  exit 1
fi

export TF_VAR_project_id="${GCP_PROJECT_ID}"
export TF_VAR_github_repository="${TF_GITHUB_REPOSITORY}"
export TF_VAR_gha_terraform_state_bucket="${TF_STATE_BUCKET}"
export TF_VAR_cors_allowed_origins="$(_comma_to_json_list "${CORS_ALLOWED_ORIGINS}")"

# --- Optional: booleans ---
if [ -n "${TF_ENABLE_CONVERSATION_DB:-}" ]; then
  export TF_VAR_enable_conversation_db="$(_bool_tf "${TF_ENABLE_CONVERSATION_DB}")"
fi
if [ -n "${TF_SESSION_DIGEST_ENABLED:-}" ]; then
  export TF_VAR_session_digest_enabled="$(_bool_tf "${TF_SESSION_DIGEST_ENABLED}")"
fi
if [ -n "${TF_ENABLE_CRASH_DATA:-}" ]; then
  export TF_VAR_enable_crash_data="$(_bool_tf "${TF_ENABLE_CRASH_DATA}")"
fi
if [ -n "${TF_BUCKET_FORCE_DESTROY:-}" ]; then
  export TF_VAR_bucket_force_destroy="$(_bool_tf "${TF_BUCKET_FORCE_DESTROY}")"
fi

# --- Optional: strings (empty = omit, Terraform default applies) ---
_set_if_nonempty "region" "${TF_REGION:-}"
_set_if_nonempty "name_prefix" "${TF_NAME_PREFIX:-}"
_set_if_nonempty "rag_corpus_resource_name" "${TF_RAG_CORPUS_RESOURCE_NAME:-}"
_set_if_nonempty "rag_engine_deployment_mode" "${TF_RAG_ENGINE_DEPLOYMENT_MODE:-}"
_set_if_nonempty "rag_corpus_ingest_region" "${TF_RAG_CORPUS_INGEST_REGION:-}"
_set_if_nonempty "cloud_run_custom_domain" "${TF_CLOUD_RUN_CUSTOM_DOMAIN:-}"
_set_if_nonempty "alert_email" "${TF_ALERT_EMAIL:-}"
_set_if_nonempty "session_digest_gmail_secret_id" "${TF_SESSION_DIGEST_GMAIL_SECRET_ID:-}"
_set_if_nonempty "session_digest_delegated_user" "${TF_SESSION_DIGEST_DELEGATED_USER:-}"
_set_if_nonempty "session_digest_email_to" "${TF_SESSION_DIGEST_EMAIL_TO:-}"
_set_if_nonempty "session_digest_schedule" "${TF_SESSION_DIGEST_SCHEDULE:-}"
_set_if_nonempty "session_digest_scheduler_timezone" "${TF_SESSION_DIGEST_SCHEDULER_TIMEZONE:-}"
_set_if_nonempty "session_digest_display_timezone" "${TF_SESSION_DIGEST_DISPLAY_TIMEZONE:-}"
_set_if_nonempty "google_oauth_client_id" "${TF_GOOGLE_OAUTH_CLIENT_ID:-}"
_set_if_nonempty "google_oauth_client_secret_id" "${TF_GOOGLE_OAUTH_CLIENT_SECRET_ID:-}"
_set_if_nonempty "admin_session_secret_id" "${TF_ADMIN_SESSION_SECRET_ID:-}"
_set_if_nonempty "admin_oauth_redirect_uri" "${TF_ADMIN_OAUTH_REDIRECT_URI:-}"
_set_if_nonempty "admin_ui_redirect_url" "${TF_ADMIN_UI_REDIRECT_URL:-}"
_set_if_nonempty "escalation_email_to" "${TF_ESCALATION_EMAIL_TO:-}"
_set_if_nonempty "conversation_db_tier" "${TF_CONVERSATION_DB_TIER:-}"
_set_if_nonempty "conversation_db_name" "${TF_CONVERSATION_DB_NAME:-}"
_set_if_nonempty "conversation_db_user" "${TF_CONVERSATION_DB_USER:-}"
_set_if_nonempty "conversation_db_password_secret_id" "${TF_CONVERSATION_DB_PASSWORD_SECRET_ID:-}"
_set_if_nonempty "conversation_database_url_secret_id" "${TF_CONVERSATION_DATABASE_URL_SECRET_ID:-}"
_set_if_nonempty "crash_data_bq_dataset" "${TF_CRASH_DATA_BQ_DATASET:-}"

# Gemini: TF_GEMINI_MODEL overrides; else reuse Deploy API GEMINI_MODEL variable
if [ -n "${TF_GEMINI_MODEL:-}" ]; then
  export TF_VAR_gemini_model="${TF_GEMINI_MODEL}"
elif [ -n "${GEMINI_MODEL:-}" ]; then
  export TF_VAR_gemini_model="${GEMINI_MODEL}"
fi
_set_if_nonempty "max_output_tokens" "${TF_MAX_OUTPUT_TOKENS:-}"

# Lists (comma-separated GitHub Variables → JSON arrays for Terraform)
if [ -n "${TF_ADMIN_ALLOWED_EMAILS:-}" ]; then
  export TF_VAR_admin_allowed_emails="$(_comma_to_json_list "${TF_ADMIN_ALLOWED_EMAILS}")"
fi
if [ -n "${TF_GITHUB_ACTIONS_TERRAFORM_ROLES:-}" ]; then
  export TF_VAR_github_actions_terraform_roles="$(_comma_to_json_list "${TF_GITHUB_ACTIONS_TERRAFORM_ROLES}")"
fi

# --- Audit log: non-sensitive values only (safe in GHA logs) ---
echo "=== Terraform inputs (from GitHub Variables / Secrets) ==="
echo "project_id=(set, redacted)"
echo "github_repository=${TF_VAR_github_repository}"
echo "gha_terraform_state_bucket=${TF_VAR_gha_terraform_state_bucket}"
echo "cors_allowed_origins=${TF_VAR_cors_allowed_origins}"
[ -n "${TF_VAR_region:-}" ] && echo "region=${TF_VAR_region}"
[ -n "${TF_VAR_rag_corpus_resource_name:-}" ] && echo "rag_corpus_resource_name=${TF_VAR_rag_corpus_resource_name}"
[ -n "${TF_VAR_rag_engine_deployment_mode:-}" ] && echo "rag_engine_deployment_mode=${TF_VAR_rag_engine_deployment_mode}"
[ -n "${TF_VAR_rag_corpus_ingest_region:-}" ] && echo "rag_corpus_ingest_region=${TF_VAR_rag_corpus_ingest_region}"
[ -n "${TF_VAR_gemini_model:-}" ] && echo "gemini_model=${TF_VAR_gemini_model}"
[ -n "${TF_VAR_cloud_run_custom_domain:-}" ] && echo "cloud_run_custom_domain=${TF_VAR_cloud_run_custom_domain}"
[ -n "${TF_VAR_alert_email:-}" ] && echo "alert_email=${TF_VAR_alert_email}"
[ -n "${TF_VAR_session_digest_enabled:-}" ] && echo "session_digest_enabled=${TF_VAR_session_digest_enabled}"
[ -n "${TF_VAR_session_digest_delegated_user:-}" ] && echo "session_digest_delegated_user=${TF_VAR_session_digest_delegated_user}"
[ -n "${TF_VAR_session_digest_email_to:-}" ] && echo "session_digest_email_to=${TF_VAR_session_digest_email_to}"
[ -n "${TF_VAR_session_digest_gmail_secret_id:-}" ] && echo "session_digest_gmail_secret_id=${TF_VAR_session_digest_gmail_secret_id}"
[ -n "${TF_VAR_enable_conversation_db:-}" ] && echo "enable_conversation_db=${TF_VAR_enable_conversation_db}"
[ -n "${TF_VAR_enable_crash_data:-}" ] && echo "enable_crash_data=${TF_VAR_enable_crash_data}"
[ -n "${TF_VAR_github_actions_terraform_roles:-}" ] && echo "github_actions_terraform_roles=${TF_VAR_github_actions_terraform_roles}"
[ -n "${TF_VAR_admin_allowed_emails:-}" ] && echo "admin_allowed_emails=${TF_VAR_admin_allowed_emails}"
echo "=== End Terraform inputs ==="

# Persist TF_VAR_* for subsequent workflow steps (export alone does not survive step boundaries).
if [ -n "${GITHUB_ENV:-}" ]; then
  while IFS= read -r line; do
    [ -n "${line}" ] && echo "${line}" >> "${GITHUB_ENV}"
  done < <(env | grep '^TF_VAR_' || true)
fi
