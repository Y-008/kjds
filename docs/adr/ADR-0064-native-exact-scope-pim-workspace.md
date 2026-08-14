# ADR-0064: Native exact-scope PIM workspace

- Status: Accepted for BAS-144 implementation
- Date: 2026-07-29
- Owners: PIM, Catalog, Content, Evidence and Agent Team

## Decision

Add one deep read module, `ScopedPimWorkspace`, with one public projection
interface: `project(principal, entity_scope, store_ref, as_of, ...)`.
It composes the existing `ScopedMarketplaceCatalogAuthority` and
`ScopedProductContentAuthority`; those remain the authorities for marketplace
catalog and Canonical Product/Passport/Content facts. No Product, SKU, Listing
or media truth is copied into a new repository or schema.

The workspace owns exact-scope admission, deterministic server-side filtering,
pagination, Canonical Product grouping, unbound Listing reporting, readiness,
counts, blockers and the stable snapshot/artifact hashes. Routers and Web are
thin consumers and may not recalculate readiness or counts.

Bad or conflicting upstream authority fails closed. Missing entity authority
returns no data without reading either raw authority. The Agent artifact is
decision support only and may suggest internal work; it cannot create Product,
Passport, Listing, Approval or Permit, and cannot write externally.

## Rejected alternatives

- A new PIM database or duplicated Product/SKU/Listing model: rejected because
  it creates a competing source of truth.
- Joining raw repositories in the API router or browser: rejected because it
  leaks scope and business logic across shallow callers.
- A migration solely to mark delivery progress: rejected because this slice is
  a read composition and has no schema change.

## Verification

Interface tests cover missing entity/no raw reads, unauthorized stores, bad
upstream authority, grouping, unbound Listings, deterministic filtering and
cursor behavior, stable hashes and the no-write Agent envelope. API/OpenAPI,
Web contract/build, PostgreSQL runtime, desktop/390 browser evidence and
Harness/Graph observation complete BAS-144 engineering evidence.
