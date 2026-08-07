# BAS-212 G-1 lifecycle database seam Evidence

- Status: target seam verified; BAS-212 remains in progress because final G-1
  is blocked by an outbox coverage registry omission outside this exact5 slice.
- Trigger: the generic G-1 suite passed 441 tests and then failed because the
  closed-loop PostgreSQL lifecycle fixture treated the already migrated runtime
  database as its immutable 0094 management database.
- Boundary: no migration, API, OpenAPI, runtime, or product behavior changes.
- Design: the run-owned contract database is migrated to 0094; the complete
  closed-loop PostgreSQL lifecycle file runs under the global G-1 mutex before
  the primary fixed database/role lease exists and is excluded from generic
  collection. Media, Primary Source Intake, and TeamAgent consume the same
  contract database through `KJDS_G1_CONTRACT_DATABASE_URL`.
- Fail closed: the closed-loop fixture rejects execution when the generic
  contract seam is present, so an exclusion or ordering regression cannot
  silently mutate the primary G-1 runtime database.

## Current-byte proof

- PowerShell parser, Python `py_compile`, Ruff, and `git diff --check`: PASS.
- Harness and assignment contracts: `29 passed in 3.48s`.
- Run-owned PostgreSQL 17 targeted lifecycle:
  - closed-loop lifecycle: `101 passed, 12 warnings in 44.90s`;
  - TeamAgent lifecycle: `31 passed, 12 warnings in 64.54s`;
  - container, listener, basetemp, and staged residue: zero.
- Fresh G-1 repair validation at lease HEAD
  `3de0127d647b52dd7674decaf9c43f7c849d77f9`:
  - global data coverage PostgreSQL contract: `84 passed`;
  - closed-loop PostgreSQL contract: `101 passed` and result flag `true`;
  - generic contract database result flag: `true`;
  - generic suite: `2651 passed, 1 skipped, 1 failed`;
  - the only failure is
    `test_outbox_coverage_registry_matches_direct_session_transactions`, because
    the out-of-scope outbox registry does not yet list
    `closed_loop_evolution.py`;
  - process, database, role, lease, owned file, container, and port 5432 cleanup:
    zero residue.
- Control decision: freeze and feature-commit this exact five-file seam first,
  without claiming final G-1 PASS. A separate machine-CAS expansion of BAS-212
  will then own the outbox registry closure and clean-HEAD G-1 reruns before
  release.
