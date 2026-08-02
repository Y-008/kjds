# ADR-0041: Native Intelligence Ingestion and Source Adapters

- Status: Accepted for BAS-117 implementation
- Date: 2026-07-28
- Owners: Market Intelligence, Identity, Evidence and Platform Governance
- Requirements: BR-003–004, BR-007, BR-037, BR-081–086, BR-089–093
- Depends on: ADR-0034, ADR-0038, ADR-0039, ADR-0040

## Context

M0 closed the global-read seams for Observation, Catalog, Batch Opportunity and
Product/content. M1 still had two incorrect shortcuts:

1. authenticated Observation capture resolved an entity grant but persisted the
   result as a legacy unscoped snapshot; and
2. the generic `seller_tool_export` label admitted data without freezing which
   provider, license, original artifact and parser contract produced it.

That is not enough for a native cross-border ERP. A browser extension, seller
tool, public page or API response may supply an observation or an original
export, but it cannot become the source of KJDS identity, Supplier Offer,
actual cost, sales, profit or permission. The capability patterns seen in
无忧易售、妙手、芒果店长、Maozi、荔枝 and LinkFox remain comparison inputs.
Their code, cookies, localStorage, internal endpoints and broad browser
permissions are not a KJDS runtime dependency or copying source.

## Decision

### 1. One versioned source-adapter registry

`IntelligenceSourceAdapterRegistry` is the single admission seam for M1 source
classes. Every adapter freezes:

- stable adapter ID/version and registry content hash;
- ingestion surface and marketplace;
- maximum source grade, never an automatic business-fact grade;
- semantic authority;
- original-Evidence and independent scope-binding requirements; and
- acquisition policy covering official/authorized status, rate limits,
  geography, personal-data minimization, revocation, robots applicability and
  prohibited browser state/internal API/captcha bypass.

An adapter can be `implemented`, `contract_only`, `blocked` or `retired`.
`contract_only` is not executable. The generic seller-tool export remains
`contract_only` until a provider-specific license, original artifact and
versioned parser contract exist.

### 2. Native scope is frozen at capture

Authenticated Observation capture must resolve exactly one current
tenant/entity/store grant and exactly one implemented adapter before reading
the request into the Observation workspace. Migration 0060 adds a
complete-or-empty native tuple to each snapshot:

`tenant_ref + entity_ref + store_ref + scope_grant_authority_sha256 + scope_as_of`

and a complete adapter tuple:

`adapter_id + adapter_version + adapter_contract_sha256 + source_grade + semantic_authority + source_evidence_ids`

Both tuples are present together or absent together. Legacy rows remain
unchanged for audit and require the existing independent A-grade Evidence
binding. New scoped idempotency is isolated by tenant/entity/store/profile/key;
the same key may be used in another authorized scope, while payload drift in
the exact same scope is rejected.

### 3. Scope filtering precedes current-fact reduction

Raw `latest` and paged reads receive the authorized tenant/entity/store scope
at query time. They exclude other native tenant/entity rows before fingerprint
deduplication, so a newer row in Store or Tenant B cannot suppress an older
current fact in Tenant A. Legacy rows may still enter the bounded query only to
be independently Evidence-bound by `ScopedMarketplaceObservationAuthority`;
legacy `external` is never relabelled as a tenant fact.

The scoped authority also verifies that a native row's stored tenant, entity,
store, grant hash and adapter contract hash match the current request. A
mismatch discloses only excluded counts and reason codes.

### 4. Semantic authority never promotes an observation

- Allowed Ozon public pages are external market observations, not own sales.
- Allowed 1688 public/checkout pages are supplier-market observations, not a
  Supplier Offer or actual procurement cost.
- Comments, ratings or public page counters are not sales.
- An A-grade Seller API source can establish only the facts defined by its
  explicit response/parser contract.
- Browser/plugin collection cannot use cookies/localStorage as a transferable
  credential, call private/internal APIs, defeat captcha/limits or retain
  personal data.

Every capture creates immutable Observation Evidence and is still
`pending_independent_binding`. Native scope proves where the record was
captured; it does not replace independent Evidence integrity/scope review.

### 5. Commerce OS exposes source readiness without creating writes

The authenticated adapter endpoint and Commerce OS workspace show implemented
versus contract-only adapters, grade ceilings, semantic authority, scope,
registry/snapshot hashes and source gaps. The client renders server output and
does not infer sales, costs or readiness. Ozon, supplier messaging, purchase,
payment, price, inventory and advertising writes remain false.

## Data and compatibility

Migration 0060 is forward-only from frozen 0059. It replaces the old global
Observation idempotency constraint with separate legacy and scoped partial
unique indexes, adds a scope/observed index and rejects partial tuples at the
database layer. Existing rows and their Evidence hashes are not backfilled or
rewritten. A downgrade is allowed only for replay/rollback validation after
proving scoped 0060 rows will not collide under the legacy global key.

The legacy direct workspace method stays available for migration and unit-test
compatibility. Authenticated capture routes always use the new registry and
native tuple. The existing Ozon Seller API catalog import remains the admitted
first-party product-read surface; this ADR does not add API credentials or a
new network worker.

## Verification

BAS-117 must prove:

1. missing entity scope returns `no_data` and does not capture;
2. anonymous access is `401` and unauthorized stores are `403`;
3. allowed public Ozon/1688 mappings are deterministic and generic seller-tool
   exports fail closed;
4. unsafe cookie/localStorage/internal API/captcha policy is rejected;
5. scope and adapter hashes are frozen into Observation/Evidence;
6. same-scope payload drift conflicts while the same key across scopes is
   isolated;
7. cross-tenant current facts are filtered before deduplication;
8. bad Evidence, grant-hash or adapter-hash mismatch is excluded without
   detail disclosure;
9. PostgreSQL rejects partial tuples and invalid source-Evidence JSON;
10. legacy Observation rows and the protected three-item snapshot remain byte
    and hash stable through 0059→0060;
11. empty database base→0060 and 0060→0059→0060 replay pass; and
12. backend, Web, OpenAPI, containers and desktop/390px browser acceptance
    remain green with all external writes false.

## Consequences

M1 now has a lawful, attributable input seam that can scale to provider-specific
official exports and authorized connectors without creating a second ERP truth.
It does not yet prove nationwide/full-market coverage, exact candidate cohorts,
Supplier Offers, actual cost, real sales, Pilot readiness or profitability.
Those remain later M1–M3 and Release Gate facts.
