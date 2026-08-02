# ADR-0037: Scoped profit and operating facts

Status: Accepted for M0 implementation

Date: 2026-07-28

Owner: Finance Data Governance

Approver: Ultimate Start Gate PM/RA authority

## Context

Legacy `ProductRow`, `OrderRow`, `FactRecordRow` and `FinanceEntryRow` predate multi-tenant/entity
scope. `ProfitLedgerService.snapshot(store_ref=...)` currently reads their global tables and labels
the resulting rows with the requested store. A caller-supplied label is not an authority relation;
this can contaminate store views and makes actual-profit claims unsafe even when the API identity is
store-bounded.

M0 already has authenticated tenant/store scope, append-only entity grants and exact scoped
Evidence. Profit and operating projections must consume those authorities before any amount or
record count leaves the deep module.

## Decision

Keep `ProfitLedgerService` as the raw accounting projection, but make it deterministic at explicit
`as_of` and never expose it directly from the runtime. Add one `ScopedProfitLedgerAuthority` deep
module with read-only `snapshot(...)` and `erosion(...)` interfaces:

1. validate Principal store access;
2. require exactly one current entity grant; without it return scoped `no_data` without invoking
   the raw ledger;
3. invoke the raw ledger at the same explicit `as_of`;
4. require every order/SKU row's complete order, cost, scenario, finance and settlement Evidence
   set to pass `ScopedEvidenceAuthority` for the exact tenant/entity/store;
5. require each unallocated fact/entry Evidence independently; excluded rows expose only counts and
   reason codes, never their amounts, SKU, order ID or other business content;
6. recompute status, coverage, erosion conservation and stable hashes only from the scoped set.

The raw ledger's deterministic cutoff excludes records captured after `as_of`, future-effective
Evidence, and expired Evidence. It does not allocate by sales, SKU similarity or requested store.
Existing legacy facts remain immutable and unavailable to a scoped projection until their original
Evidence receives an independent scope binding.

API routes must first enforce Principal store scope and pass the same current entity authority.
Truth/Governance and Operating Intelligence use only the scoped service. A missing scope may
preserve read-only market research, but it cannot emit store profit, anomaly tasks based on that
profit, Pilot approval or external execution.

### OperatingTask and OperationsQueue scope

Operating Intelligence freezes the exact authenticated `tenant_ref`, granted `entity_ref`,
authorized `store_ref`, and ScopeGrant authority hash into every new anomaly scan and task before
it writes either record. Metric-specific dimensions are subordinate attributes and cannot replace
that authority tuple. List, event, transition, queue, and escalation interfaces must filter or
authorize against all four frozen values; a task ID is not an authorization capability.

Migration `20260728_0057` adds nullable native scope columns to anomaly scan and escalation event
records. Existing rows remain deliberately unscoped and are excluded from scoped runtime APIs;
they are not assigned to the default tenant, entity, or store. Existing task JSON is likewise
eligible only when it contains the complete canonical scope tuple. A database CHECK rejects
partially populated native tuples, while new writes always persist a complete tuple.

`OperationsQueueService` may retain its no-argument legacy projection for internal compatibility,
but every authenticated API route uses scoped mode. In scoped mode:

- OperatingTask rows are filtered by their complete canonical scope;
- governed commands and readback windows come only from `GovernanceScopeAuthority`;
- legacy global incidents and other unscoped sources are excluded rather than guessed;
- escalations persist and query the same tenant/entity/store/authority tuple;
- missing entity authority returns an empty, explicit `no_data` projection and performs no write.

This is an application-layer isolation seam, not a claim that PostgreSQL RLS is complete. The next
RLS migration must use these same native dimensions and preserve the legacy-unscoped state.

### Read-workspace composition

OperatingWorkbench, OperatingAnalytics, OperatingWorkspace and EvidenceOps are composition/read
models, not authorities. Their authenticated routes must accept the same explicit Principal,
entity scope, store and `as_of` context and must not call their historical no-argument global
loaders in scoped mode.

`OperatingWorkbench` may compose the scoped queue immediately. Global Gate readiness and legacy
Automation recommendations remain excluded with source-gap codes until their own facts have a
native or Evidence-bound scope. `OperatingAnalytics` must return a structurally complete
`no_data/partial` chart contract and scoped work items without reading catalog, growth, RFQ,
procurement, finance, execution or media authorities that have not yet adopted the scope contract.
This preserves the UI and drill-through contract while making absence explicit; it is preferable
to relabeling global counts with the requested store.

The legacy no-context service methods remain only for focused compatibility tests and controlled
internal migration tooling. Runtime routes and any downstream authenticated composer must use
scoped mode. A downstream composer that still invokes an unsafe source is not covered merely
because one child snapshot is scoped.

## Options rejected

- Trust request `store_ref`: caller input is not business authority.
- Add a fallback default store to legacy rows: silently fabricates ownership.
- Filter after returning the response: leaks amounts and identifiers before the policy seam.
- Duplicate all finance tables immediately: creates a second ledger and risky migration before the
  authority contract is proven.
- Infer store from SKU/order text: violates exact-binding and no-guess rules.

## Migration and compatibility

The scoped-profit slice adds no table. It composes existing append-only ScopeGrant and Evidence
authorities and leaves raw records unchanged. Direct `ProfitLedgerService` remains available only
for its focused accounting tests and future controlled backfill tooling; runtime APIs use
`ScopedProfitLedgerAuthority`.

The task/queue slice adds forward-only migration `20260728_0057` after `20260727_0056`. It does not
backfill legacy scope. Downgrade removes only the new nullable columns, indexes, and CHECK
constraints after an audited export; it does not rewrite prior revisions or delete task, scan, or
escalation rows.

Before multi-tenant production, a later forward-only migration may persist resource scope bindings
or native tenant/entity/store columns and PostgreSQL RLS. That migration must reconcile every
legacy row to this contract, preserve Evidence hashes, and leave ambiguous rows unclassified.

## Acceptance

- unauthorized store is `403`;
- missing/ambiguous entity scope returns `no_data` without reading the raw ledger;
- scoped rows require complete current Evidence and scenario Evidence;
- cross-store, unbound, future, expired or damaged Evidence excludes the row and blocks actual
  profit;
- excluded records reveal counts/reasons only, never amounts or identifiers;
- fixed `as_of` replay is deterministic;
- scoped erosion remains Decimal-conserved;
- scoped task/scan list and task event interfaces cannot cross tenant/entity/store;
- missing scope creates no anomaly scan, task, queue escalation, or external side effect;
- legacy-unscoped rows are excluded, not assigned to a default scope;
- database writes cannot persist a partial native scan/escalation scope tuple;
- external writes remain false.

Review trigger: native tenant/entity columns, PostgreSQL RLS, multiple legal entities per store,
ledger backfill, or a new financial fact source.
