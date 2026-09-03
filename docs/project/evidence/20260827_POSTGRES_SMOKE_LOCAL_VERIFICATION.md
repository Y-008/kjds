# Postgres-Smoke CI Job Local Verification — 2026-08-27

## Background

The `postgres-smoke` CI job (`.github/workflows/ci.yml`) could not previously be
verified end-to-end locally: the earlier bootstrap attempt lost its run token
across session restarts, WSL interop hung during `alembic upgrade`, and the
remaining steps (`grant-runtime`, both pytest suites, the API readiness probe)
had not yet executed. This receipt records the completed local verification of
every step in the job, run against a run-owned disposable PostgreSQL container.

## Environment

- Container: `kjds-full-regression-pg-20260827` (postgres 17, `127.0.0.1:55434`),
  isolated from the stopped `hermes` container referenced by the developer `.env`.
- Secrets: generated once and persisted under `.runtime/g1-smoke-secrets.json`
  (gitignored), loaded per-command by dot-sourcing `.runtime/g1-smoke-env.ps1`.
  The loader mirrors every variable exported by `scripts/ci-postgres-bootstrap.sh`
  (`KJDS_DATABASE_URL`, the seven authority/runtime URLs, the run token and its
  SHA-256, `KJDS_REPOSITORY=postgres`, `KJDS_DATABASE_PROVIDER=local-postgres`,
  `KJDS_SHADOW_MODE=true`, `KJDS_LIMITED_EXECUTION_ENABLED=false`,
  `KJDS_STRATEGIC_BENCHMARK_SEALING_KEY`, `KJDS_API_KEY=ci-test-key`).

## Local-environment divergence and fix

The first API-suite attempt failed at collection with
`RuntimeError: KJDS_API_KEY must appear in KJDS_API_KEYS_JSON when multi-identity
mode is used`. Root cause: `apps/control_plane/database.py` calls
`load_dotenv()` at import time (override=False). On a developer machine the
local `.env` injects `KJDS_API_KEYS_JSON` (a multi-identity map) into the pytest
process while the loader's `KJDS_API_KEY=ci-test-key` survives, and the two are
inconsistent. CI has no `.env` file, so the job itself is unaffected — this was
a local-only divergence. The loader now pre-sets `KJDS_API_KEYS_JSON=""`;
`load_dotenv(override=False)` keeps the empty value, and the authenticator runs
in single-identity mode exactly as in CI. A temporary debug print in
`security.py` and a scratch test file were used to isolate this and were both
removed; no production code changed.

## Verified job steps (2026-08-27, in order)

| CI step | Local command | Result |
|---|---|---|
| Verify one migration head | `uv run python -m alembic heads` | PASS — single head `20260820_0103 (head)` |
| Bootstrap disposable G-1 resources | contract DB create + `alembic upgrade 20260803_0094`, then `manage_g1_database.py recover` → `acquire` → `recreate` | PASS — stale lease/roles from the interrupted earlier run recovered, new lease acquired, 10 roles + `kjds_g1_smoke` recreated |
| Apply all migrations | `uv run python -m alembic upgrade head` | PASS — all 103 migrations through `20260820_0103` |
| Grant runtime | `uv run python scripts/manage_g1_database.py grant-runtime` | PASS — lease state and owned resources verified |
| Media connector PostgreSQL contracts | `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-media-connectors-postgres tests/test_media_connectors_postgres.py` | PASS — 6 passed in 1.36s |
| PostgreSQL API contract suites | `uv run pytest ... tests/test_api_contract.py test_catalog_read_run_handoff.py test_channel_accounts_api.py test_intelligence_ingestion.py test_native_parity_acceptance_api.py test_scoped_batch_opportunity.py test_scoped_marketplace_catalog.py test_scoped_read_only_pilots.py` | PASS — 128 passed in 4.88s (8 files) |
| Verify API readiness | `uv run python -m uvicorn apps.control_plane.api:app --host 127.0.0.1 --port 8000`, then poll `GET /health/ready` (30×1s) | PASS — first attempt HTTP 200: `status: ok`, `database: ok`, `api_identity_configured: true`, write safety not engaged; server stopped after the probe |

## Scope

This receipt covers the local verification of the `postgres-smoke` CI job only.
It promotes no task observation into Fact, Approval, Permit, FinanceEntry, or
business truth, and it authorizes no external write. The disposable container
and its run-scoped roles/lease remain in place for further local runs; they hold
no production data.
