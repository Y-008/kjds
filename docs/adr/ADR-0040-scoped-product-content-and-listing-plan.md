# ADR-0040: Scoped Product, Passport, Content and Listing-Approval Plan

- Status: Accepted for BAS-116 implementation
- Date: 2026-07-28
- Owners: Identity, PIM, Content, Finance and Execution Governance
- Requirements: BR-013–016, BR-037, BR-039, BR-084, BR-086, BR-090–092
- Depends on: ADR-0034, ADR-0037, ADR-0038, ADR-0039

## Context

M0 now has scoped authorities for Evidence, governance, profit, operating tasks,
Marketplace Observation, Marketplace Catalog and Batch Opportunity. The legacy
Product, Passport, ContentAsset and ListingDraft repositories still expose
global-ID reads. A scoped Batch candidate can therefore cross back into global
Passport and ContentAsset queries during content readiness, and the existing
Listing draft route can build an Approval request before proving that Product,
content, supplier economics and Evidence belong to the same
tenant/entity/store/as-of tuple.

Caller-supplied `product_id`, `asset_id`, `store_ref`, SKU text or a value buried
inside JSON is not an ownership authority. Principal also has no entity
authority. Missing entity authority must stop raw Product/content reads, not
read globally and hide the result afterward.

## Decision

### 1. Product scope is native or derived from an already-scoped catalog fact

New Product rows freeze a complete native tuple:

`tenant_ref + entity_ref + store_ref + scope_grant_authority_sha256 + scope_as_of + created_by`

The tuple is complete-or-empty. Existing rows remain legacy-unscoped and are
never guessed or backfilled. A legacy Product may be projected only when a
current `ScopedMarketplaceCatalogAuthority` item in the exact requested scope
binds its `canonical_product_id`; that catalog Evidence is the derivation
authority. A native tuple and catalog derivation that disagree is a hard
conflict.

Scoped SKU uniqueness is per tenant/entity/store. Legacy uniqueness remains a
separate partial index so old rows are preserved without allowing an unscoped
row to become a scoped fact.

### 2. One scoped Product/content authority owns all projections and preflights

`ScopedProductContentAuthority` is the only authenticated runtime seam for:

- Product list/detail/readiness;
- latest Passport versions at an explicit `as_of`;
- ContentAsset list/detail and immutable source/artifact/QA Evidence;
- internal Product, Passport, media and content-draft mutation preflight; and
- a deterministic Listing approval plan.

It validates Principal store access and the current append-only entity grant
before any raw repository read. Child rows inherit Product scope through their
foreign key, but every Passport, content source, rights, artifact, QA, supplier
and profit Evidence is independently projected through
`ScopedEvidenceAuthority`. Excluded objects expose counts and reason codes only.

Direct asset-ID operations use an exact-scope repository join; they never load a
global ContentAsset first and then compare its Product.

### 3. Content readiness is an authority input, not a global callback

Scoped Batch Opportunity receives a frozen Product/content projection and its
snapshot hash together with scoped Observation, Catalog, Evidence and FX. In
scoped mode, `_content()` is forbidden from calling global Passport or
ContentAsset repositories. Missing Passport, rights or media QA constrains only
content/approval actions; it does not erase a valid read-only market research
candidate.

The content factory may create versioned draft/brief artifacts only from an
approved Product/Compliance/Quality Passport set and exact scoped Evidence.
Competitor titles and media remain observation inputs, never copied source
facts. Draft creation does not mean AI language QA, media QA, Listing readiness
or external publication is complete.

### 4. Listing approval planning precedes the existing approval ledger

The scoped authority composes the exact Product, approved Passport versions,
approved image assets and artifact Evidence, Supplier Offer, fifteen-item
ProfitScenario Evidence and proposed Listing payload into a deterministic
`listing_approval_plan_sha256`. It reports why a plan is allowed or blocked,
missing Evidence, Owner, SLA and next workspace.

Only an allowed, unchanged plan may create a scoped ListingDraft and the
existing independent `listing.publish` Approval request. ListingDraft freezes
the same scope, authority hashes, plan hash and Evidence IDs. Approval remains
the sole decision ledger; the plan is not an approval, Permit or execution
authority. Listing publication still requires an independently approved
execution plan, one-time Permit, execution-time revalidation, Readback, Kill
Switch and Compensation.

### 5. Fail-closed action semantics

- Missing entity grant: `no_data`, zero raw Product/content read.
- Unauthorized store: `403`.
- Legacy Product without a scoped Catalog derivation: `no_data`.
- Bad, expired, future, unbound or cross-scope Evidence: `blocked`.
- Missing Passport/content/economics: research may continue, but content draft
  or Listing approval planning is false at the relevant action.
- Approval plan created: internal deterministic artifact only.
- Ozon, supplier, procurement, payment, inventory and advertising writes:
  always false in BAS-116.

## Data and compatibility

Migration 0059 adds nullable native Product scope columns, complete-or-empty
checks and separate partial unique indexes for legacy and scoped SKU namespaces.
It also adds complete native scope, plan hash and frozen Evidence references to
ListingDraft. Existing rows are not backfilled. A downgrade removes only the
0059 additions and restores the original legacy uniqueness after proving no
duplicate SKU would be collapsed.

Legacy service methods remain available for internal migration/unit-test
compatibility, but authenticated API routes use the scoped authority. Response
compatibility aliases may be projected from the canonical scoped result; they
cannot become a second source of truth.

## Verification

BAS-116 must prove:

1. missing entity scope performs no Product, Passport or ContentAsset read;
2. cross-tenant/store Product and direct asset IDs are indistinguishable from
   absent resources;
3. native and catalog-derived scope both work, while conflicting derivations
   fail closed;
4. `as_of` excludes later Product, Passport, ContentAsset and Evidence state;
5. bad or cross-scope Passport/media/profit Evidence blocks the correct action;
6. scoped Batch never calls global Passport/content loaders;
7. Listing plan hash changes with Product, Passport, asset, economics or Listing
   payload changes and creates no Approval/Permit itself;
8. PostgreSQL rejects partial scope tuples and duplicate scoped SKU/draft
   authority;
9. anonymous requests are `401`, unauthorized stores are `403`, and all output
   keeps `external_write_allowed=false`; and
10. empty-database base-to-head and head-down-up migration replay, full backend,
    Web, OpenAPI, container health and desktop/390px browser gates pass.

## Consequences

This closes the M0 global Product/content read seam and gives M1 ingestion a
safe PIM target. It intentionally does not claim tenant RLS completion, AI
Russian-content quality, Supplier Offer truth, formal CM3, approval, Permit,
published Listing, order or settled cash profit. Those remain later-wave and
Release Gate facts.
