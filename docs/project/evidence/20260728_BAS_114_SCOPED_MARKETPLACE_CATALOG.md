# BAS-114 Scoped Marketplace Catalog Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirements: BR-090<br>
Architecture: [ADR-0038](../../adr/ADR-0038-postgresql-rls-and-scoped-read-model-envelope.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

Authenticated PIM/Catalog reads now use `ScopedMarketplaceCatalogAuthority` instead of returning
the raw store array.

- Principal store authorization and one append-only entity grant are resolved before any raw
  Catalog read. Missing entity authority returns `no_data` without touching raw rows.
- Raw SQL and memory adapters apply exact store, snapshot `imported_at`, item `observed_at` and
  explicit `as_of` before offer-level latest-fact de-duplication. A canonical binding is visible
  only when `bound_at <= as_of`.
- Every returned item requires current, intact Evidence with independent direct scope or grade-A
  target-ID/hash binding to the exact tenant/entity/store.
- Excluded rows expose only aggregate counts and reason codes. Offer, SKU, product, price, media,
  Evidence ID and item hash are not disclosed.
- Catalog import, existing-listing binding and Catalog-backed RFQ creation execute the same scope
  preflight before mutation.
- Scoped Operating Analytics and Commerce OS consume the scoped Catalog envelope. They do not
  fall back to `marketplace_catalog.latest_items`.
- The contract keeps `candidate_scoring_allowed=false`, `content_draft_allowed=false`,
  `pilot_approval_allowed=false` and `external_write_allowed=false`.

The real raw database currently has one `ozon-primary` Catalog item. The authenticated scoped API
returns zero items because no formal entity grant/Evidence binding exists. This is the intended
fail-closed result, not loss or relabelling of the raw record.

## Verification

```text
Focused Catalog/Analytics/API suite:
  PASS — 56 passed

Full backend:
  PASS — 662 passed, one existing Starlette deprecation warning

uv run python scripts/verify_secrets.py:
  PASS — 656 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

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

Negative tests prove:

- missing entity authority does not call raw Catalog;
- a Principal cannot read an unauthorized store;
- unbound, cross-tenant/entity and damaged Evidence rows do not enter the projection;
- excluded business identifiers and Evidence IDs do not leak;
- fixed `as_of` is deterministic;
- a future snapshot and future Product binding cannot rewrite a historical decision;
- unbound import Evidence cannot create a Catalog snapshot;
- missing entity authority blocks Catalog import and existing-listing binding before raw mutation;
- scoped Analytics can project authorized Catalog facts while all other legacy sources remain
  unread;
- anonymous Catalog access is `401` and an unauthorized store is `403`.

## Live PostgreSQL and Compose

The API and media-worker images were rebuilt from the current source and all four services became
healthy. The first BuildKit metadata request received a temporary Docker Hub EOF; a retry using the
local/classic builder completed successfully. `.runtime`, generated `output`, `node_modules` and
Web build output are excluded from the build context.

```text
PostgreSQL: healthy
API: healthy
Web: healthy
media-worker: healthy

GET /health/ready:
  200, version=0.59.0, database.status=ok

Alembic current/head:
  20260728_0057 / 20260728_0057

Raw internal exact-store/as_of SQL:
  query executed successfully
  returned=1, offer=2105343364UB

GET /v1/marketplace-catalog/items/latest without identity:
  401

GET /v1/marketplace-catalog/items/latest for unauthorized-store:
  403

GET /v1/marketplace-catalog/items/latest
  store_ref=ozon-primary, as_of=2026-07-28T04:00:00Z:
  200
  contract_id=kjds-scoped-marketplace-catalog-v1
  status=no_data
  items=0
  source_gaps=[catalog_entity_scope_authority_missing]
  external_write_allowed=false

GET /v1/operating-analytics/snapshot:
  status=no_data
  catalog_items=0
  catalog_entity_scope_authority_missing=true
  legacy_global_catalog is explicitly excluded

GET /v1/commerce-os/workspace:
  200, status=no_data
```

The frozen three-item Marketplace Observation snapshot remained byte-identical:

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

- `output/playwright/release-0.59.0/scoped-catalog-commerce-os-desktop.png`
- `output/playwright/release-0.59.0/scoped-catalog-commerce-os-mobile-390.png`

The running Commerce OS displayed the real server-owned state:

```text
Entity=no_data
observed listings=0
external writes closed=true
catalog_entity_scope_authority_missing is visible
browser console errors/warnings=0
/backend/v1/commerce-os/workspace=200
```

At the explicit mobile viewport:

```text
innerWidth=390
documentElement.scrollWidth=390
body.scrollWidth=390
```

The desktop and mobile screenshots were visually inspected. They render the same no-data and
governance semantics without synthetic Catalog counts or horizontal page overflow.

## PostgreSQL RLS boundary

The three Catalog tables currently report:

```text
marketplace_catalog_items:
  relrowsecurity=false, relforcerowsecurity=false, policy_count=0
marketplace_catalog_snapshots:
  relrowsecurity=false, relforcerowsecurity=false, policy_count=0
marketplace_product_bindings:
  relrowsecurity=false, relforcerowsecurity=false, policy_count=0
```

This is **not** database-enforced isolation. ADR-0038 keeps native tenant/entity/store tuple
migration, non-owner/non-`BYPASSRLS` application role, deny-by-default policies, pool reset tests
and `FORCE ROW LEVEL SECURITY` as later forward-only Release conditions. No default ownership
backfill is allowed.

## Release boundary

- BAS-114 engineering is complete; native PostgreSQL RLS remains open.
- Batch Opportunity and economics remain disabled until they consume scoped Catalog,
  Observation, fee, logistics and cost authorities.
- 0.59 PM/RA Release Gates remain `REJECTED`; Pilot and Final Gates are not passed.
- No Ozon, supplier, purchase, payment or advertising external write was enabled or executed.
- Pricing remains `not_for_sale`.
