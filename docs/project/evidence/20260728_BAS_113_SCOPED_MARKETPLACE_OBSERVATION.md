# BAS-113 Scoped Marketplace Observation Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirements: BR-089<br>
Architecture: [ADR-0038](../../adr/ADR-0038-postgresql-rls-and-scoped-read-model-envelope.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

Authenticated Marketplace Observation reads now use one explicit
Principal/tenant/entity/store/`as_of` authority envelope instead of returning a global array.

- `ScopedMarketplaceObservationAuthority` resolves the exact current entity grant before any raw
  Observation read. Missing or blocked entity authority returns `no_data`/`blocked` without
  calling the raw workspace.
- Database reads apply exact store and cutoff before current-fact de-duplication and pagination.
  Legacy `store_ref=external`, another store and future rows are never merged into the requested
  tenant/store projection.
- A returned item must have current, intact Evidence that is either directly scoped or connected
  through the current A-level target-ID/hash binding contract. Binding discovery is a bounded
  Evidence query, not a global list scan.
- Rejected rows expose only aggregate counts and reason codes. Product, supplier, price, URL,
  Evidence ID and an excluded row's cursor are not returned.
- List and page endpoints share one deterministic envelope with scope/Evidence authority hashes,
  Owner/SLA/next action and `external_write_allowed=false`.
- Browser capture remains a research Observation. It does not create entity authority, Supplier
  Offer, actual cost, Catalog readiness or external-write permission.
- Legacy Portfolio Pilot and Batch scan mutations now fail closed until scoped Catalog/economics
  adapters exist. Batch latest returns a truthful pending/no-data envelope instead of relabeling a
  global run.
- The Web Pilot workspace consumes only the scoped envelope. At the current real `no_data` state,
  candidate scoring stays disabled and the UI says why; “approval allocation” and a real Pilot are
  not presented as the same stage.

## Verification

```text
Focused Marketplace Observation authority/API suite:
  PASS — 49 passed

uv run python scripts/verify_secrets.py:
  PASS — 653 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local:
  PASS — 654 passed, one existing Starlette deprecation warning

npm ci:
  PASS — 0 vulnerabilities

npm test:
  PASS — 50 passed

npm run build:
  PASS — Next.js production build and TypeScript

OpenAPI:
  regenerated from runtime and matched the checked-in snapshot

git diff --check:
  PASS — line-ending notices only
```

Negative coverage proves:

- missing entity authority does not call the raw Observation service;
- cross-store, legacy `external`, future, unbound, cross-scope and damaged Evidence rows do not
  enter the projection;
- excluded identifiers and cursors do not leak;
- fixed `as_of` runs are deterministic;
- anonymous access is `401` and a Principal requesting an unauthorized store is `403`.

## Live Compose evidence

API, Web and media-worker images were rebuilt from the current source state. PostgreSQL, API, Web
and media-worker were healthy:

```text
GET /health/ready:
  200, status=ok, version=0.59.0, database.status=ok

GET /:
  200

Alembic current/head:
  20260728_0057 / 20260728_0057

GET /v1/marketplace-observations without identity:
  401

GET /v1/marketplace-observations for unauthorized-store:
  403

GET /v1/marketplace-observations
  marketplace=1688, store_ref=ozon-primary:
  200, status=no_data, items=0,
  source_gaps=[observation_entity_scope_authority_missing],
  external_write_allowed=false

GET /v1/batch-opportunities/latest?store_ref=ozon-primary:
  200, status=no_data,
  source_gaps=[entity_scope_authority_missing],
  external_write_allowed=false
```

The current database contains 26 Observation snapshots and 49 items; these totals are historical
records, not tenant/store-visible candidate counts. The frozen three-item snapshot remained
byte-identical after API and browser smoke:

```text
snapshot:
  mos_893969993df54dc9ab0ead01c588a215
snapshot_sha256:
  91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1
Evidence:
  evd_294c9c496acb4c25bd74bccd92b18780
item_sha256:
  2f18ac875e737eba84987f279f6eb4ea9f5a9a2c95f448ed7833cc4c30b74504
  5d652608a84aed15f603d6a25ec43612f05057752d7fd7724e71a84c24566171
  69c79e876f3a2c9c17688e11b25a467014596bb7efec592a298e918838f3fe92
```

## Browser acceptance

Artifacts:

- `output/playwright/release-0.59.0/scoped-observation-desktop.png`
- `output/playwright/release-0.59.0/scoped-observation-mobile-390.png`

The running Web rendered the scoped no-data message and kept “生成服务端排序” disabled.
At the explicit mobile override:

```text
innerWidth=390
documentElement.scrollWidth=390
body.scrollWidth=390
candidate scoring button disabled=true
notice=店铺 ozon-primary 暂无通过作用域 Evidence 的 1688 观察，不能生成候选排序。
```

The in-app browser applies privacy masking to identity and interactive surfaces in its high-DPI
image capture. Therefore the 390 screenshot is retained as an artifact, while the DOM bounds,
computed styles, no-horizontal-overflow equality and service-owned disabled state are the
authoritative responsive checks; the masked image is not used alone to claim visual correctness.

## PostgreSQL RLS boundary

Both `marketplace_observation_snapshots` and `marketplace_observation_items` currently report:

```text
relrowsecurity=true
relforcerowsecurity=false
policy_count=0
```

This is **not** effective database isolation and is not reported as completed RLS. ADR-0038 keeps
native tenant/entity/store tuple migration, non-owner/non-`BYPASSRLS` application role,
deny-by-default policies, connection-pool reset/cross-request tests and `FORCE ROW LEVEL SECURITY`
as a later forward-only release condition. No default ownership backfill is allowed.

## Review findings

- P0 — closed: authenticated reads could union `external` and requested-store rows before
  de-duplication.
- P0 — closed: missing entity authority could still read raw Observation rows and hide them only
  after the fact.
- P0 — closed: excluded Evidence IDs/item IDs could leak through details or page cursors.
- P1 — open: native PostgreSQL RLS remains pending under ADR-0038.
- P1 — open: Catalog, Batch Opportunity and economics require equivalent scoped authorities before
  candidate scoring can be re-enabled.
- Release status remains unchanged: 0.59 PM/RA Release Gates are `REJECTED`, Pilot/Final Gates are
  not passed, external Ozon/supplier/procurement/payment/advertising writes remain closed, and
  pricing is `not_for_sale`.
