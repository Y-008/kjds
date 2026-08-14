# BAS-120 Ozon Read-Run to Catalog Handoff Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirement: BR-096<br>
Architecture:
[ADR-0044](../../adr/ADR-0044-ozon-read-run-catalog-handoff.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

KJDS now has a durable internal seam between the existing official Ozon product read worker and
the native scoped Marketplace Catalog.

- `CatalogReadRunHandoffService` accepts only one completed, successful
  `ozon.product.read` run whose unique raw response Evidence still passes the original two-response
  integrity verifier.
- A client submits only `run_id`, `store_ref` and `idempotency_key`. Tenant, entity, current grant,
  scoped Evidence authority, adapter identity/version and source contract are resolved and frozen
  by the server.
- The PostgreSQL ledger has `prepared`, `completed` and deterministic `blocked` states. An
  infrastructure interruption leaves `prepared` for exact replay; a changed run, grant, Evidence
  authority or adapter registry under the same key conflicts.
- Catalog import uses a handoff-derived idempotency key and records the immutable resulting
  Catalog snapshot ID/hash.
- List and detail queries filter tenant/entity/store in SQL before serialization.
- The handoff does not read Ozon, bind a Product, create a Supplier Offer or actual cost, draft or
  publish a Listing, create Approval/Permit, or perform price, inventory, purchasing, payment,
  advertising or any other external write.

Every response states:

```text
external_write_allowed=false
automatic_product_binding=false
approval_created=false
permit_created=false
```

## API and OpenAPI

Authenticated routes:

```text
POST /v1/marketplace-catalog/ozon/import-read-run
GET  /v1/marketplace-catalog/ozon/read-run-handoffs
GET  /v1/marketplace-catalog/ozon/read-run-handoffs/{handoff_id}
```

Exported OpenAPI:

```text
version: 0.59.0
bytes: 574819
sha256: e3b7862ce9228fd32194c597b07806af5a5125bc10991551a791172782fb2327
all three routes present: true
API-key security on all three routes: true
```

Live API after the final container rebuild:

```text
anonymous list: 401
anonymous import: 401
authenticated exact-store list: 200
list status: no_data
entity_ref: null
external_write_allowed: false
unauthorized store: 403
import without entity grant: 422
handoff rows after rejected import: 0
Catalog snapshot rows after rejected import: 1
```

The empty state is required. A real product read response exists, but the current Principal has no
independently established entity grant. BAS-120 does not copy `tenant_ref` into `entity_ref` or
invent a scope binding.

## Automated verification

```text
uv run python scripts/verify_secrets.py:
  PASS — 682 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

focused handoff/Catalog/scoped Catalog/adapter suite:
  PASS — 47 passed

uv run pytest -q -p no:cacheprovider:
  PASS — 722 passed

git diff --check:
  PASS — line-ending notices only

npm ci:
  PASS — 0 vulnerabilities

npm test:
  PASS — 50 passed

npm run build:
  PASS — Next.js 16.2.11 production build
```

Focused tests prove:

- successful replay creates one Catalog snapshot;
- the same key conflicts after run, grant or adapter-registry drift;
- tenant/entity scopes are independent;
- finance and failed runs create no handoff;
- missing entity authority stops before run/Evidence/Catalog reads;
- deterministic Catalog rejection is auditable `blocked`;
- infrastructure failure remains `prepared` and succeeds on exact retry even when `as_of` advances;
- list/get cannot cross scope;
- missing entity list is `no_data` without a raw database read;
- anonymous access is 401 and unauthorized store access is 403.

The outbox coverage registry classifies this module as a `polling_contract` using the explicit
scoped idempotent resume API. It does not claim a new event bus or background workflow.

## PostgreSQL migration acceptance

Migration `20260728_0062` adds the handoff ledger, scoped uniqueness, authority/state CHECKs and
foreign keys to read run, raw Evidence and Catalog snapshot.

Independent Compose PostgreSQL database `kjds_migration_0062_20260728_1` using the explicit
`KJDS_DATABASE_URL`:

```text
base -> 0062: PASS
0062 -> 0061 -> 0062: PASS
single head: 20260728_0062
partial authority tuple: rejected
invalid completed/result state: rejected
same-scope duplicate idempotency key: rejected
missing read-run foreign key: rejected
same key in a different entity scope: accepted
```

### Execution deviation and verified recovery

The first replay command incorrectly set `DATABASE_URL`. Alembic reads `KJDS_DATABASE_URL`, so that
variable was ignored and the command hit the configured real database. The real database
temporarily ran `0062 -> 0061 -> 0062` before the mistake was detected. The 0062 handoff table was
empty during that round trip. This is an execution-policy deviation and is recorded here rather
than described as a forward-only real migration.

Immediate before/after recovery checks found no business-row or frozen-hash change:

```text
real Alembic current/head: 20260728_0062
catalog_read_run_handoffs: 0
marketplace_catalog_snapshots: 1
Catalog snapshot:
  mcs_2b9eae9e7ebb49b08fe7421fc63d7cb1
  6aac2e817f3637a0efeff0ee815ad9115d55cb65b0f2f069a09eb1b75d1990b0
marketplace_observation_snapshots/items: 26 / 49
Evidence / lineage edges: 58 / 72
read_only_pilots / read_only_pilot_runs: 1 / 1
read run:
  ror_fddfb7596d18465ab7ee0b44d2ced006
  completed / succeeded
  request=0f3df8b54d468dea526129580d631a8d41d17ccb6768c8278e63103438f5ada7
  response=0726c9b7d214675327790737c4632b6f07ceb2ddf558027b4b03198e3f1e155e
raw grade-A Evidence:
  evd_dc94091bb94d490ba8866caad7548415
  0726c9b7d214675327790737c4632b6f07ceb2ddf558027b4b03198e3f1e155e
summary grade-B Evidence:
  evd_3154e484064744ff8b7f447cda40acde
  4d5852a70f90c7bf8bbfe6b4993583c6c2e36d58b8731adabd47cbc489cf4654
orphaned Marketplace Observation Evidence refs: 0
```

All subsequent migration replay commands used `KJDS_DATABASE_URL` and targeted only the named
independent database. No real database downgrade is authorized for later slices.

## Compose and browser acceptance

Final images were rebuilt from the current source:

```text
PostgreSQL: healthy
API: healthy
media-worker: healthy
Web: healthy
GET /health/ready: 200
service version: 0.59.0
database.status: ok
Alembic current/head: 20260728_0062
```

Browser artifacts:

- `output/playwright/release-0.59.0/bas120-catalog-handoff-commerce-os-desktop.png`
  (`1440x1100`, SHA-256
  `b846fe9f7b11c696d0bebc074a7a9701351666850e1b6820d8bee5d19a7de923`)
- `output/playwright/release-0.59.0/bas120-catalog-handoff-commerce-os-mobile-390.png`
  (`390x844`, SHA-256
  `5355075d77fc261fe44f4a7e84daa0b03c5fdb5caacd8da66a5e5f5b09675759`)

All ten application requests returned 200 and browser console errors/warnings were zero.

```text
desktop inner/client/scroll/body width: 1440 / 1440 / 1440 / 1440
mobile inner/client/scroll/body width: 390 / 390 / 390 / 390
mobile horizontal overflow: false
```

The page continues to render source gaps and `external writes closed`; it does not present an empty
handoff as a live Catalog import or an Ozon listing.

## Gate boundary

BAS-120 is engineering-complete. This does not approve the 0.59 PM/RA Release Gates, a real Pilot,
or the Final Gate. A real completed native handoff still requires current entity authority and
independently scoped original Evidence. Ozon/supplier/purchasing/payment/price/inventory/advertising
external writes remain closed, and pricing remains `not_for_sale`.
