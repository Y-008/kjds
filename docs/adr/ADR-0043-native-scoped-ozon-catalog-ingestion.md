# ADR-0043: Native Scoped Ozon Seller API Catalog Ingestion

Date: 2026-07-28<br>
Status: Accepted for BAS-119<br>
Requirements: BR-095<br>
Depends on: ADR-0022, ADR-0038, ADR-0041, ADR-0042

## Context

KJDS already validates an Ozon product-read response bundle and imports it into the Marketplace
Catalog after scoped Evidence preflight. The persisted Catalog snapshot still freezes only
`store_ref`, Evidence IDs and the Ozon response contract. It does not natively persist the current
tenant/entity grant or the admitted Seller API adapter contract.

That gap matters because a later reader can see the Catalog row only through Evidence projection,
but cannot prove from the row itself which tenant/entity authority and source-adapter version
created it. The import route also computes scoped Evidence authority and then discards its hash.

BAS-117 established the versioned source-adapter registry. BAS-119 must connect that registry to
the existing Catalog deep module without adding another catalog or contacting Ozon during import.

## Decision

Extend Marketplace Catalog snapshot persistence with a complete-or-empty native authority tuple:

```text
tenant_ref
entity_ref
scope_grant_authority_sha256
scope_evidence_authority_sha256
scope_as_of
adapter_id
adapter_version
adapter_contract_sha256
source_grade
semantic_authority
```

Migration 0061 is forward-only from 0060. Existing rows remain legacy with every new column NULL;
the migration must not infer tenant/entity/adapter values. PostgreSQL rejects a partial tuple.
Idempotency remains compatible for legacy rows and becomes
`tenant + entity + store + idempotency_key` for native rows.

`IntelligenceSourceAdapterRegistry.catalog_contract()` uniquely selects the implemented
`catalog_evidence_import` adapter for Ozon, freezes the registry and adapter contract hashes, and
requires current entity authority. The contract permits internal Catalog import only; it grants no
network or external-write capability.

The authenticated import flow is:

1. resolve Principal tenant/store and one current entity grant;
2. independently project every original response Evidence record into that exact scope;
3. compile the effective Ozon Seller API Catalog adapter contract;
4. validate the immutable two-response `ozon-response-bundle-v2` and its per-body hashes;
5. persist one Catalog snapshot with the scope, Evidence-authority and adapter tuple included in
   the snapshot hash;
6. link source Evidence to the saved snapshot and read it back through the scoped Catalog
   projection.

The Catalog store filters native tenant/entity/store rows before latest-offer selection. Legacy
rows remain eligible only through the existing independent Evidence binding; a newer native row
from another tenant/entity cannot suppress the authorized tenant's current fact.

## API and runtime boundary

The existing `POST /v1/marketplace-catalog/ozon/import-evidence` remains the mutation surface and is
backward-compatible at the HTTP request level. The server now supplies scope and adapter authority;
clients cannot submit or override those fields.

No Ozon network request occurs in this endpoint. Network acquisition remains isolated in
`OzonReadOnlyWorker`, which uses the official `api-seller.ozon.ru` origin and stores raw grade-A
response Evidence. A completed read-run response still requires independent scope binding before
Catalog import.

The import:

- creates no canonical Product binding automatically;
- creates no Supplier Offer, price decision, inventory write, Listing draft, Approval or Permit;
- never copies cookies/localStorage or calls internal endpoints;
- never converts external media references into owned/licensed rights.

## Acceptance

1. Native Catalog import freezes the exact tenant/entity/store/grant/Evidence/adapter tuple.
2. PostgreSQL rejects a partial tuple and same-scope duplicate idempotency.
3. The same idempotency key is allowed in two tenant/entity scopes.
4. Legacy Catalog rows remain byte-identical and all new columns NULL.
5. A native row from tenant B cannot suppress tenant A during latest-item selection.
6. A mismatched grant, Evidence-authority hash or adapter contract is excluded/blocked.
7. Missing entity authority or bad/cross-scope Evidence causes no Catalog write.
8. Contract-only or non-Ozon adapters cannot import a Catalog bundle.
9. Bundle/body hash, response path, offer ID and item-count mismatches fail closed.
10. Idempotent replay returns the original snapshot; changed scope/Evidence/adapter content
    conflicts.
11. Anonymous access returns 401 and cross-store access returns 403.
12. Empty PostgreSQL base-to-head and 0061-to-0060-to-0061 replay pass.
13. Real database forward migration preserves row counts and canonical legacy hashes.
14. OpenAPI, full tests, Compose and readback prove `external_write_allowed=false`.

## Consequences

This closes the native Catalog provenance seam for future official Seller API replay. It does not
claim that live Ozon credentials, an entity grant or a production Catalog import exists. Those
remain truthful `no_data` until independently supplied.
