#!/usr/bin/env bash
set -euo pipefail

host="${KJDS_CI_POSTGRES_HOST:-127.0.0.1}"
port="${KJDS_CI_POSTGRES_PORT:-5432}"
user="${KJDS_CI_POSTGRES_USER:-hermes}"
password="${KJDS_CI_POSTGRES_PASSWORD:-hermes_dev}"
database="${KJDS_CI_POSTGRES_DATABASE:-kjds_g1_smoke}"
base_url="postgresql+psycopg://${user}:${password}@${host}:${port}"

set_var() {
  local name="$1"
  local value="$2"
  export "${name}=${value}"
  if [[ -n "${GITHUB_ENV:-}" ]]; then
    printf '%s=%s\n' "${name}" "${value}" >> "${GITHUB_ENV}"
  fi
}

run_token="$(openssl rand -hex 32)"
coverage_issuer_password="$(openssl rand -hex 32)"
runtime_password="$(openssl rand -hex 32)"
cloe_issuer_password="$(openssl rand -hex 32)"
cloe_experiment_password="$(openssl rand -hex 32)"
cloe_cost_password="$(openssl rand -hex 32)"
cloe_outcome_password="$(openssl rand -hex 32)"
cloe_review_password="$(openssl rand -hex 32)"
contract_token_sha256="$(printf '%s' "${run_token}" | sha256sum | awk '{print $1}')"
contract_database="kjds_g1_contract_${contract_token_sha256:0:24}"

set_var KJDS_DATABASE_URL "${base_url}/${database}"
set_var KJDS_G1_ADMIN_DATABASE_URL "${base_url}/postgres"
set_var KJDS_G1_RUN_TOKEN_SHA256 "${contract_token_sha256}"
set_var KJDS_G1_CONTRACT_DATABASE_NAME "${contract_database}"
set_var KJDS_G1_CONTRACT_DATABASE_URL "${base_url}/${contract_database}"
set_var KJDS_RUNTIME_DATABASE_URL "postgresql+psycopg://kjds_g1_runtime:${runtime_password}@${host}:${port}/${database}"
set_var KJDS_GLOBAL_DATA_COVERAGE_ISSUER_DATABASE_URL "postgresql+psycopg://kjds_gdc_issuance_runtime:${coverage_issuer_password}@${host}:${port}/${database}"
set_var KJDS_CLOSED_LOOP_ISSUER_DATABASE_URL "postgresql+psycopg://kjds_cloe_issuance_runtime:${cloe_issuer_password}@${host}:${port}/${database}"
set_var KJDS_CLOSED_LOOP_EXPERIMENT_AUTHORITY_DATABASE_URL "postgresql+psycopg://kjds_cloe_experiment_authority:${cloe_experiment_password}@${host}:${port}/${database}"
set_var KJDS_CLOSED_LOOP_COST_AUTHORITY_DATABASE_URL "postgresql+psycopg://kjds_cloe_cost_authority:${cloe_cost_password}@${host}:${port}/${database}"
set_var KJDS_CLOSED_LOOP_OUTCOME_AUTHORITY_DATABASE_URL "postgresql+psycopg://kjds_cloe_outcome_authority:${cloe_outcome_password}@${host}:${port}/${database}"
set_var KJDS_CLOSED_LOOP_REVIEW_AUTHORITY_DATABASE_URL "postgresql+psycopg://kjds_cloe_review_authority:${cloe_review_password}@${host}:${port}/${database}"

set_var KJDS_G1_RUN_TOKEN "${run_token}"
set_var KJDS_G1_COVERAGE_ISSUER_PASSWORD "${coverage_issuer_password}"
set_var KJDS_G1_RUNTIME_PASSWORD "${runtime_password}"
set_var KJDS_G1_CLOE_ISSUER_PASSWORD "${cloe_issuer_password}"
set_var KJDS_G1_CLOE_EXPERIMENT_PASSWORD "${cloe_experiment_password}"
set_var KJDS_G1_CLOE_COST_PASSWORD "${cloe_cost_password}"
set_var KJDS_G1_CLOE_OUTCOME_PASSWORD "${cloe_outcome_password}"
set_var KJDS_G1_CLOE_REVIEW_PASSWORD "${cloe_review_password}"

set_var KJDS_REPOSITORY postgres
set_var KJDS_DATABASE_PROVIDER local-postgres
set_var KJDS_SHADOW_MODE true
set_var KJDS_LIMITED_EXECUTION_ENABLED false
set_var KJDS_STRATEGIC_BENCHMARK_SEALING_KEY "ci-strategic-benchmark-sealing-key-0123456789"
set_var KJDS_API_KEY "ci-test-key"

uv run python scripts/manage_g1_contract_database.py create
export KJDS_DATABASE_URL="${base_url}/${contract_database}"
uv run python -m alembic upgrade 20260803_0094
export KJDS_DATABASE_URL="${base_url}/${database}"

uv run python scripts/manage_g1_database.py recover
uv run python scripts/manage_g1_database.py acquire
uv run python scripts/manage_g1_database.py recreate
