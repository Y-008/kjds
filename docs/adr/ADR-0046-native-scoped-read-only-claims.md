# ADR-0046: Native scoped read-only Claims

- Status: Accepted for BAS-122 implementation
- Date: 2026-07-28
- Owners: Identity, Evidence, Ozon read integration, governance
- Depends on: ADR-0034, ADR-0037, ADR-0045

## Context

`ReadOnlyClaim` is the independently reviewed interpretation bridge from one successful
read-only Ozon Run to a possible later business fact. It is not itself a Product, inventory
balance, price, Supplier Offer, actual cost, Listing approval or external execution authority.

The original Claim service verifies the Run state hash and independent reviewer, but its list,
detail and review routes address a global table by ID. Its idempotency key is globally unique,
and the row does not freeze the tenant/entity/store, current grant or Evidence scope authority.
The proposal route now preflights a scoped Run, but later Claim reads and review can still cross
scope. That breaks the same authority boundary established for Pilot and Run in BAS-121.

## Decision

### 1. Freeze native Claim authority

A new native Claim has a complete tuple:

```text
tenant_ref
entity_ref
store_ref
scope_grant_authority_sha256
scope_evidence_authority_sha256
scope_as_of
```

All six values are present or all are absent. Existing Claims remain legacy rows with the empty
tuple and are never inferred into tenant APIs.

The frozen Evidence authority is calculated from the Run summary Evidence and its independent
grade-A scope binding. A Run ID, Claim ID, payload value or actor-supplied store field never
establishes scope.

### 2. One scoped Claim authority

`ScopedReadOnlyClaimAuthority` owns proposal, list, detail and review for tenant APIs.

- It resolves the authenticated Principal, current entity grant, exact store and deterministic
  `as_of` before Claim, Run or Evidence reads.
- Proposal requires `ScopedReadOnlyPilotAuthority.require_run`, a completed successful Run, and
  current independently scoped Run Evidence.
- List and detail filter the Claim tuple and join Claim → Run → Pilot in SQL before serialization.
  The joined Pilot tuple and current grant must equal the Claim tuple.
- Review revalidates the Claim, its parent Run/Pilot, current grant, frozen Evidence binding and
  proposer/reviewer separation before the immutable pending decision changes once.
- Missing entity authority returns an explicit `no_data` collection without Claim, Run or
  Evidence reads. An exact-ID read or mutation fails closed.

### 3. Scoped idempotency and migration

Migration 0064 removes global Claim idempotency uniqueness and creates:

- one partial unique legacy key for rows whose authority tuple is empty;
- one partial unique native key for
  `(tenant_ref, entity_ref, store_ref, idempotency_key)`;
- an index for scoped current reads;
- a complete-or-empty authority CHECK.

The existing `(run_id, payload_hash)` uniqueness remains. Same-scope replay converges; the same
client key in a different authorized scope is independent.

### 4. Semantic and execution boundary

An accepted Claim remains:

```text
formal_fact_promoted=false
external_write_allowed=false
approval_created=false
permit_created=false
```

It may later feed a separately scoped Product/inventory/price fact-promotion workflow. Native
scoped Claims are not accepted as Ozon listing before-state authority by the legacy global
execution-plan path; that path must first gain the same tenant/entity/store execution authority.
This slice therefore cannot publish, price, change inventory, purchase, pay or advertise.

## Consequences

- Tenant Claim reads and review no longer trust a global ID.
- Legacy records remain available only to explicit internal legacy services and migrations.
- Run Evidence without an independent exact-scope binding is visibly blocked instead of silently
  promoted.
- A later fact-promotion module can consume one frozen, reviewed Claim contract without rebuilding
  authentication logic.

## Acceptance

- anonymous Claim list/get/review returns 401;
- unauthorized stores return 403;
- missing entity authority returns list `no_data` and creates/reviews nothing;
- legacy and cross-tenant rows are excluded before serialization;
- bad, expired, unbound or cross-scope Run Evidence creates no native Claim;
- changed grant or Evidence binding blocks review;
- proposal and review enforce independent actors and deterministic idempotency;
- PostgreSQL rejects partial tuples and same-scope duplicate keys, while allowing the same key
  across scopes;
- base → 0064 and 0064 → 0063 → 0064 replay pass on an independent database;
- real database advances forward only and preserves Pilot, Run, Evidence, Catalog and Claim rows;
- API/OpenAPI, full backend/Web suites, Compose and desktop/390px browser acceptance pass.
