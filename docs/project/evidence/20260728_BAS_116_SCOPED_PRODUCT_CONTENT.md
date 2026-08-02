# BAS-116 Scoped Product, Passport, Content and Listing Plan Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirements: BR-092<br>
Architecture: [ADR-0040](../../adr/ADR-0040-scoped-product-content-and-listing-plan.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

`ScopedProductContentAuthority` is now the authenticated authority for Product, three Passport
types, ContentAsset readiness and the deterministic Listing approval plan.

- Every native Product freezes a complete `tenant_ref + entity_ref + store_ref +
  scope_grant_authority_sha256 + scope_as_of + created_by` tuple. PostgreSQL rejects partial tuples
  and enforces SKU uniqueness inside that exact scope while allowing the same SKU in a different
  tenant/entity/store.
- A legacy Product is visible only when a current `ScopedMarketplaceCatalogAuthority` projection
  binds it as the canonical Product in the requested scope. No migration guessed or backfilled a
  tenant, entity or store onto the legacy row.
- Passport and ContentAsset facts are read at the requested `as_of`. Their source and artifact
  Evidence must independently project to the same scope; bad, missing or cross-scope Evidence
  cannot become approved content readiness.
- Scoped Batch Opportunity consumes the frozen scoped Product/content projection and never falls
  back to the global Passport or ContentAsset repository.
- The read-only `POST /v1/listings/ozon/approval-plan` freezes the scope grant, Product/content
  snapshot, selected assets, Supplier Offer, formal fifteen-component scenario, Evidence and
  Listing payload into a deterministic hash. It creates no ListingDraft, Approval, Permit or Pilot.
- The existing ListingDraft path can proceed only from an allowed plan, freezes the same authority
  hashes, and then requests the existing independent Approval. It still cannot publish without the
  separate one-time Permit, Readback, Kill Switch and Compensation chain.

The real database currently contains one legacy Product and no scoped Product, Passport,
ContentAsset or ListingDraft. The authenticated live result is therefore `no_data`. No public page
price, market title or legacy global row was promoted into Product/content authority.

## Automated verification

```text
Focused Commerce OS + scoped Product/content + scoped Batch + API suite:
  PASS — 63 passed

Full backend:
  PASS — 685 passed
  command used an isolated workspace --basetemp after the shared Windows
  %TEMP% pytest directory was locked by another process

uv run python scripts/verify_secrets.py:
  PASS — 665 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

git diff --check:
  PASS — line-ending notices only

npm ci:
  PASS

npm test:
  PASS — 50 passed

npm run build:
  PASS — Next.js production build and TypeScript

OpenAPI:
  deterministic checked-in SHA-256 before/after export:
  7b0645b8b99c181e015d121043c1915890ad4d985c2d36da9d7b5093fecb5356
  API contract suite: PASS — 32 passed
```

Negative and authority tests prove:

- missing entity authority returns `no_data` before Product, Catalog, Passport, ContentAsset or
  Evidence reads;
- anonymous Product/content and Listing-plan requests return 401;
- an authenticated identity requesting another store returns 403 before the authority method;
- Product creation without a current entity grant returns 409 and performs no write;
- native Product rows from another tenant or store are excluded without disclosing their details;
- a legacy Product without the exact scoped Catalog binding is excluded;
- Passport and asset Evidence conflicts block content readiness;
- fixed `as_of` excludes later Passport and ContentAsset rows;
- Listing approval-plan replay is deterministic, payload change changes its hash, and both
  Approval and Permit remain absent;
- a scoped Batch content evaluation cannot invoke the legacy global content loader.

## Migration replay and real database preservation

Alembic has one head: `20260728_0059`.

An isolated PostgreSQL database `kjds_bas116_0059_20260728` completed:

```text
base -> 20260728_0059
20260728_0059 -> 20260728_0058 -> 20260728_0059
```

PostgreSQL bypass checks rejected:

- a Product with a partial scope tuple;
- a duplicate SKU in one tenant/entity/store;
- a ListingDraft with a partial scope tuple.

They also proved that the same SKU in two different tenant/entity/store scopes is allowed. The
temporary database was removed and verified absent.

The sole real migration was `0058 -> 0059`. Before and after it:

```text
products=1
scoped_products=0
passports=0
content_assets=0
listing_drafts=0
marketplace_observation_items=49
marketplace_observation_snapshots=26
```

Old-column aggregate hashes were unchanged:

```text
Product:
  dfc3b5bedcadd4277f9324a2cc330b766a1d858f9b95ae3bb59b047eabdbc326
Passport / ContentAsset / ListingDraft (empty):
  e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
Observation items:
  517adc0eb44326d69fc99c68c0bd68628caa5b222ca730a6d84f7fa13294bf4b
Observation snapshots:
  31a66ea0e7210fd48d132e640d5b950eb884fc46b301ad2d487a5f19596e8dec
```

The original frozen three-item Observation remains byte-identical:

```text
snapshot:
  mos_893969993df54dc9ab0ead01c588a215
snapshot_sha256:
  91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1
Evidence:
  evd_294c9c496acb4c25bd74bccd92b18780
declared and recomputed Blob SHA-256:
  0d8e17d3191d42572dec874d459686c4c0d6f3948354cff8195297252c307812
item_sha256:
  2f18ac875e737eba84987f279f6eb4ea9f5a9a2c95f448ed7833cc4c30b74504
  5d652608a84aed15f603d6a25ec43612f05057752d7fd7724e71a84c24566171
  69c79e876f3a2c9c17688e11b25a467014596bb7efec592a298e918838f3fe92
```

## Live Compose, API and browser acceptance

API, media-worker and Web images were rebuilt from the current worktree. No migration was replayed
during rebuild; API startup observed the already-current 0059 database.

```text
PostgreSQL: healthy
API: healthy
media-worker: healthy
Web: healthy

GET /health/ready:
  status=ok
  version=0.59.0

container Alembic current/head:
  20260728_0059 / 20260728_0059

authenticated GET /v1/product-content/workspace:
  200
  status=no_data
  entity_ref=null
  external_write_allowed=false

authenticated GET /v1/commerce-os/workspace:
  200
  product_content.status=no_data
  external_writes=false

authenticated POST /v1/listings/ozon/approval-plan:
  200
  status=blocked
  reason=entity_scope_authority_missing
  approval_created=false
  permit_created=false
  external_write_allowed=false

anonymous Product/content GET:
  401

unauthorized store:
  403

OpenAPI includes:
  /v1/product-content/workspace
  /v1/listings/ozon/approval-plan
  /v1/listings/ozon/drafts
```

Browser artifacts:

- `output/playwright/release-0.59.0/scoped-product-content-commerce-os-desktop.png`
- `output/playwright/release-0.59.0/scoped-product-content-commerce-os-mobile-390.png`

The live page displayed Product, three-Passport, content-draft, media-QA and Listing-plan counts
from the server snapshot. It explicitly rendered:

```text
审批计划 ≠ 独立 Approval
Approval ≠ 一次性 Permit
Ozon 外部写入：关闭
```

Desktop and mobile console errors/warnings were zero. At the mobile acceptance size:

```text
innerWidth=390
documentElement.scrollWidth=390
body.scrollWidth=390
```

## Gate boundary

- BAS-116 engineering and runtime acceptance are complete.
- The 0.59 PM and RA **Release Gates remain REJECTED**.
- There is no real scoped Product/Passport/content set, allowed Listing plan, independent Approval,
  one-time Permit, Ozon publication, order, procurement, settlement or reconciled cash CM3.
- Ozon, supplier messaging, procurement, payment, inventory, pricing and advertising external
  writes remain closed.
- Pricing remains `not_for_sale`.
