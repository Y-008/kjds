# ADR-0085: Store-category routing over the profit growth operating system

- Status: Accepted; engineering implementation complete
- Date: 2026-08-02
- Requirements: BR-136, BR-137
- Deliveries: BAS-161, BAS-162
- Owners: Product, Profit Operations, Data, Engineering

## Context

The Profit Command Center can now retain the complete recon bundle and expose
currency-safe SKU economics, but a seller still needs to know which store,
official category and operating playbook should receive each candidate. A
single generic "listing strategy" is unsafe: store positioning, assortment
mode, price band, region, fulfillment, operating capability and official
platform taxonomy all constrain the valid route. Derived commercial labels
such as seasonal, heavy, replacement part or content-led are useful for
operations, but they are not Ozon category IDs.

KJDS must support beginners, solo sellers, teams and enterprises without
forking the fact/profit kernel or weakening data truth for lower-priced plans.
The dashboard must also provide multi-page drillthrough without moving profit
calculation into the browser or fabricating history for charts.

## Decision

1. Add one deep `StoreCategoryStrategyWorkspace` over Profit Command rather
   than a second product, category, profit or listing authority.
2. Store operating profiles are evidence-backed append-only events scoped by
   tenant, entity, store and current Scope Grant. A profile records positioning,
   assortment mode, price band, regions, fulfillment, growth channels,
   capabilities and bounded official category paths.
3. Category paths preserve official L1/L2/L3, leaf category and product type
   identities separately from derived archetype tags. Derived tags may select
   evidence gates, metrics and playbooks; they can never create an official
   category match.
4. Routing precedence is deterministic: explicit exclusion, exact official
   leaf, exact product type, exact official hierarchy, then no route. Core,
   adjacent and experimental roles project `primary_store`,
   `adjacent_category_limited` and `pilot_only`; missing official identity or
   profile returns `needs_category_data`.
5. Profit state selects lifecycle and playbook. Research, Pilot, growth and
   exit logic may propose listing, traffic and inventory actions, but cannot
   publish, advertise, procure, approve or issue a Permit.
6. Cross-store routing compares only authorized current profiles. It returns
   alternatives, confidence and whether a governed handoff is required. It
   never duplicates a listing or automatically publishes across stores.
7. Freeze an immutable `StoreOperatingPlanSnapshot` for replay and model
   evaluation. Input/output hashes, profile, Profit Command snapshot, Evidence
   and as-of are retained; idempotency drift conflicts.
8. Extend Profit Command with server-owned candidate filtering/pagination,
   analytics, data lineage and portfolio projections. Profit aggregation is
   allowed only for the same basis and currency with Evidence. Cross-store
   cash amounts remain unaggregated without an aggregate reconciliation
   snapshot. Missing history explicitly returns `no_data` and zero synthetic
   points.
9. Deliver one multi-page Web console: profit overview, SKU collection, SKU
   detail, store/category routing and Evidence lineage. The browser displays
   server projections and performs no profit calculation or synthetic trend
   generation.
10. Seller tiers share this kernel. Commercial plans may change quotas,
    automation eligibility, approvals and SLA, but not data completeness,
    export rights, Evidence standards, profit semantics or execution controls.

## Public Interface

```text
GET  /v1/profit-command/portfolio
GET  /v1/profit-command/workspace
GET  /v1/profit-command/analytics
GET  /v1/profit-command/candidates
GET  /v1/profit-command/candidates/{candidate_id}
GET  /v1/profit-command/lineage
POST /v1/profit-command/candidates/{candidate_id}/pilot-proposals

GET  /v1/seller-os/category-strategy-registry
POST /v1/seller-os/store-profiles
GET  /v1/seller-os/store-profiles/current
GET  /v1/seller-os/operating-plan
POST /v1/seller-os/operating-plans
GET  /v1/seller-os/operating-plans/{snapshot_id}
GET  /v1/seller-os/store-routing
```

## Alternatives Rejected

- Separate beginner and enterprise applications: rejected because facts and
  profit would drift between products.
- Model-generated store/category assignment: rejected because the model may
  propose interpretation but cannot create official taxonomy facts.
- Automatic broad distribution to every compatible store: rejected because it
  increases duplicate content, capital exposure, account risk and attribution
  ambiguity before profitability is proven.
- Client-side dashboard calculations: rejected because formula, FX, Evidence
  and as-of would become non-replayable.
- A new event broker or workflow engine: rejected because PostgreSQL,
  immutable snapshots and the existing approval/Permit authorities are enough
  for this read/proposal slice.

## Migration and Rollback

Migration `20260802_0086` adds append-only store profile events and operating
plan snapshots. Downgrade removes only those new strategy tables after the
feature is disabled; it does not alter Product, Evidence, bundle, profit,
orders, finance or execution authorities. The replay gate is
`base -> 0086 -> 0085 -> 0086` in an isolated, strictly named PostgreSQL
database. Production rollback disables the new routers and pages first; it
must not mutate or reinterpret saved Evidence.

## Acceptance

- Official identity match and exclusion precedence are deterministic.
- A derived tag alone cannot produce an official route.
- Cross-tenant/store reads fail closed before business data access.
- Profile and plan writes are idempotent and append-only in PostgreSQL.
- Five profit bases remain separate in API, contracts and UI.
- Portfolio does not sum cash profit without a reconciled aggregate snapshot.
- Browser tests prohibit client profit arithmetic and synthetic data.
- Desktop build and 390px CSS bounds pass.
- All routes remain proposal/read-only except the independently governed
  profile/snapshot persistence and existing Pilot proposal endpoint.

## Review Triggers

Re-open this ADR before adding automatic cross-store publication, changing
official taxonomy match semantics, treating derived tags as platform
categories, aggregating cross-currency/cross-store profit, or allowing an Agent
to create profiles, approvals, permits or external actions.
