# BAS-111 Scoped OperatingTask and OperationsQueue Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirements: BR-079, BR-086, BR-087<br>
Architecture: [ADR-0037](../../../adr/ADR-0037-scoped-profit-and-operating-facts.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

The runtime OperatingTask, anomaly scan and OperationsQueue APIs now use one exact
tenant/entity/store scope instead of exposing global task and queue tables:

- every new anomaly run and task freezes authenticated `tenant_ref`, current granted
  `entity_ref`, authorized `store_ref`, and the ScopeGrant authority SHA-256;
- metric dimensions are stored below that tuple and cannot overwrite it;
- task list, immutable event read/write, queue projection and escalation ledger authorize against
  the complete tuple;
- task IDs do not grant access, and cross-scope task reads/transitions return not found;
- resolve/dismiss Evidence must pass the current `ScopedEvidenceAuthority`;
- historical analysis `as_of` is separated from the current authorization time for write-bearing
  anomaly and escalation scans;
- the API queue reads scoped OperatingTask plus `GovernanceScopeAuthority` commands/windows and
  does not read or relabel legacy global incidents;
- missing entity authority returns `no_data`, an empty list/projection, `persisted=false`, and no
  task, scan or escalation write;
- all platform, supplier, procurement, payment and advertising writes remain closed.

This is an application authority seam. It does not claim PostgreSQL RLS is complete.

## Migration evidence

Forward-only migration `20260728_0057` adds nullable native scope columns and complete-or-empty
CHECK constraints to `anomaly_scan_runs` and `operations_escalation_events`. It intentionally does
not backfill legacy rows.

Verified on an isolated PostgreSQL database:

```text
base -> 20260728_0057: PASS
20260728_0057 -> 20260727_0056 -> 20260728_0057: PASS
ck_anomaly_scan_scope_complete: present
ck_operations_escalation_scope_complete: present
direct partial-scope INSERTs: rejected by PostgreSQL
single Alembic head: 20260728_0057
```

The temporary database `kjds_mig_0057_test` was removed after verification.

The real Compose database was upgraded only forward from `20260727_0056` to `20260728_0057`.
Before and after:

```text
anomaly_scan_runs: 4 -> 4
legacy scan rows with any new native scope value: 0
operations_escalation_events: 0 -> 0
```

The four legacy scan rows remain unscoped and cannot enter a scoped runtime projection.

## Frozen Observation preservation

The protected three-item Marketplace Observation remained unchanged across the real migration and
container rebuild:

```text
snapshot_id:
  mos_893969993df54dc9ab0ead01c588a215
snapshot_sha256:
  91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1
evidence_id:
  evd_294c9c496acb4c25bd74bccd92b18780
item_sha256:
  2f18ac875e737eba84987f279f6eb4ea9f5a9a2c95f448ed7833cc4c30b74504
  5d652608a84aed15f603d6a25ec43612f05057752d7fd7724e71a84c24566171
  69c79e876f3a2c9c17688e11b25a467014596bb7efec592a298e918838f3fe92
```

No Observation row, Evidence FK or content hash was rewritten.

## Automated verification

```text
uv run python scripts/verify_secrets.py
  PASS — 648 non-ignored worktree files and 581 historical paths checked

uv run ruff check .
  PASS

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
  PASS — 645 passed, one existing Starlette deprecation warning

git diff --check
  PASS — line-ending notices only

web/npm ci
  PASS — 0 vulnerabilities

web/npm test
  PASS — 50 passed

web/npm run build
  PASS — Next.js production build and TypeScript
```

Focused API/service verification covered:

- two tenants/entities/stores with disjoint scans, tasks, events, queue items and escalations;
- legacy-unscoped task exclusion;
- cross-scope task event read and transition denial;
- bad/unbound resolution Evidence leaving the task in progress;
- missing entity scope producing no persistent scan/task/escalation;
- deterministic analysis cutoff with current write authorization;
- SQLite and real PostgreSQL complete-or-empty scope constraints;
- anonymous `401`, unauthorized store `403`, authenticated no-entity `no_data`;
- OpenAPI API-key security and `store_ref` query contract.

## Live Compose evidence

The final source state was rebuilt into API and media-worker images. PostgreSQL, API, Web and
media-worker were all healthy. Live runtime results:

```text
/health/ready: 200, version=0.59.0, database=ok
anonymous GET /v1/operations-control/queue: 401
authenticated queue: 200, status=no_data, items=0, external_write_allowed=false
authenticated task list: 200, count=0
authenticated anomaly scan: 201, status=no_data, persisted=false,
  external_write_allowed=false
unauthorized store queue: 403
OpenAPI queue security: KjdsApiKey
OpenAPI task store_ref parameter: present
anomaly_scan_runs before/after smoke: 4 -> 4
operations_escalation_events before/after smoke: 0 -> 0
Alembic current/head: 20260728_0057
```

The real tenant currently has no formal entity grant, so `no_data` is the correct safe result. No
grant, Approval, Permit, supplier message, purchase, payment, ad action or Ozon write was created.

## Review findings

- P0 — closed: global task/scan/queue APIs could cross store/entity boundaries.
- P0 — closed: task IDs could be used without verifying the task's frozen scope.
- P0 — closed: historical `as_of` could otherwise be confused with current write authorization.
- P0 — closed: resolve/dismiss Evidence was integrity-checked but not scope-bound.
- P1 — open/defer to next M0 slice: OperatingWorkbench and downstream read workspaces still need
  the new scoped queue projection instead of the legacy no-argument queue.
- P1 — open/defer to an accepted migration: native scope/RLS for the remaining canonical facts.
- Release status — unchanged: 0.59 PM and RA Release Gates remain `REJECTED`; Pilot/Final Gates are
  not passed and pricing remains `not_for_sale`.
