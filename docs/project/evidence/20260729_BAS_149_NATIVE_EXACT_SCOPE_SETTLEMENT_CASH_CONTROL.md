# BAS-149 native exact-scope settlement and cash control

- Date: 2026-07-29
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Business state: `no_data`
- External write: `false`
- Requirement: `BR-123`
- ADR: [ADR-0069](../../adr/ADR-0069-native-exact-scope-settlement-cash-control.md)

## Outcome

BAS-149 delivers one deep read module:

`ScopedSettlementCashWorkspace.project(...)`.

It projects the Order/Accrual, Platform Settlement and Bank Cash books from
the existing native Fact and Finance authorities. It does not create a second
Order, Settlement, Cash, Profit, Approval or Permit truth store.

The canonical API is:

`GET /v1/finance-control/workspace`.

The Web route is:

`/finance-control`.

Router, React and Agent prompts do not calculate amounts, variances, stages or
Actual Cash CM3.

## Native finance authority

Forward-only migration `20260729_0075` adds complete-or-empty native scope
fields to the existing:

- `finance_entries`;
- `reconciliation_runs`;
- `cash_plan_items`.

Each native row freezes tenant, entity, store, ScopeGrant authority hash,
source Evidence hash and `scope_as_of`. Historical legacy rows remain all-null
for these columns and are never guessed into an entity. Legacy and scoped
idempotency are separated by PostgreSQL partial unique indexes.

The migration creates six exact-scope/idempotency indexes and preserves a
single Alembic head. A temporary PostgreSQL database passed:

- empty replay from 0001 to 0075;
- 0075 downgrade to 0074;
- forward replay from 0074 to 0075;
- deletion of the temporary database after verification.

The live PostgreSQL current and script head are both
`20260729_0075`.

## Deep-module boundary

### Scope before raw read

The workspace validates authenticated Principal, exact authorized store,
current entity grant and timezone-aware cutoff before calling
`FinanceService.read_scoped_sources(...)`.

The narrow SQL source applies tenant/entity/store/grant and `as_of` predicates
before materializing:

- native `ozon_order`, `ozon_accrual`, `ozon_settlement`, `ozon_fee` and
  `ozon_return` Facts;
- scoped Finance Entries;
- scoped Reconciliation Runs.

Missing entity authority returns `no_data` and performs zero raw finance or
profit reads. Malformed ready authority is `blocked`. Legacy finance rows and
cross-tenant/store rows remain excluded at SQL level.

### Three-book projection

Each explicit reconciliation key receives:

- Order/Accrual book;
- Platform Settlement book;
- Bank Cash book;
- latest independent Reconciliation observation;
- expected settlement, settlement variance and cash variance;
- unknown fee and independent-review classification;
- Evidence references;
- `fact_pending`, `accrual_pending`, `settlement_pending`, `cash_pending`,
  `reconcile_pending`, `variance`, `unknown_fee`, `reconciled` or `blocked`;
- Owner, SLA and next workspace;
- server counts, filters, opaque cursor and stable snapshot/artifact hashes.

An older damaged Reconciliation does not replace a newer valid authority. A
damaged or future latest Reconciliation fails closed. When a Settlement Fact
and Finance Entry both exist but disagree, the cycle becomes `blocked`, the
settlement amount is withheld and Actual Cash CM3 remains unavailable.

No proportional allocation, SKU guess or store-wide split is allowed.

### Actual Cash CM3 boundary

Three-book reconciliation alone does not create cash profit. Actual Cash CM3
is available only if a future/proven native exact-scope profit source is
reconciled at the same scope and cutoff, produces exactly one order result and
has no unallocated or excluded values.

The current `ScopedProfitLedgerAuthority` still reads the pre-native legacy
profit source and therefore does not advertise `native_exact_scope`. BAS-149
does not call it and truthfully returns:

`actual_cash_cm3.status=no_data`.

### Formal Fact is not automatic accounting

The full suite exposed and closed an attempted semantic bypass:

`FinanceService.ingest_fact(...)` continues to reject native scoped Formal
Facts with `accounting ingestion is not authorized`.

Read-only settlement projection may consume exact-scope Facts, but Fact
promotion cannot directly generate a Finance Entry. A later mutation path
must use a separately reviewed scoped finance-entry contract.

## Failure and no-write policy

The affected business payload is withheld on:

- missing, bad or hash-drifted Evidence;
- invalid payload hash, currency, amount or timestamp;
- future Fact, Entry or Reconciliation state;
- scope, grant, source or input hash drift;
- truncated source collection;
- conflicting current Order or Settlement authority;
- reconciliation self-review or Evidence-independence failure;
- unknown fee, review requirement, variance or missing book leg.

The versioned `kjds-finance-steward-artifact-v1` artifact can only suggest
internal tasks. Runtime output proves:

- `finance_entry_created=false`;
- `reconciliation_created=false`;
- `fact_created=false`;
- `cash_plan_created=false`;
- `approval_created=false`;
- `permit_created=false`;
- `payment_initiated=false`;
- `collection_initiated=false`;
- `refund_initiated=false`;
- `dispute_initiated=false`;
- `external_write_allowed=false`.

Private Seller ERP endpoints, Cookies, internal Tokens and CAPTCHA bypass
remain prohibited. KJDS authorization does not create third-party permission.

## Backend and repository verification

Focused tests cover:

- missing/malformed entity with zero source and profit reads;
- deterministic three-book replay and suggestion-only Agent output;
- latest-valid versus older-bad Reconciliation selection;
- Settlement Fact/Entry conflict;
- bad Evidence payload withholding;
- source truncation;
- deterministic server search, stage filter and opaque cursor;
- unauthorized store;
- real SQLite native/legacy/cross-tenant isolation;
- source Evidence authority drift;
- Finance, Profit, scoped Profit and API/OpenAPI compatibility.

Results:

- focused backend: `74 passed`;
- full backend: `900 passed`, `9 warnings`;
- Ruff: all checks passed;
- OpenAPI snapshot matches runtime;
- `verify_secrets`: passed across `880` non-ignored worktree files and `581`
  historical paths;
- `git diff --check`: passed;
- `npm ci`: passed with `0` vulnerabilities;
- Web contract tests: `85 passed`;
- Web production build: `45` routes.

## PostgreSQL and real runtime

Live rows:

- FinanceEntry: `0` native / `0` total;
- ReconciliationRun: `0` native / `0` total;
- CashPlanItem: `0` native / `0` total;
- scoped Order/Accrual/Settlement/Fee/Return/Inventory Facts: `0`;
- Actual Cash CM3 available: `0`.

After rebuilding the current source, PostgreSQL, API, Web and media-worker are
all `healthy`.

Live API behavior:

- anonymous workspace: `401`;
- configured operator and exact store: `200`;
- unauthorized store: `403`;
- entity: `null`;
- status: `no_data`;
- all stage, settlement, cash and Actual Cash CM3 counts: `0`;
- `scoped_input_read=false`;
- `external_write_allowed=false`.

Repeated fixed-input reads are deterministic and create no Fact, Finance
Entry, Reconciliation, Cash Plan, Approval, Permit or OperatingTask.

## Web and browser

`/finance-control` renders:

- loading/error/retry;
- ready/no_data/partial/blocked;
- three-book Evidence ladder;
- server-side reconciliation-key/currency search and stage filter;
- explicit variances, unknown fees and latest reconciliation;
- Actual Cash CM3 as a separate authority;
- source gaps, blocker, Owner/SLA/next;
- explicit no-write and Agent boundaries.

Commerce OS, OMS and Inventory link to the same workspace. The Web contract
suite verifies all three links; the rebuilt browser runtime also verified the
OMS and Inventory links.

Browser QA used the configured operator identity in memory to authenticate
real rebuilt API responses; no credential was persisted in screenshots,
source or logs. This is an API-authenticated browser harness, not a claim that
a new Supabase user session was created.

- desktop: `inner/client/scrollWidth = 1440/1440/1440`;
- mobile: `inner/client/scrollWidth = 390/390/390`;
- finance page console errors: `0`;
- finance page errors: `0`;
- visible business state: `no_data`.

Screenshots:

- `output/playwright/bas149-finance-control-desktop.png`
  - SHA-256:
    `eb15952b3d1136feb4e76573c91f89af7c86072f6ff0e0d3a3994084b8630d25`
- `output/playwright/bas149-finance-control-mobile-390.png`
  - SHA-256:
    `ae1e623b3258ac2e6eefe37508b1a31d5d942e3a927c825668c4fd7a1e336cd1`

The visible BAS-040 scheduler toast is an unrelated stale runtime signal. It
was not hidden or relabeled as BAS-149 success.

## Harness and Graph

`scripts/seed_bas149_agent_graph.py` independently reruns and records:

- focused pytest;
- PostgreSQL/Alembic authority;
- authenticated Docker/API runtime;
- desktop and 390px browser Evidence;
- immutable BAS-149 Evidence.

Canonical Graph after BAS-149:

- tasks: `76`;
- nodes: `183`;
- edges: `186`;
- observations: `>=320`.

Only fresh external verifier observations can change task state.

## Gate interpretation

BAS-149 is `DONE_ENGINEERING`, not a settlement or profit claim.

The business state remains:

- no exact entity authority;
- no scoped Order, Accrual, Settlement, Fee, Return or Inventory Facts;
- no scoped Finance Entry or Reconciliation;
- no bank cash;
- no Actual Cash CM3;
- no Approval, Permit or external write.

The 0.59 PM/RA Release Gates and Pilot/Final Gates remain rejected or
unpassed. Real Order-to-Cash requires official scoped financial Evidence,
independent finance review, three-book conservation and a future native
exact-scope profit authority.
