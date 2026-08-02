# ADR-0066: Authorized Seller ERP Bridge and Canonical Diff

- Status: Accepted for BAS-146 implementation
- Date: 2026-07-29
- Owners: Integration, Evidence, PIM, OMS, Inventory and Agent Team

## Context

Seller ERP products such as 店小秘 expose useful cross-platform export and
operating workflows. KJDS needs migration, reconciliation and coexistence
capability without making any third party the authority for Product, Listing,
Order, Inventory, Settlement or Cash.

A private endpoint discovered from a browser session is not an authorization
contract. Reusing cookies, internal tokens, undocumented endpoints, CAPTCHA
bypass or intercepted traffic would be unstable, non-revocable in KJDS terms
and unable to prove provenance. User control of KJDS does not confer the
third-party service owner's permission.

KJDS already owns immutable Evidence, independent exact-scope binding,
Canonical Product/PIM, formal Order Facts/OMS and formal Inventory
Facts/fulfillment projections. A page or Router joining arbitrary exports to
those authorities would duplicate scope, freshness and conflict semantics.

## Decision

Add one deep module, `ScopedSellerErpBridge`, whose primary public read
interface is:

`reconcile(principal, entity_scope, store_ref, as_of, source_evidence_id, ...)`.

The module also owns a dedicated three-party authority workflow:

1. an operator freezes the original official/formal export or authorized
   Adapter snapshot as immutable source Evidence, including provider, source
   kind, domain, schema version, explicit column mapping, exported time,
   authorization mode and file hash;
2. a different Reviewer records an immutable accepted/rejected review after
   checking original authenticity, exact export scope, schema mapping,
   authorization and absence of credentials/session material;
3. a different Compliance/Admin recorder creates the grade-A exact-scope target
   ID/hash binding from that accepted review.

Revocation is append-only. Current review, binding, Evidence integrity,
authorization state and scope are re-evaluated at every reconciliation.

After exact-scope admission, the module parses the bounded source snapshot and
composes existing `ScopedPimWorkspace`, `ScopedOmsWorkspace` or
`ScopedInventoryFulfillmentWorkspace`. It owns schema validation, normalization,
canonical key selection, latest-row semantics, source/canonical comparison,
field-level diffs, deterministic filters/cursor/counts, blockers, Owner/SLA/next
and stable snapshot/artifact hashes.

Rows remain Observations. Diff states are `matched`, `source_only`,
`canonical_only`, `conflict` or `blocked`; none promotes a Fact or mutates a
Canonical object. Missing/invalid entity or source identity performs zero blob
and upstream reads. Bad Evidence, a latest rejection/revocation, missing binding,
scope/hash/as-of drift, duplicate keys or schema drift fails closed and does not
disclose affected business rows.

Supported source classes are platform official exports, Seller ERP formal
exports and snapshots from public/contracted/explicitly authorized Adapters.
Provider-specific mapping is data, not code authority. 店小秘 is optional and
removable; KJDS preserves Evidence, Canonical Facts, decisions and outcomes.

Agent output is versioned decision support and internal task suggestion only.
It cannot import formal Facts, create or modify Product, Listing, Order,
Inventory, Approval or Permit, issue a Permit, or write to any external system.

## Rejected alternatives

- Reverse engineer private Seller ERP interfaces or reuse session credentials:
  rejected because KJDS lacks the service owner's authorization and cannot
  make the access stable, revocable or independently auditable.
- Treat an uploaded spreadsheet as Canonical truth: rejected because a source
  observation cannot replace existing Facts.
- Let Web, Router or Agent prompts calculate diffs: rejected because every
  caller would duplicate scope, schema and conflict rules.
- Let uploader self-review or bind a source: rejected because it would allow
  self-asserted provenance.

## Verification

Interface tests cover three-party independence, immutable idempotent replay,
conflicting replay, reject/revoke/expiry, missing entity and zero reads,
authorization/store isolation, bad/unbound Evidence, latest bad record,
schema/hash/as-of drift, duplicate canonical keys, every diff state,
deterministic filtering/cursor/counts/hash and the no-write Agent envelope.

API/OpenAPI, anonymous `401`, forbidden `403`, PostgreSQL/Alembic, Web
ready/no_data/blocked/error/retry, desktop/390 rendering and a fresh external
Harness/Graph observation complete BAS-146 engineering evidence. Real data and
external write remain gated separately.
