# BAS-112 Scoped Read-Workspace Composition Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirements: BR-086, BR-088<br>
Architecture: [ADR-0037](../../../adr/ADR-0037-scoped-profit-and-operating-facts.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

Authenticated OperatingWorkbench, OperatingAnalytics, OperatingWorkspace, EvidenceOps and
Commerce OS now pass one explicit Principal/entity/store/`as_of` context through the read chain.

- Workbench scoped mode reads only `OperationsQueueService.projection(...)`.
- Legacy global Gate readiness and Automation recommendations are excluded with source-gap codes.
- Analytics scoped mode returns the same chart/stage/coverage/pipeline shape but does not read
  legacy global catalog, growth, RFQ, procurement, execution, finance or media sources.
- Point/line/surface workspaces and EvidenceOps consume that scoped analytics/workbench contract.
- Commerce OS resolves Truth/Governance scope first. Batch, ERP Item and media sources enter only
  through explicit future `latest_scoped`, `workspace_scoped` and `snapshot_scoped` seams; the
  current unscoped services are replaced with truthful no-data projections.
- Missing entity authority produces useful no-data tasks and next actions without relabeling global
  records to the requested store.
- All adapters and external writes remain closed.

Legacy no-context methods remain only for focused compatibility tests and controlled migration
tooling; no authenticated route uses them.

## Verification

```text
Focused read-composition suite:
  67 passed

uv run python scripts/verify_secrets.py:
  PASS — 649 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local:
  PASS — 649 passed, one existing Starlette deprecation warning

git diff --check:
  PASS — line-ending notices only

OpenAPI snapshot:
  regenerated and matched runtime

Web gate from the same unchanged Web source state:
  npm ci PASS, 0 vulnerabilities
  npm test PASS, 50 passed
  npm run build PASS
```

Negative tests replace every legacy source with a function that raises if read. Under a missing
entity grant, all five authenticated workspace flows still return successfully, proving the
no-data result is not produced after first reading and then hiding global facts.

## Live Compose evidence

API and media-worker were rebuilt from the final source state; PostgreSQL, API, Web and
media-worker were healthy. With the real tenant's current missing entity grant and fixed
`as_of=2026-07-28T01:00:00Z`:

```text
OperatingWorkbench: 200, no_data, external_writes=false
OperatingAnalytics: 200, no_data, catalog_items=0,
  formal_finance_entries=0, external_writes=false
OperatingWorkspace point: 200, contract/runtime no_data projection,
  external_writes=false
EvidenceOps: 200, needs_evidence, external_writes=false
Commerce OS: 200, no_data, observed_listings=0,
  profit_qualified_for_erp=0, external_writes=false
anomaly_scan_runs: 4 -> 4
operations_escalation_events: 0 -> 0
Alembic current/head: 20260728_0057
API version: 0.59.0
```

The first attempted Commerce OS smoke used a future UTC cutoff and correctly returned `422
as_of cannot be in the future`; it was rerun with a valid past cutoff and returned the result
above. No database or external side effect occurred.

## Review findings

- P0 — closed: authenticated Workbench could read the global queue and global recommendations.
- P0 — closed: Analytics and downstream workspaces could label global counts with a requested
  store.
- P0 — closed: Commerce OS read unscoped Batch/ERP/media before resolving entity authority.
- P1 — open: add native/Evidence-bound scope adapters for catalog, growth, RFQ, procurement,
  finance, media, Batch Opportunity and ERP Item so scoped Analytics can progressively show real
  rows.
- P1 — open: implement the accepted PostgreSQL RLS envelope only after native scope columns and a
  zero-ambiguity legacy classification plan exist.
- Release status remains unchanged: 0.59 PM/RA Release Gates are `REJECTED`, Pilot/Final Gates are
  not passed, and pricing is `not_for_sale`.
