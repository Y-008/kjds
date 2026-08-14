# ADR-0039: Scoped Batch Opportunity and Evidence-bound Economics

- Status: Accepted for M0 engineering
- Date: 2026-07-28
- Requirement: BR-091 / BAS-115
- Depends on: ADR-0034, ADR-0037, ADR-0038

## Context

The legacy Batch Opportunity engine can normalize exact product identity and
variant cohorts, compare supplier alternatives, calculate the fifteen-component
downside CM3 screen, and allocate a bounded approval waitlist. Its legacy
loader also accepts global `external` observations and selects FX directly from
the finance table. An authenticated route therefore cannot safely treat a
caller-provided `store_ref` as ownership or relabel those inputs as one
tenant/entity/store fact set.

This slice must unlock deterministic research scoring without converting
observations into Supplier Offers, actual costs, formal CM3, approvals, Permits,
Pilots, or marketplace writes.

## Decision

Introduce `ScopedBatchOpportunityAuthority` as the only authenticated Batch
Opportunity boundary.

1. Resolve `Principal` store access and the append-only entity grant before any
   child read. A missing entity returns `no_data`; a conflicting grant returns
   `blocked`; a cross-store request returns 403.
2. Collect only exact-store, `as_of`-bounded current facts from
   `ScopedMarketplaceObservationAuthority`. Shared legacy `external` rows are
   not published into a tenant scope.
3. Read own-listing identity only from `ScopedMarketplaceCatalogAuthority`.
   Absence of a Catalog item is valid for a new candidate; a damaged or
   conflicting Catalog authority fails closed.
4. Recursively collect every Observation, cost, fee, logistics, media and
   checkout Evidence reference, then require current, intact,
   tenant/entity/store-bound projection from `ScopedEvidenceAuthority`.
5. Freeze one effective and recorded-before-`as_of` FX row per required
   non-CNY currency. Its Evidence must pass the same scoped projection. The
   Batch evaluator receives this frozen map and may not fall back to global FX.
6. Hash Observation, Catalog, FX/economics and Evidence authorities into the
   request fingerprint. The persisted run freezes tenant, entity, store, grant
   hash and combined Evidence authority. Reusing an idempotency key with a
   changed authority or request is a conflict.
7. Derive own listing versus external competitor cohort from scoped Catalog
   offer/product bindings. Exact product identity and exact variant remain the
   cohort key. Supplier ranking keeps target purchase quantity, MOQ, tax,
   freight, freshness and risk-adjusted landed-cost semantics.
8. A successful run is `ready_with_constraints`: it creates an immutable
   internal research artifact and may score candidates. It never creates a
   Supplier Offer, actual cost, formal CM3, independent Approval, one-time
   Permit, Pilot, purchase, payment, ad or Ozon write.

`GET /v1/batch-opportunities/latest` reads only the latest run matching the
complete tenant/entity/store/grant tuple at the requested `as_of`. The derived
run Evidence and payload scope must remain intact and consistent. `POST
/v1/batch-market-scans` requires a current entity grant and otherwise returns
409 without scanning.

## Data evolution

Alembic 0058 adds nullable native scope columns to legacy Batch runs, a
complete-or-empty CHECK, a legacy partial idempotency index, a scoped
tenant/entity/store idempotency index and a scoped `as_of` lookup index.
Existing rows remain legacy/unscoped and are not backfilled or published.

The empty-database release test is `base -> 0058 -> 0057 -> 0058`. Once scoped
runs with colliding legacy store/key pairs exist, downgrade to the old
store-only uniqueness contract is intentionally not a lossless production
rollback; production rollback is application rollback with 0058 retained.

## Consequences and remaining gates

- Candidate screening can advance from scoped observations while actual
  profit, approval and external execution remain closed.
- Current real data stored as legacy `external` stays visible only to internal
  compatibility tooling until an independently reviewed scope/publication
  authority exists.
- PostgreSQL native tenant/entity columns and FORCE RLS for Observation,
  Catalog and their derived inputs remain a separate ADR-0038 Release Gate.
- BAS-116 must scope the downstream content/passport and approval-plan
  authorities before any candidate can become `pilot_ready`.
