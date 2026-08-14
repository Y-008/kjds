# BAS-220 G1 Closed-loop Currentness Evidence

## Scope

- Base control commit: `a26f63013e0412584b7ff3bbee89664c1b44a54b`.
- Functional write set is exactly:
  - `tests/test_closed_loop_evolution_postgres.py`
  - this Evidence file.
- No migration, application, G1 harness, runtime, API, OpenAPI, Web, dependency,
  production configuration, external-write, or private `.runtime` input changed.

## Failure Reproduction

The fresh G1 run at BAS-186 release `0aad59bfe4187f1fcc6e76c2c2199338ef0f645a`
failed in the module-scoped `postgres_gate` fixture. The fixture upgraded its
disposable database with the moving target `head` and therefore reached
`20260809_0098`, while its 0096 ACL downgrade-failure checks correctly expected
the failed transaction to conserve the starting revision `20260805_0096`.
That mismatch produced one fixture assertion and 101 dependent setup errors.

This was a test-currentness defect. It was not a 0098 migration failure and did
not justify changing or weakening the 0096, 0097, or 0098 migration contracts.

## Closure

- The module freezes `CLOSED_LOOP_REVISION = "20260805_0096"`.
- All six closed-loop fixture/replay upgrades target that explicit revision,
  rather than the moving global `head`.
- Existing 0095 to 0096 to 0095 to 0096 replay, ACL baseline restoration,
  preflight rejection, populated downgrade rejection, role/receipt integrity,
  and catalog conservation assertions remain active.
- The repository's global head remains a separate moving concern verified by the
  G1 migration replay. The 0096 contract suite deliberately does not pin or
  assert any later global head.

## Verification

Run in the dedicated `kjdsbas220targeted` Compose project and disposable
PostgreSQL volume on 2026-08-14 (Asia/Shanghai):

- A fresh contract database was migrated to management revision
  `20260803_0094`.
- The complete closed-loop PostgreSQL lifecycle contract passed:
  `101 passed, 12 warnings in 74.50s`.
- The warnings are existing SQLAlchemy `Column.copy()` deprecations in migration
  `20260728_0067`; no assertion or cleanup failed.
- The fixture removed `kjds_g1_smoke` and all ten fixed G1/GDC/CLOE roles.
- The contract database, isolated container, network, and volume were then
  deleted. The pre-existing development PostgreSQL container returned healthy
  at its unchanged revision `20260803_0094`.
- Targeted Ruff, test collection, secret scan across 1,457 non-ignored files and
  1,586 historical paths, and `git diff --check` passed.
- Full-repository Ruff, secret scan, and `git diff --check` passed again after
  the targeted database run. The ordinary full Pytest suite did not complete
  within the 604.1-second command limit, so it is recorded as `INCOMPLETE`, not
  PASS or FAIL; its remaining process tree was explicitly stopped.

Two full-G1 attempts against the pre-existing development Compose project were
correctly rejected before BAS-220 verification because that development
database is at revision `20260803_0094` while retaining the two GDC principals
and their minimum Evidence ACLs required by the later 0095 contract. The G1
recovery seam classified them as unowned fixed roles and refused destructive
cleanup. A subsequent full-G1 attempt in a clean isolated project stopped in
the earlier global-data-coverage PostgreSQL contract and never entered the
closed-loop contract. These are separate G1 environment/GDC findings; they do
not invalidate the independently clean 101-test BAS-220 result.

The prior fresh G1 run at the BAS-186 release continued past the closed-loop
contract but ended in the generic suite:

`21 failed, 3168 passed, 76 skipped`. Those remaining failures are outside this
exact write set and fall into four pre-existing/current integration groups:

1. commercial-lifecycle entitlement expectation drift;
2. outbox coverage missing `media_jobs.py`;
3. research-inbox capture timestamp/lock-contract drift;
4. write-path registry missing `marketplace_research_mcp.py`.

Therefore BAS-220 closes the closed-loop 0096/current-head defect only. It does
not claim that the remaining generic-suite failures are closed or that the full
G1 is green; those integration findings require a separately governed task and
commit topology.

## Cleanup

- The run-owned Compose container, network, and volume were deleted.
- Targeted G1 roles and the `kjds_g1_smoke` database were absent before teardown.
- The pre-existing default PostgreSQL container was restarted and returned
  `healthy` at its unchanged revision `20260803_0094`; its persistent volume was
  not modified by the isolated run.
- Repository staging remained empty and unrelated user paths were not changed.
