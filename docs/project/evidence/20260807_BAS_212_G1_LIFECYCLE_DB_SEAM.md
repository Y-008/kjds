# BAS-212 G-1 lifecycle database seam Evidence

- Status: target seam and Outbox registry alignment verified; final clean-HEAD
  G-1 must run after the alignment feature commit before BAS-212 release.
- Trigger: the generic G-1 suite passed 441 tests and then failed because the
  closed-loop PostgreSQL lifecycle fixture treated the already migrated runtime
  database as its immutable 0094 management database.
- Boundary: no migration, API, OpenAPI, runtime, or product behavior changes;
  the only follow-up is release-governance registry coverage and its test.
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
- Outbox registry, harness, and assignment contracts after the formal scope
  expansion: `30 passed in 3.10s`; JSON, Ruff, and diff checks PASS.
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
- Exact5 feature commit:
  `b0d3c881b6826bf17d42b7c3d954527308103220`.
- Machine-CAS expansion commit:
  `d7c3b4799bd1d75ee0c38db7c5737ccac06e4d38`.
- `closed_loop_evolution.py` now has one `internal_only` registry entry with
  delivery contract
  `append_only_exact_scope_closed_loop_outcome_and_evidence_ledger`; its
  rationale freezes `outbox=0`, `external_write=false`, and no Approval,
  Permit, or external action. The activation trigger is a future independently
  approved cross-process consumer or external execution orchestrator.
- This Evidence does not claim final G-1 PASS. The alignment commit must remain
  atomic, then the unique control process must run fresh G-1 on that clean HEAD.
