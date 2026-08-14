# ADR-0047: Native scoped Ozon import staging

- Status: Accepted for BAS-123 implementation
- Date: 2026-07-28
- Owners: Identity, Evidence, finance ingestion, Ozon integration
- Depends on: ADR-0034, ADR-0037, ADR-0041

## Context

Ozon CSV/XLSX imports are raw staging artifacts. They may contain orders, fees, accruals, returns
or settlement rows, but they are not formal commerce or accounting facts until contract
validation and the applicable independent finance controls pass.

The original upload route authenticates its caller, while `ImportJob` itself has no tenant,
entity or store authority. File SHA-256 is globally unique, import detail and review-status routes
are global by ID, and later promotion can resolve SKU against all Products. Two tenants uploading
the same official export could collide or reveal state across scope.

## Decision

### 1. Freeze native staging scope

A newly persisted Ozon import freezes:

```text
tenant_ref
entity_ref
store_ref
scope_grant_authority_sha256
source_evidence_sha256
scope_as_of
```

All six values plus `evidence_id` are present for native rows or all six authority values are
absent for legacy rows. Existing imports remain legacy and are never inferred into a tenant.

The original uploaded file remains immutable grade-A Evidence. Its metadata records the
authenticated tenant/entity/store and current grant, but this capture is not represented as an
independent Evidence scope review. Independent binding is required later for formal Fact
promotion.

### 2. One scoped import authority

`ScopedOzonImportAuthority` owns native import creation, duplicate lookup and detail access.

- Principal, exact store, current entity grant and deterministic `as_of` are resolved before file
  bytes are parsed or persisted.
- Same-scope file replay returns the immutable first import only when the frozen grant and
  Evidence hash still match.
- A changed grant under the same tenant/entity/store/file conflicts and requires explicit
  reauthorization; it does not create a second truth row.
- Exact-ID access filters tenant/entity/store/current grant in SQL before serialization.
- Legacy and cross-tenant imports are invisible to tenant APIs.

### 3. Scoped uniqueness

Migration 0065 replaces global file-hash uniqueness with:

- one partial unique SHA-256 for legacy rows;
- one partial unique
  `(tenant_ref, entity_ref, store_ref, sha256)` for native rows;
- a complete-or-empty native authority CHECK;
- a scope/created index.

The same file may be independently staged by different tenants. It remains one immutable import
within one tenant/entity/store.

### 4. Promotion boundary

BAS-123 is staging only:

```text
formal_fact_promotion_allowed=false
accounting_posted=false
product_mapping_performed=false
external_write_allowed=false
```

Finance review, fee mapping and accrual classification endpoints first resolve the scoped import,
but BAS-124 must add scoped formal Fact and promotion authority before a native import can be
promoted. The legacy global promotion path is not used for a native row.

## Consequences

- Official exports become reusable native ERP input without becoming global truth.
- Same-file cross-tenant collision is removed.
- Missing entity authority fails before upload processing and creates no Evidence or import row.
- Formal Fact, accounting and Product mapping remain deliberately blocked until their own scoped
  authority is implemented.

## Acceptance

- anonymous import detail and finance-control status routes return 401;
- unauthorized stores return 403;
- missing entity authority creates no Evidence, import or import row;
- legacy and cross-tenant imports are excluded before serialization;
- same file is independent across tenant scopes and idempotent in one scope;
- changed grant or Evidence hash conflicts;
- PostgreSQL rejects partial tuples and same-scope duplicates;
- base → 0065 and 0065 → 0064 → 0065 replay pass in an independent database;
- real database advances forward only and preserves the existing import, Pilot, Run, Evidence,
  Catalog and Claim rows;
- native promotion remains fail closed until BAS-124;
- API/OpenAPI, full backend/Web suites, Compose and desktop/390px acceptance pass.
