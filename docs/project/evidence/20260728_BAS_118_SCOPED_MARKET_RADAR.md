# BAS-118 Scoped Market Radar and Candidate Normalization Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirements: BR-094<br>
Architecture: [ADR-0042](../../adr/ADR-0042-scoped-market-radar-and-candidate-normalization.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

KJDS now exposes one authenticated, read-only Market Radar over the existing scoped Observation,
Catalog and Batch Opportunity truth modules.

- The server recomputes and validates the canonical exact product identity + exact variant key
  before aggregation. A stored/tampered candidate key that does not match the identity and variant
  is excluded.
- Several Ozon listings for one exact variant become one cohort. Counts separately report observed
  listings, unique exact identities, own Listing rows, external competitor rows, unique competitor
  sellers, supplier option rows, unique suppliers and target-quantity checkout rows.
- Own Listing identity comes only from the scoped Catalog. Its price is projected as an own current
  fact and never replaces or enters the external competitor p25/p50/p75 distribution.
- Ozon competitor and 1688 supplier price bands remain separated by source currency. No FX or
  client-side conversion is performed.
- Supplier checkout comparison freezes the requested target purchase quantity. A 100-unit
  checkout/MOQ row remains an alternative and cannot enter the 3-unit first-Pilot price band.
- Source grade, semantic authority, Evidence IDs, observed time and freshness are frozen on each
  cohort. Stale, disallowed-grade, unresolved or key-mismatched rows are counted as gaps rather
  than silently used.
- The service creates no rank, candidate score, Supplier Offer, actual cost, formal CM3, Approval,
  Permit or external action.
- Commerce OS consumes the exact same service projection and renders no synthetic trend or local
  economics.

## Automated verification

```text
uv run python scripts/verify_secrets.py:
  PASS — 674 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

uv run pytest -q -p no:cacheprovider
  --basetemp=.runtime/pytest-bas118-final-20260728-1625:
  PASS — 704 passed

Focused API + Market Radar contract suite:
  PASS — 40 passed

uv run python scripts/export_openapi.py:
  PASS

OpenAPI SHA-256:
  014bc38e596be4eaeed224e670e82f55b398450eafcd9b35413343a0649a8b38
OpenAPI bytes:
  569209

git diff --check:
  PASS — line-ending notices only

npm ci:
  PASS — 0 vulnerabilities

npm test:
  PASS — 50 passed

npm run build:
  PASS — Next.js production build and TypeScript
```

Focused behavior tests prove:

- three Ozon seller listings for one exact variant produce one cohort, not three candidates;
- two variants of the same product produce two candidate keys/cohorts;
- own Listing price remains outside competitor p50;
- duplicate rows from one supplier preserve Evidence but count as one supplier identity;
- target quantity 3 excludes a 100-unit checkout/MOQ row from the supplier price band;
- RUB and CNY produce separate price bands;
- stale and disallowed-grade rows are disclosed but not scored;
- a candidate key that does not match its identity/variant is excluded;
- missing entity authority performs no Observation or Catalog read;
- fixed `as_of` produces a deterministic snapshot hash;
- invalid timezone/source-grade queries fail;
- anonymous access returns 401 and cross-store access returns 403;
- OpenAPI declares the protected GET contract.

## Database and migration boundary

BAS-118 adds no table or column. Alembic remains one head:

```text
current=head=20260728_0060
marketplace_observation_snapshots=26
marketplace_observation_items=49
native scoped snapshots=0
adapted snapshots=0
```

The frozen legacy Observation remains unchanged:

```text
snapshot:
  mos_893969993df54dc9ab0ead01c588a215
snapshot_sha256:
  91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1
Evidence:
  evd_294c9c496acb4c25bd74bccd92b18780
```

No database migration, stamp, backfill or real data mutation was performed for this slice.

## Live Compose and API acceptance

API, media-worker and Web images were rebuilt from the final source. The first combined build hit a
transient Docker Hub token EOF; a bounded retry succeeded without changing PostgreSQL.

```text
PostgreSQL: healthy
API: healthy
media-worker: healthy
Web: healthy

GET /health/ready:
  200
  status=ok
  version=0.59.0

anonymous GET /v1/market-radar:
  401

authenticated GET /v1/market-radar?store_ref=ozon-primary:
  200
  status=no_data
  tenant_ref=default
  entity_ref=null
  observed_listings=0
  unique_exact_identities=0
  source_gap=entity_scope_authority_missing
  external_write_allowed=false

unauthorized store:
  403

authenticated GET /v1/commerce-os/workspace:
  200
  market_radar.status=no_data
  market_radar counts all zero
  control_envelope.external_writes=false
```

The live database has 49 legacy Observation items, but they have no native tenant/entity/adapter
tuple and the current principal has no entity authority. Returning zero/no_data is therefore the
required result; the implementation did not use the global rows merely to make the dashboard look
populated.

## Browser acceptance

Artifacts:

- `output/playwright/release-0.59.0/scoped-market-radar-commerce-os-desktop.png`
  (`1440x1100`, SHA-256
  `93d1aa6e1d7480e0c0022ff675a179b5f50f0558e36a14f499ff9315bdb2ad0b`)
- `output/playwright/release-0.59.0/scoped-market-radar-commerce-os-mobile-390.png`
  (`390x844`, SHA-256
  `40c14fca0c5deb55c37e017dbdfa934cbb765bbecabbb773e93be08c4cd2b3d0`)

The live page rendered the server-owned no-data state, eight independent funnel counts and:

```text
同一商品先聚合 cohort，再进入候选
listing 数不冒充 SKU
100 件价不能筛 3 件 Pilot
Observation ≠ Offer / actual cost
销量推断：关闭
外部写入：关闭
```

Browser console errors and warnings were zero. Desktop and 390px both satisfied:

```text
documentElement.scrollWidth == documentElement.clientWidth
no horizontal overflow=true
```

At 390px the headed Windows Chromium values were `innerWidth=390`,
`clientWidth=scrollWidth=375`; the 15px difference is the native vertical scrollbar.

## Independent review

- Requirement/API/data/security/architecture/reliability review: no open P0 or P1 in BAS-118.
- `Info / no-op`: no current entity grant means the live Radar is correctly `no_data`; no
  production fact was invented to demonstrate a cohort.
- `Info / defer`: nationwide/full-market coverage, Seller API demand fields and scheduled
  incremental acquisition remain later M1 slices.
- `Info / defer`: display-currency rollup remains unavailable until Evidence-bound FX rows are
  present; price bands remain in their source currencies.
- `Info / no-op`: Market Radar is research-only and intentionally does not rank candidates or
  create formal economics.

## Gate boundary

- BAS-118 engineering, API, runtime and browser acceptance are complete.
- The M1 Release condition still requires a real scoped Observation replay. No entity grant or
  native scoped Observation currently exists.
- The 0.59 PM and RA **Release Gates remain REJECTED**.
- No Supplier Offer, full fifteen-component downside CM3, Approval, Permit, Ozon publication,
  order-triggered purchase, settlement or reconciled cash CM3 exists.
- Ozon, supplier messaging, procurement, payment, inventory, price and advertising external writes
  remain closed.
- Pricing remains `not_for_sale`.
