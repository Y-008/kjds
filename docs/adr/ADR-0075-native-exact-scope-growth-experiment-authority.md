# ADR-0075: Native exact-scope growth experiment authority

- Status: Accepted
- Date: 2026-07-30
- Requirement: BR-129
- Delivery: BAS-155

## Decision

Introduce one deep module, `ScopedGrowthExperimentWorkspace`, whose sole public
interface is `project(...)`. The module owns exact tenant/entity/store/as-of
admission, canonical Product/Listing joins, upstream contract validation,
server-side readiness, filtering, counts, opaque pagination, stable snapshots
and a versioned redacted Agent artifact.

The existing `MarketplaceGrowthPlanner`, `MarketplaceGrowthWorkspace`, 0042
tables and `/v1/marketplace-growth/*` routes remain legacy and are not promoted
to exact-scope authority. No guessed backfill is allowed. A future importer may
only bridge formal exports or official public APIs through Canonical
Diff/Evidence/Approval/Permit/Readback.

## Authority and failure closure

Missing entity authority performs zero upstream reads. Scope, as-of, contract,
hash, Evidence or Canonical binding drift fails closed and never falls back to
an older successful observation. Raw review/customer text and PII remain in
Evidence Blob; only redacted aggregates may enter this projection or artifact.

The module may produce recommendations, shadow experiment drafts and internal
tasks. It cannot change price, create a promotion, buy advertising, contact a
customer, approve itself, issue or consume a Permit, or write externally.
`external_write_allowed` and `private_erp_interface_allowed` are always false.

## Consequences

The new route and Web workspace consume one server projection. Client code may
not recompute business readiness. No 0080 migration is required until a new
immutable exact-scope observation authority is introduced; 0079 and legacy
0042 are unchanged.
