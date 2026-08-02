# ADR-0069: Native exact-scope settlement and cash control

- Date: 2026-07-29
- Status: Accepted for BAS-149
- Requirement: BR-123
- Decision owner: Finance control-plane engineering

## Context

KJDS already has immutable `FinanceEntry`, `ReconciliationRun` and
`CashPlanItem` ledgers, native scoped Ozon Facts and a scoped profit
projection. The finance tables predate native tenant/entity/store authority:
their rows are global legacy records. Reading every finance row and hiding
cross-scope values after materialization cannot become the authority for a
multi-entity Order-to-Cash enterprise.

No second Order, Accrual, Settlement, Bank Cash or profit ledger may be
introduced. Historical finance rows also cannot be guessed into a tenant,
entity or store.

## Decision

Add one deep read module:

`ScopedSettlementCashWorkspace.project(...)`.

It owns exact-scope projection, three-book conservation, current-state
selection, failure policy, pagination, counts and stable hashes. API, Web,
Commerce OS and Agents consume this projection and do not recompute money or
readiness.

### Native finance authority

Forward-only migration `0075` adds complete-or-empty native scope fields to
the existing:

- `finance_entries`;
- `reconciliation_runs`;
- `cash_plan_items`.

Legacy rows keep all scope fields null and remain available only to legacy
workflows. Native rows freeze tenant, entity, store, ScopeGrant authority,
source Evidence authority and scope cutoff. Legacy and scoped idempotency use
separate partial unique indexes so two entities cannot collide on a provider
reference.

No historical row is updated or inferred.

### Exact-scope source seam

The existing finance service exposes one narrow SQL read source that applies:

- tenant/entity/store;
- ScopeGrant authority hash;
- `recorded_at <= as_of` and `effective_at <= as_of`;
- bounded collection limits;
- allowed native Fact types.

These predicates run before materialization. Missing or invalid entity
authority performs zero Fact, FinanceEntry, ReconciliationRun and Profit
reads.

### Projection and stages

The workspace groups only explicit reconciliation keys and projects:

- Order/Accrual book;
- Platform Settlement book;
- Bank Cash book;
- source Evidence and classification state;
- expected settlement, settlement variance and cash variance;
- latest independent reconciliation observation;
- Actual Cash CM3 eligibility from the existing scoped profit authority;
- stage, blockers, Owner, SLA and next workspace.

Stages are:

`fact_pending`, `accrual_pending`, `settlement_pending`, `cash_pending`,
`reconcile_pending`, `variance`, `unknown_fee`, `reconciled`, `blocked`.

Unknown fees remain isolated. Missing legs are not treated as zero. Allocation
by ratio, SKU guess or store-wide proportional split is prohibited.

Actual Cash CM3 remains `no_data` unless the existing scoped profit ledger is
reconciled at the same scope and cutoff, the three books conserve and all
current Evidence is valid.

### Failure policy

The affected business payload is withheld on:

- bad latest Evidence or missing blob;
- scope, grant or source Evidence hash drift;
- future Fact, entry or reconciliation state;
- duplicate/conflicting current records;
- reconciliation snapshot/input/status drift;
- source truncation;
- unknown fees, independent-review conflicts or non-conservation.

Failure output may expose bounded reason counts but not affected amounts,
order keys or Evidence identifiers.

### Agent and write boundary

The projection and its versioned Agent artifact may only recommend internal
tasks. They cannot create or mutate a Fact, FinanceEntry, ReconciliationRun,
CashPlanItem, Approval or Permit, and cannot initiate payment, collection,
refund, dispute or any external write.

Private Seller ERP endpoints, Cookies and internal Tokens remain prohibited.
Authorized exports and contracted APIs still enter through immutable
Evidence/import review before any native Fact or finance record.

## Consequences

- The old finance tables become usable by native exact-scope workflows
  without erasing legacy history.
- Scope and temporal predicates are testable below Router and Web.
- Real runtime will remain `no_data` until scoped financial Evidence and
  Facts exist; engineering completion cannot be reported as cash profit.
- A later controlled mutation slice may create native finance entries and
  reconciliation observations, but only through independent review and the
  same frozen authority contract.
