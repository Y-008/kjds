# BAS-121 Native Scoped Ozon Read Pilot/Run Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirement: BR-097<br>
Architecture:
[ADR-0045](../../adr/ADR-0045-native-scoped-ozon-read-pilots.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

KJDS no longer exposes the Ozon read-only Pilot and Run ledgers as global ID-addressable
resources.

- Every newly created native Pilot freezes the authenticated Principal's `tenant_ref`, an
  independently granted `entity_ref`, an exact authorized `store_ref`, the current scope-grant
  hash, independently scoped Evidence authority hash and deterministic `scope_as_of`.
- The historical Pilot and its Run remain complete, unchanged legacy rows with an empty scope
  tuple. Tenant APIs do not infer tenant, entity or store from those rows and do not return them.
- Pilot create/list/get/evaluate, attestation, review-request, review and activation resolve the
  same scope before reading or mutating the Pilot.
- Run start/complete/Evidence capture/checkpoint/finalize/list/get/usage resolve the parent Pilot
  in the same scope first. Run reads join Pilot scope in SQL before serialization; knowing a Pilot
  or Run ID grants no authority.
- Lifecycle mutations revalidate the current grant, the frozen Pilot authority and current,
  intact, independently scoped Evidence. The scoped reaper receives only the authorized Pilot ID
  set.
- The read-run-to-Catalog handoff now resolves its Run through this authority before accessing
  raw Evidence or Catalog.
- Commerce OS projects the native scoped Pilot/Run state separately, explicitly says that legacy
  rows are not inferred, and keeps the missing entity authority as `no_data`.

This slice executes only the already implemented `ozon.product.read` and `ozon.finance.read`
contracts. It creates no Listing, Product binding, Supplier Offer, actual cost, Approval, Permit,
purchase, payment, price, inventory, advertising or other external write:

```text
external_write_allowed=false
legacy_rows_inferred=false
```

## API and OpenAPI

Authenticated and scope-filtered reads:

```text
GET /v1/read-only-pilots
GET /v1/read-only-pilots/{pilot_id}
GET /v1/read-only-pilot-runs
GET /v1/read-only-pilot-runs/{run_id}
```

The existing Pilot and Run lifecycle routes now perform the same scoped preflight before using
their underlying services.

Exported OpenAPI:

```text
version: 0.59.0
bytes: 584368
sha256: 2caa2149e9f28ba05e64186240b4d721c251522a1ea895a46e7dc7194c3d91b4
API-key security on all four read routes: true
```

Live API after the final image rebuild:

```text
anonymous Pilot list/get: 401 / 401
anonymous Run list/get: 401 / 401
authorized exact-store Pilot list: 200, status=no_data, rows=0
authorized exact-store Run list: 200, status=no_data, rows=0
entity_ref: null
external_write_allowed: false
unauthorized store: 403
Pilot create without entity authority: 422, zero new Pilot rows
Run start/reaper without entity authority: 422, zero new Run rows
```

The authenticated empty response is correct: the current Principal has no independently
established entity grant. `tenant_ref` is never copied into `entity_ref`.

## Automated verification

```text
uv run python scripts/verify_secrets.py:
  PASS — 687 non-ignored worktree files and 581 historical paths checked

uv run ruff check .:
  PASS

focused Pilot/Run/handoff/security suite:
  PASS — 43 passed before the complete scoped and Commerce OS regression sets

uv run pytest -q -p no:cacheprovider:
  PASS — 730 passed, 9 warnings

git diff --check:
  PASS — line-ending notices only

npm ci:
  PASS — 0 vulnerabilities

npm test:
  PASS — 50 passed

npm run build:
  PASS — Next.js 16.2.11 production build
```

Tests prove:

- native create freezes current scope and scoped Evidence authority;
- same-scope idempotent replay returns one Pilot, while authority drift conflicts;
- SQL filtering excludes legacy and cross-tenant Pilot/Run rows before serialization;
- missing entity authority causes no Pilot, Run or Evidence database read;
- unbound, cross-scope, bad or expired Evidence creates no native Pilot;
- changed grants and expired Evidence block later lifecycle operations;
- reaping changes only runs under authorized Pilot IDs;
- database constraints reject partial native scope tuples and same-scope duplicate keys while
  preserving independent cross-tenant keys;
- anonymous access is 401, unauthorized stores are 403 and missing entity authority is fail
  closed;
- Commerce OS projects server state and does not reconstruct scope or readiness in the client.

## PostgreSQL migration acceptance

Migration `20260728_0063` adds the complete-or-empty Pilot scope tuple, authority constraints,
native scope index and separate partial uniqueness for legacy and native idempotency.

Independent Compose PostgreSQL database `kjds_migration_0063_20260728_1`, using an explicit
guarded `KJDS_DATABASE_URL`:

```text
base -> 0063: PASS
0063 -> 0062 -> 0063: PASS
single head: 20260728_0063
same native key in different tenant/entity/store scopes: accepted
same-scope native duplicate: rejected
partial native authority tuple: rejected
duplicate legacy key: rejected
```

The real database was upgraded forward only from `0062` to `0063`; it was not downgraded for this
slice. Final preservation:

```text
Alembic current/head: 20260728_0063 / 20260728_0063
read_only_pilots: 1
read_only_pilot_runs: 1
Evidence / lineage edges: 58 / 72
Marketplace Catalog snapshots: 1
read-run Catalog handoffs: 0

legacy Pilot:
  id=rop_94223e8e17cc4ea2b0657fa76aefb98b
  idempotency=ozon-r0-offer-2105343364UB-20260724
  status=active
  tenant/entity/store=NULL/NULL/NULL

legacy Run:
  id=ror_fddfb7596d18465ab7ee0b44d2ced006
  pilot=rop_94223e8e17cc4ea2b0657fa76aefb98b
  status=completed
  request=0f3df8b54d468dea526129580d631a8d41d17ccb6768c8278e63103438f5ada7
  response=0726c9b7d214675327790737c4632b6f07ceb2ddf558027b4b03198e3f1e155e
  summary Evidence=evd_3154e484064744ff8b7f447cda40acde
```

## Compose and browser acceptance

Final source images:

```text
PostgreSQL: healthy
API: healthy
media-worker: healthy
Web: healthy
GET /health/ready: 200
service version: 0.59.0
database.status: ok
Alembic current/head: 20260728_0063
```

Browser artifacts:

- `output/playwright/release-0.59.0/bas121-native-scoped-read-pilots-desktop.png`
  (`1440px`, SHA-256
  `af09e1a12a1db43fdd7771cf9269e8c81745fd56d8a40bbc5e93c85b2ada980d`)
- `output/playwright/release-0.59.0/bas121-native-scoped-read-pilots-mobile-390.png`
  (`390x844`, SHA-256
  `e6aca81255cdb753090186ede0f2ed3c160c437638e83b733c2f5b60538804c8`)

All eight recorded application requests returned 200. Browser console errors and warnings were
zero.

```text
desktop inner/client/scroll/body width: 1440 / 1440 / 1440 / 1440
mobile inner/client/scroll/body width: 390 / 390 / 390 / 390
mobile horizontal overflow: false
```

The UI visibly renders `Ozon 只读 Pilot / Run`, `legacy 不推断` and the missing entity authority;
it does not present the historical legacy row as an authorized tenant resource.

## Gate boundary

BAS-121 is engineering-complete. The 0.59 PM/RA Release Gates remain `REJECTED`; no Pilot or Final
Gate has passed. This slice does not approve a real Ozon Pilot or listing. Ozon, supplier,
purchasing, payment, price, inventory and advertising external writes remain closed, and pricing
remains `not_for_sale`.
