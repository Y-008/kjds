# M0 Truth/Governance first slice evidence

## Verdict

`M0 Truth/Governance` first slice is implemented and verified as a dynamic, read-only contract.

This verdict is limited to the first M0 implementation slice. It does not change these later gates:

- 0.59 PM Release Gate: `REJECTED`
- 0.59 RA Release Gate: `REJECTED`
- Pilot Gate: not passed
- Final Gate: not passed
- pricing: `not_for_sale`
- Ozon / supplier / purchase / payment / ads external writes: closed

Recorded at: `2026-07-27T15:35:40.2134594+08:00`

## Baseline and traceability

- Branch: `feature/batch-opportunity-mining-059`
- Start evidence:
  [20260727_ULTIMATE_EXECUTION_START.md](20260727_ULTIMATE_EXECUTION_START.md)
- Approved product source:
  [ULTIMATE_PRODUCT_BLUEPRINT.md](../ULTIMATE_PRODUCT_BLUEPRINT.md)
- Approved requirements source:
  [ULTIMATE_REQUIREMENTS_ARCHITECTURE.md](../ULTIMATE_REQUIREMENTS_ARCHITECTURE.md)
- PM Start Gate:
  [20260727_ULTIMATE_START_GATE_PM.md](../reviews/20260727_ULTIMATE_START_GATE_PM.md)
- RA Start Gate:
  [20260727_ULTIMATE_START_GATE_RA.md](../reviews/20260727_ULTIMATE_START_GATE_RA.md)

## Implemented contract

Authenticated read-only endpoint:

`GET /v1/truth-governance/snapshot`

The endpoint is backed by `TruthGovernanceService.snapshot()`, which dynamically composes existing
authorities rather than copying their state into a second workflow:

- authenticated `Principal` for tenant and store scope
- `EvidenceService` for immutable blob hash and effective-time verification
- `OzonGlobalRuleRegistry` for effective registry and compiled-policy hashes
- `ProfitLedgerService` for scenario, accrual, settlement, and cash contribution availability
- `GovernanceService` and governed execution plans for approval state
- `LimitedExecutorService` for one-time Permit, receipt, and rollback state
- `PostExecutionService` for readback/observation state
- `KillSwitchService` for effective-time kill-switch state

The endpoint has no mutation method. Its control envelope always reports:

- `read_only=true`
- `external_writes=false`
- `ozon_write=false`
- `supplier_write=false`
- `purchase_write=false`
- `payment_write=false`
- `ads_write=false`

## Scope semantics

The authenticated principal currently has tenant and store authority only. It has no entity grant.
The contract therefore returns:

```json
{
  "entity_scope": {
    "status": "no_data",
    "entity_ref": null,
    "authority": null,
    "reason": "entity_scope_authority_missing"
  }
}
```

`tenant_ref` is never copied or re-labelled as `entity_ref`. The missing entity authority is a P0
blocker with Owner, SLA, next action, and workspace link. Tenant/store scope comes only from the
authenticated `Principal`; an unauthorized `store_ref` is rejected before the deep module runs.

Legacy governance records without an explicit store binding are not counted in a store snapshot.
The contract reports `governance_review_store_binding_missing` as a source gap instead of projecting
global records into a tenant/store view.

## Action-scoped behavior

The real container snapshot at `as_of=2026-07-27T02:00:00Z` returned:

- overall status: `ready_with_constraints`
- `observe_research=ready`
- `candidate_score=research_only`
- `content_draft=ready_with_constraints`
- `pilot_approve=blocked`
- `external_publish=blocked`
- `scale=blocked`
- `settlement_reconcile=no_data`

Visible blockers were:

- `entity_scope_authority_missing`
- `evidence_scope_not_bound`
- `profit_ledger_no_data`
- `rule_source_evidence_binding_missing`

All four contribution views returned `no_data` in the real store because there is no current
profit-ledger row. No zero or fabricated actual profit was emitted.

## Runtime verification

Docker Compose was rebuilt from the current source and all four services became healthy:

- `kjds-postgres-1`
- `kjds-api-1`
- `kjds-web-1`
- `kjds-media-worker-1`

Database migration state:

- `alembic heads` -> `20260727_0054 (head)`
- `alembic current` -> `20260727_0054 (head)`

API/runtime verification:

- authenticated request -> `200`
- anonymous request -> `401`
- authorized identity requesting `forbidden-store` -> `403`
- two requests with the same explicit `as_of` -> identical `snapshot_sha256`
- `entity_ref=null`
- `entity_scope.status=no_data`
- `external_writes=false`

The OpenAPI snapshot contains the authenticated read-only route and matches runtime
`app.openapi()`.

## Evidence and failure tests

`tests/test_truth_governance.py` verifies:

- deterministic explicit `as_of`
- tenant/store scope from `Principal`
- entity scope remains `null/no_data`
- direct service store-scope rejection
- API anonymous `401`
- API unauthorized store `403`
- effective-time kill-switch lookup
- rule-domain/source-evidence gaps remain visible
- profit no-data keeps all four contribution views at `no_data`
- a real SQLite Evidence blob altered after capture fails SHA-256 verification
- bad Evidence makes the snapshot `blocked`, clears the Evidence authority hash, blocks candidate
  scoring and Pilot approval, and never enables external writes

## Quality gates

- `uv run python scripts/verify_secrets.py`
  - passed: `609` non-ignored worktree files and `581` historical paths checked
- `uv run ruff check .`
  - passed
- focused M0 test:
  - `8 passed`
- M0/0.59 focused regression:
  - `85 passed`
- full backend:
  - `589 passed`
- `git diff --check`
  - passed
- OpenAPI fixed snapshot:
  - runtime and `docs/project/contracts/openapi-v1.json` match

The only warning is the existing Starlette `TestClient` deprecation warning for `httpx`; it is not a
test failure.

## Preserved operating data

No migration or data mutation was performed by this slice. The real database remained at 0054.
The frozen Marketplace Observation snapshot remained:

- snapshot ID:
  `mos_893969993df54dc9ab0ead01c588a215`
- snapshot SHA-256:
  `91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1`
- Evidence FK:
  `evd_294c9c496acb4c25bd74bccd92b18780`
- Evidence blob SHA-256:
  `0d8e17d3191d42572dec874d459686c4c0d6f3948354cff8195297252c307812`
- item count: `3`
- item SHA-256 values:
  - `2f18ac875e737eba84987f279f6eb4ea9f5a9a2c95f448ed7833cc4c30b74504`
  - `5d652608a84aed15f603d6a25ec43612f05057752d7fd7724e71a84c24566171`
  - `69c79e876f3a2c9c17688e11b25a467014596bb7efec592a298e918838f3fe92`

## Remaining M0 boundary

This slice intentionally does not invent the missing entity authority or populate absent operating
facts. The next M0 slice must add a formal, audited tenant/entity/store grant authority and scoped
Evidence/governance bindings before any external approval can become ready. It may not weaken the
current entity blocker or external-write closure.

## Second slice: audited scope grant authority

Recorded at: `2026-07-27T20:23:01+08:00`

`BR-084/BAS-106` and ADR-0034 now implement the next M0 boundary without inferring an entity:

- `ScopeGrantAuthority` stores append-only `grant|revoke` events for
  tenant/entity/store/subject actor;
- every event freezes explicit effective time, A-grade Evidence ID and verified content hash,
  `kjds-scope-authority-evidence-v1` metadata, independent reviewer, independent recording actor,
  reason, idempotency key, immutable request hash, and recorded time;
- current authority is derived at explicit `as_of`; revoke history is retained;
- self-grant, Principal store expansion, scope/Evidence mismatch, weak/damaged Evidence,
  ambiguous active entities, and idempotency payload drift fail closed;
- `TruthGovernanceService` dynamically includes the grant authority hash and only returns a real
  `entity_ref` when exactly one current verified grant exists.

No formal organizational authority Evidence was supplied or invented during this slice. The real
runtime therefore correctly remains:

- `entity_scope.status=no_data`
- `entity_ref=null`
- `external_publish=blocked`
- `external_writes=false`

Authenticated governance routes are:

- `GET /v1/scope-grants/current`
- `GET /v1/scope-grants/events`
- `POST /v1/scope-grants/events` (internal compliance/admin governance only)

Runtime route verification on the rebuilt production image returned anonymous `401`, authenticated
`200`, and unauthorized-store `403`. Both new routes appear in runtime OpenAPI; the fixed OpenAPI
snapshot matches it. This internal authority administration does not create an Ozon, supplier,
purchase, payment, advertising, Approval, or Permit action.

### Migration verification

Migration `20260727_0056` is forward-only from the already applied `0055`; no prior revision was
rewritten. A separate temporary PostgreSQL database passed:

- empty database `base -> 0056`
- `0056 -> 0055 -> 0056`
- single head/current `20260727_0056`
- PostgreSQL CHECK, FK, unique constraints, and current-scope index inspection

The temporary database was removed after verification. The real database advanced only
`0055 -> 0056`. A read-only before/after comparison found every Marketplace Observation snapshot,
Evidence FK/blob hash, and item count unchanged. Current totals are 24 snapshots and 45 items. The
original frozen three-item snapshot remains exactly:

- snapshot ID `mos_893969993df54dc9ab0ead01c588a215`
- snapshot SHA-256 `91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1`
- Evidence ID `evd_294c9c496acb4c25bd74bccd92b18780`
- Evidence blob SHA-256 `0d8e17d3191d42572dec874d459686c4c0d6f3948354cff8195297252c307812`
- item count `3`

### Second-slice gates

- focused scope/Truth/OpenAPI regression: `40 passed`
- full backend: `606 passed`
- Web: `49 passed`
- Web production build: passed, 22 routes generated
- secret scan: `623` non-ignored worktree files and `581` historical paths checked
- Ruff: passed
- `git diff --check`: passed
- PostgreSQL/API/Web/media-worker: healthy
- API version: `0.59.0`
- Alembic head/current: `20260727_0056`

The first full-backend attempt correctly failed because `scope_grants.py` was absent from the
machine-readable Outbox Coverage Registry. The registry now explicitly classifies this module as
an internal append-only effective-time audit ledger with no external delivery contract; the full
gate then passed. Browser/plugin collection remains a later Evidence-backed Observation Adapter and
cannot create entity authority, Supplier Offer, actual cost, or write permission.
