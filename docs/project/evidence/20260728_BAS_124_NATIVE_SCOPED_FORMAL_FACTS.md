# BAS-124 Native Scoped Formal Facts — Release Evidence

## Decision

`BAS-124` engineering acceptance is `PASS` for the native scoped formal
Fact/PromotionRun boundary. The plan state is `DONE_ENGINEERING`.

This decision does not approve accounting posting, Approval, Permit, Ozon execution
or any external write. Release/Pilot/Final Gates and the real operating loop remain
open.

## Requirement and implementation

- Requirement: `BR-101`
- Decision: `ADR-0049`
- Migration: `20260728_0067_native_scoped_formal_facts.py`
- Deep module: `apps/control_plane/scoped_facts.py`
- Runtime and authenticated API:
  `apps/control_plane/runtime.py`,
  `apps/control_plane/routers/finance_imports.py`
- Legacy isolation:
  `apps/control_plane/facts.py`,
  `apps/control_plane/finance.py`,
  `apps/control_plane/profit_ledger.py`
- Commerce OS projection:
  `apps/control_plane/commerce_operating_system.py`
- Contract tests: `tests/test_scoped_facts.py`
- Web workspace:
  `web/app/formal-facts/page.tsx`,
  `web/features/formal-facts/formal-facts-console.tsx`

The native tuple is:

`tenant_ref + entity_ref + store_ref + scope_grant_authority_sha256 +
source_evidence_sha256 + scope_as_of`.

Native promotion accepts only a BAS-123 native scoped ImportJob under the exact
current Principal/entity/store grant. It independently revalidates current scoped
Evidence, source review, finance mapping/classification and one exact scoped
Product/SKU before opening the write transaction. A bare SKU, global Product,
ambiguous Product, bad Evidence, future authority or Claim ID fails closed with zero
Fact and PromotionRun writes.

Fact rows, their Evidence lineage and the PromotionRun commit in one transaction.
The request hash is scoped-idempotent; the same payload can be promoted independently
across tenants. Legacy all-null rows remain readable only through the legacy service
and are never inferred into an authenticated tenant resource. Native rows are
excluded from the legacy finance and global profit-ledger bypasses.

Every returned formal Fact states:

- `claim_promoted=false`
- `accounting_posted=false`
- `approval_created=false`
- `permit_created=false`
- `external_write_allowed=false`

## Migration verification

### Isolated PostgreSQL

- empty database → `0067`;
- `0067 → 0066 → 0067`;
- isolated database removed after verification.

### Real PostgreSQL forward migration

The real database moved forward only from `20260728_0066` to
`20260728_0067 (head)`.

Before migration:

- Fact count: `0`
- PromotionRun count: `0`
- retained legacy ImportJob:
  `imp_76eab9701e954896a6f67ccdbb845cb6`
- retained source SHA-256:
  `489d4518e8e8c1f00c135cd1380ed636ff5e3ee1768182a9146b3cc4b1dcae68`
- retained Evidence:
  `evd_902fe12a454e4703b88b6ad7314ed652`
- retained status/type: `completed / ozon_accrual`
- all six ImportJob native scope fields: `NULL`

After migration, Fact and PromotionRun counts remained zero. The new complete-or-null
checks and scoped indexes were present:

- `ix_fact_scope_recorded`
- `ix_promotion_run_scope_created`
- `uq_fact_scoped_import_contract`
- `uq_fact_scoped_source_payload`
- `uq_promotion_run_scoped_request`

Unrelated state was frozen before the migration and matched after it:

| Table | Count | MD5 of deterministic row projection |
|---|---:|---|
| `import_jobs` | 1 | `8197d4eb36401c8dff2a13e788987a49` |
| `import_rows` | 15 | `e82b8c910255d161e1e545ebbc3e7522` |
| `evidence_records` | 58 | `2605ef3130ae88ed304d4fdd630cb087` |
| `lineage_edges` | 72 | `d0c25646098fc26c990896c2172cd7ed` |
| `graph_projects` | 1 | `2d39b725adf18ac747cb928cd3f343c1` |
| `goal_tasks` | 6 | `54834f1987211d8339133402020cb79e` |
| `harness_observations` | 6 | `33d785ddbac6b60520ae633802506286` |
| `graph_nodes` | 13 | `831671f275ec558bace6c1151d9fd6f0` |
| `graph_edges` | 12 | `48572c9ef083837d2d0e3a7afbfdc18c` |

## Verification observations

Observed on 2026-07-28 in `D:\KJDS\kjds` on
`feature/batch-opportunity-mining-059`.

### Static, test and contract gates

- Full backend: `754 passed, 9 warnings in 29.59s`.
- Focused scoped Fact and API contract: `39 passed, 1 warning`.
- Ruff: `All checks passed`.
- Secret scan: `727` non-ignored worktree files and `581` historical paths,
  exit `0`.
- `git diff --check`: exit `0`; line-ending warnings only.
- Web tests: `55 passed`, `0 failed`.
- Web production build: passed; `33` routes generated, including
  `/formal-facts`.
- Web dependency audit: `0 vulnerabilities`.
- OpenAPI export: exit `0`; authenticated scoped Fact routes are present.
- Outbox registry classifies `scoped_facts.py` as internal-only.

The seven focused BAS-124 tests cover atomicity and replay, cross-tenant
independence, global/bad/Claim inputs, missing entity and future `as_of`, database
scope checks, legacy/finance bypass isolation, and API anonymous/cross-store/entity
security.

### Delivery containers

The current source was rebuilt before acceptance. PostgreSQL, API, media-worker and
Web were all externally healthy.

| Service | Container | Image SHA-256 |
|---|---|---|
| API | `392af2aa9702` | `b54b0fb6c1eefec278356be92161f145eedbf9b7338000889250a5995d75f263` |
| media-worker | `444cb847c7fd` | `d4179569cbc59cda4f4062ddb4ba75e2880df63d2d4ccbba8cd7228a9147e418` |
| Web | `b9ccaea1fb48` | `7cf2860f2ca056faf4b0ce13cde3555afa5d9d06ba202cac1f5223e7d9099b66` |

The API container reported `20260728_0067 (head)` and imported the application
successfully.

### Live API boundary probes

| Probe | Result |
|---|---|
| API readiness | `200` |
| anonymous `/v1/facts` | `401` |
| cross-store Fact list | `403` |
| exact-store Fact list | `422`, current entity required |
| exact-store Fact detail | `422`, current entity required |
| promote retained legacy ImportJob | `422`, current entity required before mutation |
| Commerce OS exact store | `200` |
| formal Fact state | `no_data`, count `0`, legacy fallback `false` |
| Claim/accounting/Approval/Permit/external write | all `false` |
| server-owned gap | `entity_scope_authority_missing` |

### Browser acceptance

The rebuilt `http://localhost:3000/formal-facts` was observed in the in-app browser.

- Desktop `1440x1000`: server state `blocked`; document, client, body and inner
  widths all `1440`; no horizontal overflow; no console warning/error.
- Mobile `390x844`: server state `blocked`; document, client, body and inner widths
  all `390`; no horizontal overflow; status rail bounded from left `12` to right
  `378` at width `366`; no console warning/error.
- Both viewports honestly displayed that the current entity could not be established;
  neither rendered legacy Facts nor claimed promotion success.

## Remaining boundary

The real database has no current entity grant and no native scoped Import/Product/
Fact chain. A live successful promotion was intentionally not fabricated. The
accepted observation is the fail-closed `entity_scope_authority_missing` state.

Therefore this Evidence closes only BAS-124 engineering. It does not close the
Release/Pilot/Final Gates, real SKU Evidence, independent business review,
settlement/bank reconciliation or actual-cash CM3. Accounting and every external
commerce write remain closed.
