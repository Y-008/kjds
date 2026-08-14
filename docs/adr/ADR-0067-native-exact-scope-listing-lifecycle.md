# ADR-0067: Native exact-scope Listing lifecycle workspace

- Status: Accepted for BAS-147 implementation
- Date: 2026-07-29
- Owners: PIM, Content, Profit, Evidence, Governance, Execution and Agent Team

## Context

KJDS already has Canonical Product/PIM projections, immutable Listing drafts,
Russian-native review Evidence, independent high-risk Approval and governed
Execution Plan/Dry Run/Permit machinery. Those authorities are currently
exposed through separate routes and dashboard fragments. Operators cannot see
one exact-scope answer to: what Ozon currently shows, what KJDS proposes, which
fields differ, which snapshot was reviewed, and which gate is next.

Seller ERP products commonly provide batch Listing edit, status and repair
workspaces. Copying those screens or calculating lifecycle state in Web/Router
would duplicate Product, Evidence, Approval and execution semantics. Treating a
missing platform field as equal to a proposed field would also create false
readiness.

## Decision

Add one deep module, `ScopedListingLifecycleWorkspace`, with the primary public
interface:

`project(principal, entity_scope, store_ref, as_of, ...)`.

The module composes, but does not replace:

1. `ScopedPimWorkspace` for exact Canonical Product, current marketplace
   Listing/offer binding, Passport and media readiness;
2. the existing scoped Listing Draft store for immutable desired state and its
   frozen Product/content/scope/Evidence hashes;
3. Listing Russian-native review Evidence for independent language, claims and
   Ozon-policy review;
4. the existing Approval authority for an independently decided frozen Listing
   snapshot;
5. governed Execution Plan and Dry Run records for later controlled execution.

The aggregate key is Canonical Product + target platform + offer. The module
owns deterministic lifecycle classification, field normalization and Diff,
authority-drift detection, filtering, pagination, counts, blockers,
Owner/SLA/next and stable snapshot/artifact hashes. Diff states are `same`,
`changed`, `source_missing` and `desired_missing`. Observed platform values,
desired draft values, approved snapshot and later readback are separate
sections; absence or unsupported readback remains an explicit gap.

The module must resolve exact entity scope before reading PIM, drafts,
Approvals or Plans. Missing/invalid entity returns `no_data` with zero upstream
reads. Bad current Evidence, latest bad review, cross-scope/future records,
Product or approval mismatch, frozen snapshot/hash drift, unlicensed media, or
truncated upstream authority fails closed and withholds the affected payload.

This slice is read-only. It does not create a Listing Draft, Russian review,
Approval, Execution Plan, Permit, platform task or readback. Its versioned
Agent artifact may only suggest internal work. Self-approval, Permit issuance,
publish, price, inventory and every external write remain false.

No new table is required if exact temporal and lookup semantics can be obtained
from the existing immutable draft/Evidence/plan rows and append-only approval
events. A forward-only `0075` is allowed only if implementation tests prove a
missing authority or index that cannot be derived safely.

## Rejected alternatives

- Build a Listing status page over raw tables: rejected because it would
  bypass exact-scope and Evidence authority.
- Recalculate Diffs or stage readiness in React or Router code: rejected
  because API, Web and Agents would disagree.
- Treat desired draft data as current platform state: rejected because a
  proposal is not a readback Fact.
- Automatically create Approval, Permit or publish tasks from the projection:
  rejected because a read projection cannot grant execution authority.
- Reuse a Seller ERP private endpoint or session to fill missing fields:
  rejected because it lacks stable owner authorization and violates BAS-146.

## Verification

Tests cover missing/invalid entity zero reads, tenant/store isolation, exact
scope/as-of, deterministic replay, every Diff state, multiple drafts per offer,
bad/latest-bad Evidence, Product/scope/approval/hash drift, future records,
unknown platform fields, PIM truncation, stable counts/cursor/hash and
suggestion-only Agent output.

API/OpenAPI must return anonymous `401` and forbidden `403`. Web must implement
ready/no_data/partial/blocked/error/retry, real list/detail drilldown and
desktop/390 layouts without horizontal overflow. PostgreSQL/runtime, migration
head, full backend/Web gates and a fresh Harness/Graph verifier observation are
required before BAS-147 becomes `DONE_ENGINEERING`.
