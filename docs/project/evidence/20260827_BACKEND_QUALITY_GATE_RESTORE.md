# Backend Quality Gate Restoration — 2026-08-27

## Background

The branch's backend-quality CI job invokes `scripts/verify-fast.ps1`, which was
missing from this working tree, so the job could not run locally or in CI. In
addition, three genuine non-database regressions surfaced during the no-database
full-tree rerun and had to be fixed before the gate could pass.

## Changes (all local and reversible)

1. Restored `scripts/verify-fast.ps1` (adapted from `origin/main`) with the
   focused pytest list scoped to the seven test files present on this branch:
   `test_ai_listing_taxonomy.py`, `test_agent_inference.py`,
   `test_g1_harness_contract.py`, `test_automated_commerce.py`,
   `test_browser_capture_inbox.py`, `test_supplier_rfq.py`,
   `test_supplier_rfq_dispatch.py`. The script runs Ruff, the focused pytest
   suite against an isolated `.runtime/pytest-local` basetemp, and
   `git diff --check`.
2. `tests/test_optional_provider_boundaries.py`: the provider-existence contract
   now deletes the `KJDS_OPENAI_COMPAT_*` variables in its monkeypatch preamble
   and adds an explicit case asserting that `openai_compatible` joins the
   provider set only when all four compat variables are configured. This fixes
   the environment-leakage failure where the compat provider appeared
   unconfigured.
3. `apps/control_plane/enterprise_control.py` /
   `tests/test_enterprise_control.py`: `DisasterRecoveryCheckPort.check()` and
   `RecoveryVerifier.check()` accept an optional `as_of` timestamp; observed RPO
   is computed from `as_of` instead of wall-clock `datetime.now(UTC)`. The test
   passes `as_of=NOW`, fixing the time-dependent false `BLOCKED` result.
4. `tests/test_codex_app_server_worker.py`: added
   `_link_intermediate_directory`, which prefers a directory symlink and falls
   back to a Windows junction (`_winapi.CreateJunction`) when symlink creation
   is unavailable (WinError 1314 without elevation). The intermediate-swap
   contract still validates reparse-point detection and the
   `artifact_path_not_admitted` failure code on Windows.
5. `apps/control_plane/ai_listing.py`: import order corrected for Ruff `I001`.

## Verified gate results (2026-08-27, this shell)

| Gate | Command | Result |
|---|---|---|
| Secret scan | `uv run python scripts/verify_secrets.py` | PASS — 1696 non-ignored worktree files and 1793 historical paths checked |
| Write-path validation | `uv run python scripts/validate_write_paths.py` | PASS — write-path registry and source boundaries valid |
| Whitespace diff | `git diff --check` | PASS — exit 0, line-ending warnings only, no whitespace errors |
| Fast gate end-to-end | `pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/verify-fast.ps1` | PASS — Ruff "All checks passed!", focused pytest "82 passed, 1 warning in 8.77s", `git diff --check` clean, "verify-fast PASS" |

## Web quality gate (2026-08-27, same shell)

| Gate | Command | Result |
|---|---|---|
| Web contract tests | `npm test` (web/) | PASS — 167 tests, 0 failures |
| Production build | `npm run build -- --webpack` (web/) | PASS — compiled, 73 routes generated |

Two local defects were fixed to reach this state:

1. `web/features/control-tower/control-plane.tsx`: the Agent 权限边界 policy list is now the
   explicitly typed `ActionSafetyEnvelope` constant (mirroring `journeyPolicy`), satisfying the
   plane-token contract in `web/lib/control-plane-contract.test.ts` that previously failed on
   the missing `ActionSafetyEnvelope` identifier.
2. `web/features/ui2/ui2.module.css`: the document-wide `:focus-visible` accessibility rule
   moved to the global `web/features/ui2/tokens.css` (where `--kjds-focus-ring` is defined).
   CSS Modules reject non-local element selectors, which broke the webpack production build;
   the rule's cascade position is unchanged because `tokens.css` is imported after
   `globals.css` in `app/layout.tsx`.

Sandbox note: `npm test`/`npm run build` exit codes surface as 1 in this shell only because
the agent sandbox blocks npm's debug-log writes under the external npm cache directory; the
test runner itself reports `pass 167 / fail 0` and the build reports successful compilation
with all routes emitted.

## Regression context

The earlier full-tree no-database pytest rerun observed `3660 passed / 24
failed`. The 24 failures were environment-bound — the shell's PostgreSQL
endpoints pointed at a stopped container, producing connection timeouts rather
than code regressions; database-bound suites were exercised separately against
run-owned isolated containers. After the three fixes above, the focused rerun
of the affected test files returned `182 passed` with no failures. The only
remaining pytest warning is the known Starlette/httpx deprecation notice from
the test client.

## Scope

This receipt covers the local backend quality gate only. It does not promote
any task observation into Fact, Approval, Permit, FinanceEntry, or business
truth, and it does not authorize an external write. The changes were verified
in the working tree; the CI backend-quality job can now execute the restored
`verify-fast.ps1` once these changes are committed and pushed.
