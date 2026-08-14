# BAS-119 Native Scoped Ozon Catalog Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirement: BR-095<br>
Architecture:
[ADR-0043](../../adr/ADR-0043-native-scoped-ozon-catalog-ingestion.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

The existing authenticated Ozon Catalog Evidence import now freezes the native operating and
source authority that created each new snapshot.

- The HTTP request remains `evidence_ids + store_ref + idempotency_key`; a client cannot submit or
  override tenant, entity, grant, Evidence-authority or adapter fields.
- The server resolves the Principal tenant/store, one current entity grant, independently scoped
  source Evidence and the implemented `ozon-seller-api-product-read-v1` adapter.
- The snapshot hash includes tenant, entity, store, grant hash, scoped Evidence-authority hash,
  `as_of`, adapter/version/contract hash, source grade and semantic authority.
- The Catalog parser still requires the immutable two-response
  `ozon-response-bundle-v2`, exact response paths, body hashes and matching offer identity.
- Native latest-item reads filter tenant/entity/store before choosing the latest offer. A newer row
  in another tenant/entity cannot hide the authorized current fact.
- Legacy rows remain available only through their independent scoped Evidence projection. No
  tenant/entity/adapter values were inferred or backfilled.
- Legacy idempotency remains `store + key`; native idempotency is
  `tenant + entity + store + key`. Changed immutable content conflicts.
- Import performs no Ozon network request, Product auto-binding, media-rights upgrade, Supplier
  Offer, actual cost, Listing, Approval, Permit or external write.

## Automated verification

```text
uv run python scripts/verify_secrets.py:
  PASS — 678 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local:
  PASS — 709 passed

Focused Catalog/scoped Catalog/adapter suite:
  PASS — 34 passed

git diff --check:
  PASS — line-ending notices only

npm ci:
  PASS — 0 vulnerabilities

npm test:
  PASS — 50 passed

npm run build:
  PASS — Next.js production build and TypeScript

uv run python scripts/export_openapi.py:
  PASS

OpenAPI SHA-256:
  014bc38e596be4eaeed224e670e82f55b398450eafcd9b35413343a0649a8b38
OpenAPI bytes:
  569209
```

The OpenAPI artifact is byte-identical to BAS-118 because BAS-119 intentionally preserves the
existing HTTP request/path contract. The new authority fields are supplied only by server
authorities.

Focused tests prove:

- only the implemented official Ozon Catalog adapter can issue an import contract;
- missing entity authority and pre-effective registry versions fail before Catalog mutation;
- the same native request replays one snapshot and changed content conflicts;
- the same idempotency key is independent across tenant/entity scopes;
- a malformed scope hash, scope mismatch or semantic adapter drift writes nothing;
- native scoped projection revalidates the frozen Evidence-authority hash;
- cross-scope rows are filtered before current-fact selection;
- the API passes server-owned scope/Evidence/adapter values to the workspace;
- anonymous access is 401 and cross-store access is 403.

## PostgreSQL migration acceptance

Migration `20260728_0061` is forward-only from `20260728_0060`. It adds a complete-or-empty native
authority tuple, partial legacy/native idempotency indexes and a scoped observed-time index.

Independent Compose PostgreSQL database `kjds_migration_0061_20260728`:

```text
base -> 0061:
  PASS
single head:
  20260728_0061
0061 -> 0060 -> 0061:
  PASS
service-bypass partial native tuple:
  rejected by ck_marketplace_catalog_native_authority_complete
same-scope duplicate native idempotency:
  rejected
same key in tenant-a/entity-a and tenant-b/entity-b:
  accepted as two independent rows
```

The real database was upgraded only forward from 0060 to 0061. Frozen before/after result:

```text
marketplace_catalog_snapshots:
  1 -> 1
snapshot ID:
  mcs_2b9eae9e7ebb49b08fe7421fc63d7cb1
snapshot hash:
  6aac2e817f3637a0efeff0ee815ad9115d55cb65b0f2f069a09eb1b75d1990b0
tenant_ref:
  NULL
adapter_id:
  NULL
Alembic current=head:
  20260728_0061
```

No real Catalog snapshot, item, Evidence link or binding was created or altered by BAS-119.

## Live Compose and API acceptance

API, media-worker and Web images were rebuilt from the final source.

```text
PostgreSQL: healthy
API: healthy
media-worker: healthy
Web: healthy

GET /health/ready:
  200
  status=ok
  version=0.59.0
  database.status=ok

anonymous Catalog latest:
  401
anonymous Catalog import:
  401
unauthorized store:
  403

authenticated Catalog latest:
  200
  status=no_data
  entity_ref=null
  included=0
  external_write_allowed=false

authenticated adapter registry:
  200
  status=no_data
  entity_ref=null
  external_write_allowed=false

Catalog import without entity grant:
  422
  Marketplace catalog import requires one current entity scope grant
```

The real Catalog row count remained one after the rejected import. Returning `no_data` is required:
the existing legacy row is not independently bound to the current Principal's missing entity
scope, and BAS-119 did not invent a grant or a native Seller API replay.

## Browser acceptance

Artifacts:

- `output/playwright/release-0.59.0/native-scoped-catalog-commerce-os-desktop.png`
  (`1440x1100`, SHA-256
  `79ade58e72e2188bb737641aac42815a0a4a3d44cbc2dec03c94dbd774ad7a10`)
- `output/playwright/release-0.59.0/native-scoped-catalog-commerce-os-mobile-390.png`
  (`390x844`, SHA-256
  `7b51cbc1c66514b8f22c199e73dc546f52b175cbcb55c6db00eb817b8ab04ad7`)

The live Commerce OS rendered the implemented Ozon Seller API Catalog adapter as admitted grade A
with `own_listing_catalog_fact`, while the current source state remained `no_data`. It also
rendered:

```text
需原始 Evidence · 需独立作用域绑定
外部写保持关闭
页面不把“功能已编码”冒充真实闭环
```

All 11 application requests returned 200, and browser console errors/warnings were zero. At the
headed 390px viewport:

```text
innerWidth=390
documentElement.clientWidth=375
documentElement.scrollWidth=375
body.scrollWidth=375
horizontal overflow=false
```

The 15px difference is the native Windows vertical scrollbar.

## Independent review

- Requirement/data/API/security/architecture/reliability review: no open P0 or P1 in BAS-119.
- `Info / no-op`: current entity authority is absent; live import correctly fails and the read
  projection remains `no_data`.
- `Info / defer`: no production Ozon Seller API response has been imported through the new native
  tuple. A real independently bound replay remains an M1 Release condition.
- `Info / no-op`: external media references remain
  `unverified_external_reference`; Catalog import does not grant content rights.
- `Info / no-op`: the official read worker remains isolated from the import service. No
  cookie/localStorage/internal endpoint or CAPTCHA bypass is introduced.

## Gate boundary

- BAS-119 engineering, migration, API, runtime and browser acceptance are complete.
- M1 Release still requires a real scoped entity grant and independently bound official Seller API
  Catalog replay.
- The 0.59 PM and RA **Release Gates remain REJECTED**.
- Pilot and Final Gates remain closed.
- No full fifteen-component downside CM3, Listing Approval, one-time Permit, Ozon publication,
  order-triggered purchase, settlement or reconciled cash CM3 exists.
- Ozon, supplier messaging, procurement, payment, inventory, price and advertising external writes
  remain closed.
- Pricing remains `not_for_sale`.
