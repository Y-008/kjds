# BAS-122 Native Scoped Read-Only Claims Evidence

Date: 2026-07-28<br>
Branch baseline: `feature/batch-opportunity-mining-059` at `b34a3a7` plus the current integrated
0.59 worktree<br>
Requirement: BR-098<br>
Architecture:
[ADR-0046](../../adr/ADR-0046-native-scoped-read-only-claims.md)<br>
Status: `DONE_ENGINEERING`

## Outcome

The Ozon read-only Claim bridge is now a native tenant/entity/store authority instead of a global
ID-addressable ledger.

- A new Claim can be proposed only from a Run already authorized by
  `ScopedReadOnlyPilotAuthority`.
- The Run summary Evidence must still be current, intact and independently bound to the same
  tenant/entity/store. The Claim freezes current grant hash, Evidence binding authority hash and
  deterministic `as_of`.
- Claim proposal, list, detail and review are owned by `ScopedReadOnlyClaimAuthority`.
- Claim → Run → Pilot is joined in SQL before serialization; all three must resolve to the same
  current grant and scope. Knowing a Claim, Run or Pilot ID grants no access.
- Review revalidates the parent Run/Pilot, current grant, frozen Evidence authority and independent
  reviewer before the pending Claim can move once to accepted or rejected.
- Same-scope retries converge even when transport time advances, provided the Run, payload, grant
  and Evidence authority are unchanged. The same client key is independent across tenant scopes.
- Legacy Claims retain an empty authority tuple and are never inferred or returned by tenant
  routes.
- Commerce OS exposes a separate `Ozon 只读 Claim 复核账` card and the server-owned count/status.

An accepted Claim remains a reviewed interpretation, not a business fact:

```text
formal_fact_promoted=false
external_write_allowed=false
approval_created=false
permit_created=false
```

Native scoped Claims are explicitly excluded from the legacy global listing before-state lookup.
This slice cannot publish or change Ozon price/inventory, message/order a supplier, purchase, pay
or advertise.

## API and OpenAPI

Authenticated and scoped routes:

```text
POST /v1/read-only-pilot-runs/{run_id}/claims
GET  /v1/read-only-claims
GET  /v1/read-only-claims/{claim_id}
POST /v1/read-only-claims/{claim_id}/review
```

Exported OpenAPI:

```text
version: 0.59.0
bytes: 586546
sha256: e5bb8a7658eb666fcbd0eee556cdc8392de391bb98243c37d7a06b2528f3ea6f
API-key security on all four operations: true
```

Live API after the final image rebuild:

```text
anonymous Claim list/get: 401 / 401
authorized exact-store list: 200
list status: no_data
Claim rows: 0
entity_ref: null
external_write_allowed: false
unauthorized store: 403
propose without entity authority: 422
review without entity authority: 422
Claim rows after both rejected mutations: 0
```

The empty state is correct. The authenticated Principal still has no independently established
entity grant, and BAS-122 does not copy `tenant_ref` into `entity_ref`.

Commerce OS live projection:

```text
contract: kjds-scoped-read-only-claims-v1
status: no_data
claims / pending / accepted / rejected / authority blocked: 0 / 0 / 0 / 0 / 0
source gap: entity_scope_authority_missing
legacy_rows_inferred: false
formal_fact_promoted: false
external_write_allowed: false
```

## Automated verification

```text
uv run python scripts/verify_secrets.py:
  PASS

uv run ruff check .:
  PASS

focused Claim/Pilot/Run/handoff/execution/Commerce OS suite:
  PASS — 46 passed

uv run pytest -q -p no:cacheprovider
  --basetemp=output/pytest/bas122-full-20260728-0912:
  PASS — 737 passed, 9 warnings

git diff --check:
  PASS — line-ending notices only

npm ci:
  PASS — 0 vulnerabilities

npm test:
  PASS — 50 passed

npm run build:
  PASS — Next.js 16.2.11 production build
```

The first full backend invocation reached 715 passing tests but could not create 21 `tmp_path`
fixtures because the user-level Windows pytest temporary root denied access; the OpenAPI snapshot
also correctly failed because the new query contract had not yet been exported. The OpenAPI
artifact was exported, and the complete suite was rerun with an isolated workspace-local
`--basetemp`, producing the final 737/737 result above. No failing result is reported as green.

Tests prove:

- native Claim creation freezes exact scope and independently scoped Evidence authority;
- idempotent replay returns the first immutable Claim;
- legacy and cross-tenant rows are excluded before serialization;
- missing entity authority returns `no_data` without Claim, Run or Evidence database reads;
- unbound Run Evidence creates no Claim;
- changed grant, expired Evidence and self-review all fail closed;
- same client key works independently across tenant scopes;
- the database rejects partial authority tuples and same-scope duplicates;
- accepted remains `formal_fact_promoted=false`;
- anonymous access is 401 and unauthorized store access is 403;
- Commerce OS and the Web client project the server contract without reconstructing authority.

## PostgreSQL migration acceptance

Migration `20260728_0064` adds the complete-or-empty Claim authority tuple, native scope index and
separate partial uniqueness for legacy and native idempotency.

Independent Compose PostgreSQL database `kjds_migration_0064_20260728_1`, using a guarded explicit
`KJDS_DATABASE_URL`:

```text
base -> 0064: PASS
0064 -> 0063 -> 0064: PASS
single head: 20260728_0064
same client key in different tenant/entity/store scopes: accepted
same-scope native duplicate: rejected
partial native authority tuple: rejected
duplicate legacy key: rejected
```

The running API image initially contained migrations only through 0063, so the first isolated
base replay truthfully stopped at that image's head. The 0064 migration artifact was copied into
the isolated API container, then the explicit 0064 upgrade/downgrade/upgrade acceptance above was
performed. This did not touch the real database.

The real database was upgraded forward only from `0063` to `0064`; no real downgrade occurred.
Before/after preservation:

```text
Alembic current/head: 20260728_0064 / 20260728_0064
read_only_claims / native Claims: 0 / 0
read_only_pilots / runs: 1 / 1
Evidence / lineage edges: 58 / 72
Marketplace Catalog snapshots: 1
read-run Catalog handoffs: 0

legacy Pilot:
  rop_94223e8e17cc4ea2b0657fa76aefb98b
  ozon-r0-offer-2105343364UB-20260724
  active
  tenant/entity/store=NULL/NULL/NULL

legacy Run:
  ror_fddfb7596d18465ab7ee0b44d2ced006
  pilot=rop_94223e8e17cc4ea2b0657fa76aefb98b
  completed
  request=0f3df8b54d468dea526129580d631a8d41d17ccb6768c8278e63103438f5ada7
  response=0726c9b7d214675327790737c4632b6f07ceb2ddf558027b4b03198e3f1e155e
  summary Evidence=evd_3154e484064744ff8b7f447cda40acde
```

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
Alembic current/head: 20260728_0064
```

Browser artifacts:

- `output/playwright/release-0.59.0/bas122-native-scoped-read-only-claims-desktop.png`
  (`1440px`, SHA-256
  `cc39abcba5da604fb9209f6d9b1191aa17669117c7564b8f02d40bfddd49b281`)
- `output/playwright/release-0.59.0/bas122-native-scoped-read-only-claims-mobile-390.png`
  (`390x844`, SHA-256
  `24463115e09d0dfd027f31f6dc9642a432e93d3bb4484f9d4adaa2cead96c1d0`)

All eight recorded application requests returned 200. Browser console errors and warnings were
zero.

```text
desktop inner/client/scroll/body width: 1440 / 1440 / 1440 / 1440
mobile inner/client/scroll/body width: 390 / 390 / 390 / 390
mobile horizontal overflow: false
```

The page visibly states that accepted Claims are not formal inventory or price facts and shows
`formal fact false · external write false`.

## Gate boundary

BAS-122 is engineering-complete. The 0.59 PM/RA Release Gates remain `REJECTED`; no Pilot or Final
Gate has passed. This does not approve a real Ozon Pilot or listing. Ozon, supplier, purchasing,
payment, price, inventory and advertising external writes remain closed, and pricing remains
`not_for_sale`.
