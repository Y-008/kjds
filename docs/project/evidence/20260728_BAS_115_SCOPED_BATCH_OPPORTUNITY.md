# BAS-115 Scoped Batch Opportunity and Economics Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirements: BR-091<br>
Architecture: [ADR-0039](../../adr/ADR-0039-scoped-batch-opportunity-and-economics.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

Authenticated Batch Opportunity routes now use `ScopedBatchOpportunityAuthority`.

- Principal store authorization and the append-only entity grant resolve before any Observation,
  Catalog, FX or raw Batch read. Missing entity authority returns `no_data` on GET and 409 on POST
  with zero run/task creation.
- The input collector reads only the requested store and `as_of` through
  `ScopedMarketplaceObservationAuthority`; legacy `external` rows are not republished into a
  tenant.
- Own listing identity comes only from the scoped Catalog. External Ozon rows remain competitor
  cohort facts and cannot become the store's sale price.
- All nested checkout, fee, logistics and fifteen-component cost Evidence plus required FX
  Evidence are re-projected to the exact tenant/entity/store. Invalid or conflicting Evidence
  blocks before scoring.
- Non-CNY economics use a frozen effective/recorded-before-`as_of` FX map. The scoped evaluator
  cannot fall back to global finance rows.
- The persisted run freezes grant, Observation, Catalog, economics and combined Evidence hashes.
  Scoped idempotency is tenant/entity/store-local; changed payload or authority conflicts.
- A successful result is `ready_with_constraints` internal research only. Supplier Offer,
  actual cost, formal CM3, independent Approval, one-time Permit, Pilot, purchase, payment,
  advertising and Ozon write flags remain false.

The current real database contains only legacy/global market observations and no current entity
grant for `ozon-primary`. The live scoped API therefore returns zero candidates. That is the
correct fail-closed operating result; no observed page price was promoted into an Offer, cost or
profit claim.

## Automated verification

```text
Focused scoped Batch/Observation/Catalog/Commerce/API suite:
  PASS — 88 passed

Full backend:
  PASS — 673 passed

uv run python scripts/verify_secrets.py:
  PASS — 660 non-ignored worktree files and 581 historical paths checked

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

The first Web build was started concurrently with `npm ci` and temporarily failed while
`node_modules` was being replaced. After `npm ci` completed, the required ordered `npm run build`
passed. This was an orchestration race, not an accepted product failure.

Negative tests prove:

- missing entity authority reads no child/raw source;
- anonymous access is 401 and an unauthorized store is 403;
- missing entity POST is 409 and creates no research run;
- bad component Evidence and damaged Catalog authority fail before Batch execution;
- missing scoped RUB/CNY FX returns `no_data` and global FX is never read;
- a complete CNY input freezes all scope hashes and still creates only an internal research run;
- a selected FX row and its Evidence enter the frozen evaluator input;
- a partial database scope tuple is rejected;
- two tenants may use the same store/idempotency text independently, while a duplicate within
  one tenant/entity/store is rejected.

## Migration replay and PostgreSQL bypass checks

Alembic has one head: `20260728_0058`.

An isolated PostgreSQL database completed:

```text
base -> 20260728_0058
20260728_0058 -> 20260728_0057 -> 20260728_0058
```

At 0058, PostgreSQL contained:

```text
CHECK:
  ck_batch_opportunity_run_scope_complete

indexes:
  uq_batch_opportunity_run_legacy_idempotency
  uq_batch_opportunity_run_scoped_idempotency
  ix_batch_opportunity_run_scope_as_of
```

A direct SQL insert with only `tenant_ref` failed the CHECK. Direct inserts for two distinct
tenant/entity tuples with the same store/key succeeded; a repeated tuple failed the scoped unique
index. The temporary database was removed after replay.

Before the real forward migration:

```text
Alembic current: 20260728_0057
Observation items: 49
Observation snapshots: 26
Batch Opportunity runs: 19
Observation item Evidence FK missing: 0
item aggregate SHA-256:
  1648cf9b2d67032e03978c9809efdf1d49b0cdd9fdec7f827fb841b093b50e36
snapshot aggregate SHA-256:
  c66aab3bf787985d3d1b0cc1c6349ad05f884f4ccf4bfb202738be2370146687
```

After the sole real migration `0057 -> 0058`, all counts and both hashes were identical. The 19
legacy Batch runs remain complete legacy tuples; scoped runs remain 0. No Observation row,
snapshot, item hash or Evidence FK changed.

## Live Compose and API

The API and media-worker images were rebuilt from the current source. BuildKit encountered a
temporary dependency-download failure; the local classic builder retried the same locked
dependencies and completed successfully. No dependency version was changed.

```text
PostgreSQL: healthy
API: healthy
Web: healthy
media-worker: healthy

GET /health/ready:
  200
  version=0.59.0
  database.status=ok

container Alembic current/head:
  20260728_0058 / 20260728_0058

OpenAPI:
  POST /v1/batch-market-scans
  GET /v1/batch-opportunities/latest
  GET parameters include store_ref and as_of

anonymous GET /v1/batch-opportunities/latest:
  401

unauthorized store:
  403

authenticated GET store_ref=ozon-primary:
  200
  contract_id=kjds-scoped-batch-opportunity-v1
  status=no_data
  entity_ref=null
  source_gaps=[entity_scope_authority_missing]
  candidates=0
  scoped_input_read=false
  external_write_allowed=false

authenticated POST with missing entity:
  409
  Batch runs before/after=19
  scoped Batch runs=0
```

## Browser acceptance

Artifacts:

- `output/playwright/release-0.59.0/scoped-batch-opportunity-commerce-os-desktop.png`
- `output/playwright/release-0.59.0/scoped-batch-opportunity-commerce-os-mobile-390.png`

The running Commerce OS rendered:

```text
Entity=no_data
exact identities=0
fully costed candidates=0
downside-positive=0
external writes closed=true
entity_scope_authority_missing visible
browser console errors=0
```

At the explicit mobile viewport:

```text
innerWidth=390
documentElement.scrollWidth=390
body.scrollWidth=390
```

Both screenshots were visually inspected. The desktop and mobile surfaces show the same real
empty/governance state without synthetic candidate counts, prices, profit curves or horizontal
overflow.

## Review findings and remaining gates

- `P0`: none in the scoped Batch slice.
- `P1/defer`: PostgreSQL native tenant/entity columns plus non-owner, deny-by-default and FORCE
  RLS for Observation/Catalog remain an ADR-0038 Release Gate.
- `P1/defer`: Catalog/Observation facts currently lack a reviewed entity publication authority,
  so live candidate throughput correctly remains zero.
- `P1/defer`: content/passport, independent Approval, frozen execution plan, one-time Permit,
  Readback, Kill Switch/Compensation and actual settlement remain later M1-M3 gates.

BAS-115 engineering is complete. The 0.59 PM/RA Release Gates remain `REJECTED`; Pilot and Final
Gates are not passed. Pricing remains `not_for_sale`. No Ozon, supplier, purchase, payment or ads
external write was enabled or executed.
