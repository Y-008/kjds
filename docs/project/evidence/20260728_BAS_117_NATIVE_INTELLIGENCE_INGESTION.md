# BAS-117 Native Intelligence Ingestion and Source Adapter Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirements: BR-093<br>
Architecture: [ADR-0041](../../adr/ADR-0041-native-intelligence-ingestion-and-source-adapters.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

KJDS now has one native, versioned admission boundary for market and supplier intelligence. The
boundary does not copy a seller tool's private implementation, browser state or internal endpoint:
it freezes the legal/semantic contract by which an official API, official export, authorized
connector or allowed public observation may enter the existing Catalog/Observation truth kernel.

- `IntelligenceSourceAdapterRegistry` freezes adapter ID/version, source-grade ceiling, semantic
  authority, allowed hosts, Evidence requirements, acquisition policy, effective date and registry
  hash. Cookie/localStorage reuse, internal API use, CAPTCHA bypass and personal-data collection are
  explicitly false.
- Three adapters are implemented: Ozon Seller API product-read import, allowed public Ozon
  observation and allowed public 1688 observation. The generic seller-tool export is
  `contract_only`; it stays `no_data` until a provider-specific license, original export Evidence
  and parser contract exist.
- Authenticated Observation capture resolves the principal's tenant/store and current entity grant
  before reading or persisting the payload. A new native row freezes the complete
  `tenant + entity + store + grant hash + as_of + adapter/version/contract hash + source Evidence`
  tuple.
- The database filters native tenant/entity/store scope before current-fact fingerprint
  deduplication. A newer row in another store or tenant therefore cannot suppress the authorized
  store's fact.
- Legacy rows remain fully legacy. Migration 0060 did not guess or backfill tenant, entity, grant or
  adapter authority onto the 26 existing Observation snapshots.
- Public price remains an Observation, never a Supplier Offer or actual procurement cost. Comments
  and public-page signals never become sales. A source grade never promotes the semantic authority
  of the captured fact.
- The authenticated adapter API and Commerce OS render the same server-owned registry status,
  hashes, gaps and control envelope. The client does not recompute admission or business meaning.
- Ozon, supplier messaging, purchase, payment, pricing, inventory and advertising writes remain
  false.

## Automated verification

```text
uv run python scripts/verify_secrets.py:
  PASS — 671 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

uv run pytest -q -p no:cacheprovider
  --basetemp=.runtime/pytest-bas117-final-20260728-1458:
  PASS — 696 passed

uv run python scripts/export_openapi.py:
  PASS

Focused API + intelligence contract suite:
  PASS — 42 passed

OpenAPI SHA-256:
  4af387bfabe3f335862657a36baa89be238bb7165f195d347061a39583c98808
OpenAPI bytes:
  565586

git diff --check:
  PASS — line-ending notices only

npm ci:
  PASS — 0 vulnerabilities

npm test:
  PASS — 50 passed

npm run build:
  PASS — Next.js production build and TypeScript
```

Negative and authority tests prove:

- an anonymous adapter request returns 401;
- an authenticated identity requesting another store returns 403 before adapter evaluation;
- a future `as_of` returns 422;
- a missing current entity grant returns `no_data`, and capture fails before a database write;
- a `contract_only` seller-tool export cannot be captured;
- a source or item URL outside the frozen adapter host set is rejected;
- an unsafe acquisition policy cannot be admitted into the registry;
- adapter profile/marketplace mappings must be unique;
- a partial scope/adapter tuple is rejected by PostgreSQL;
- `source_evidence_ids_json` must be an array;
- duplicate idempotency inside one native scope is rejected while the same source key in another
  tenant/entity/store is allowed;
- native rows are filtered by scope before fingerprint deduplication;
- a native row with a mismatched grant hash, adapter contract or Evidence scope cannot project into
  the requested authority;
- a fixed `as_of` produces deterministic adapter and Observation contracts.

## Migration replay and real database preservation

Alembic has one head: `20260728_0060`.

Isolated PostgreSQL verification completed:

```text
empty base -> 20260728_0060
empty base -> 20260728_0060 -> 20260728_0059 -> 20260728_0060
```

Direct PostgreSQL bypass checks rejected:

- a duplicate source-profile/idempotency key inside the same native scope;
- a partial native scope/adapter tuple;
- an object in place of the frozen source-Evidence ID array.

They also proved that the same source key can exist independently in two authorized
tenant/entity/store scopes. The isolated PostgreSQL container and replay database were removed
after the exact targets were verified.

The sole real migration was forward-only `0059 -> 0060`. Before and after it:

```text
marketplace_observation_snapshots=26
marketplace_observation_items=49
native scoped/adapted snapshots=0
legacy snapshots=26
```

Canonical pre/post hashes of the legacy columns remained equal:

```text
Observation snapshots:
  5c6a5967ec303dff732eca0ea767824f286f5159744e06513969b8f8e4f8d497
Observation items:
  049c095ccececfd0a2d375b60e4a7db994277f4f422f88bde9de14b9931f49fa
```

The original frozen three-item Observation remains unchanged:

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

API, media-worker and Web images were rebuilt from the current source. PostgreSQL, API,
media-worker and Web are all healthy.

```text
GET /health/ready:
  200
  status=ok
  version=0.59.0

container/local Alembic current and head:
  20260728_0060 / 20260728_0060

anonymous GET /v1/intelligence-ingestion/adapters:
  401

authenticated GET /v1/intelligence-ingestion/adapters:
  200
  status=no_data
  tenant_ref=default
  entity_ref=null
  implemented=3
  contract_only=1
  external_write_enabled=0
  source_gap=entity_scope_authority_missing

unauthorized store:
  403

authenticated POST /v1/marketplace-observations:
  409
  reason=current entity scope authority is missing
  database row counts unchanged

authenticated GET /v1/commerce-os/workspace:
  200
  status=no_data
  intelligence_sources.status=no_data
  control_envelope.external_writes=false
```

The live registry projection was:

```text
contract_id:
  kjds-intelligence-source-adapter-authority-v1
registry_sha256:
  34ff5ea70699289c756f2d7f60f34d4309efd8b1bf68bc642723e4db0e3a4e3d
counts:
  implemented=3
  contract_only=1
  external_write_enabled=0
```

Browser artifacts:

- `output/playwright/release-0.59.0/native-intelligence-ingestion-commerce-os-desktop.png`
  (`1440x1100`, SHA-256
  `2f6c338f5e6481e46f4bc54d14c5f40ec12185bdfc57a799c3d6f1c9476ad785`)
- `output/playwright/release-0.59.0/native-intelligence-ingestion-commerce-os-mobile-390.png`
  (`390x844`, SHA-256
  `34d235874faf471b548378823dddbd38b505fe1d1868be427570e6ecbf07a186`)

The desktop and 390px mobile page rendered the server-owned source status, all four adapter
contracts, grade ceilings and semantic authority. It explicitly displayed:

```text
公开价格 ≠ Supplier Offer
评论/页面信号 ≠ 销量
来源等级 ≠ 业务事实升级
外部写入：关闭
```

Browser console errors and warnings were zero. At 390px:

```text
innerWidth=390
documentElement.clientWidth=375
documentElement.scrollWidth=375
scrollWidth == clientWidth
no horizontal overflow=true
```

The 15px difference is the headed Windows Chromium vertical scrollbar, not content overflow.

## Independent review

Review baseline: the final BR-093/ADR-0041 contract, migration 0060, checked-in OpenAPI and current
0.59 runtime.

- Requirement/API/data/security/architecture/reliability review: no open P0 or P1 in BAS-117.
- `Info / defer`: provider-specific seller-tool exports remain `contract_only`; no product claim is
  made that Wuyou, Miaoshou, Mangguo, Maozi or Lizhi is integrated.
- `Info / no-op`: the live tenant has no entity grant, so the truthful runtime state is `no_data`.
  Adding a native Observation merely to make a count non-zero would violate the authority contract.
- `Info / defer`: real Seller API/export/connector data requires the later provider license,
  credentials, revocation, rate-limit and original-Evidence acceptance slice.

## Gate boundary

- BAS-117 engineering, migration, runtime and browser acceptance are complete.
- The 0.59 PM and RA **Release Gates remain REJECTED**.
- There is no real native scoped intelligence row, fully costed candidate, permitted Listing,
  Ozon publication, order-triggered purchase, settlement or reconciled cash CM3.
- Ozon, supplier messaging, procurement, payment, inventory, price and advertising external writes
  remain closed.
- Pricing remains `not_for_sale`.
