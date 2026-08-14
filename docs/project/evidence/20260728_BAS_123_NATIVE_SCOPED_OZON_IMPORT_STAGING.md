# BAS-123 Native Scoped Ozon Import Staging — Release Evidence

## Decision

`BAS-123` engineering acceptance is `PASS` for the native scoped staging boundary.
This does not approve formal Fact promotion, accounting posting, Ozon execution, or
any external write. Those paths remain closed.

## Requirement and implementation

- Requirement: `BR-099`
- Decision: `ADR-0047`
- Migration: `20260728_0065_native_scoped_ozon_imports.py`
- Authority module: `apps/control_plane/scoped_ozon_imports.py`
- API integration: `apps/control_plane/routers/finance_imports.py`
- Read projection: `apps/control_plane/commerce_operating_system.py`
- Contract tests: `tests/test_scoped_ozon_imports.py`

The native tuple is:

`tenant_ref + entity_ref + store_ref + scope_grant_authority_sha256 +
source_evidence_sha256 + scope_as_of`.

Legacy rows remain all-null and are never inferred into a tenant resource.
`formal_fact_promotion_allowed=false` and `external_write_allowed=false`.

## Verification observations

Observed on 2026-07-28 in `D:\KJDS\kjds` on
`feature/batch-opportunity-mining-059`.

### Static and test gates

- Full backend: `743 passed, 9 warnings in 30.71s`.
- Ruff: exit `0`, `All checks passed`.
- Secret scan: exit `0`; 698 non-ignored worktree files and 581 historical paths.
- `git diff --check`: exit `0` (line-ending warnings only).
- Web dependency audit: 39 packages, 0 vulnerabilities.
- Web tests: `50 passed`, 0 failed.
- Local production build: passed, 23 routes generated.
- OpenAPI export: exit `0`.

### Real PostgreSQL forward migration

Before migration the real database was `20260728_0064`; the sole repository head was
`20260728_0065`.

The frozen legacy ImportJob was:

- ID: `imp_76eab9701e954896a6f67ccdbb845cb6`
- file SHA-256:
  `489d4518e8e8c1f00c135cd1380ed636ff5e3ee1768182a9146b3cc4b1dcae68`
- Evidence: `evd_902fe12a454e4703b88b6ad7314ed652`
- status/type: `completed / ozon_accrual`

The migration was applied forward only: `0064 -> 0065`. The real database then
reported `20260728_0065 (head)`. The frozen row retained the same identity, content
hash, Evidence, status and type; all six native scope columns remained `NULL`.

Unrelated authority data remained unchanged. Pre/post counts and deterministic row
hashes matched:

| Table | Count | MD5 of deterministic row projection |
|---|---:|---|
| `read_only_claims` | 0 | `d41d8cd98f00b204e9800998ecf8427e` |
| `read_only_pilots` | 1 | `6b0b1c290f69c49bc15fc8239929383e` |
| `read_only_pilot_runs` | 1 | `c65a919bd688f95a595793427ecb6c53` |
| `evidence_records` | 58 | `c9cf4bd695bf653f9ea9ea90e80c32b2` |
| `lineage_edges` | 72 | `0d888f74b62fb22cee367a354c48c826` |
| `marketplace_catalog_items` | 1 | `660ed2671cd42ca5be739631a8384d6c` |
| `marketplace_catalog_snapshots` | 1 | `88a4255079aafa9ac02dffc511431cf7` |
| `catalog_read_run_handoffs` | 0 | `d41d8cd98f00b204e9800998ecf8427e` |

### Delivery containers and live API

API, media-worker and Web images were rebuilt from the current source. PostgreSQL,
API, media-worker and Web all became healthy. The production API image reported
`0065 (head)` and imported `apps.control_plane.api` successfully.

Live observations:

| Probe | Result |
|---|---|
| anonymous import detail | `401` |
| anonymous finance review | `401` |
| unauthorized store | `403` |
| exact configured store with no current entity grant | `422` |
| upload with no current entity grant | `422`, before mutation |
| Commerce OS scoped workspace | `200` |
| legacy import exposed as tenant resource | no |
| native scoped imports | `0`, `no_data` |
| formal Fact promotion | `false` |
| external write | `false` |

The real database contains no `scope_grant_events`; therefore an authenticated
exact-store import cannot truthfully be reported as readable. The fail-closed `422`
and the server-derived `entity_scope_authority_missing` state are the accepted real
observation, not a synthetic grant.

### Browser acceptance

The rebuilt `http://localhost:3000/commerce-os` was observed in the in-app browser.

- Desktop viewport: `1440x900`; document width equalled client width; no horizontal
  overflow; no page console warnings/errors.
- Mobile viewport: `390x844`; document/client width `375`; no oversized elements;
  no page console warnings/errors.
- The page displayed `Entity no_data`, zero native imports, legacy non-inference,
  formal promotion false and external write false.
- Desktop full-page and mobile viewport captures were observed. The browser's mobile
  full-page capture returned a blank artifact even though the DOM, element geometry
  and normal viewport capture were populated; acceptance therefore relies on the
  normal mobile viewport capture plus DOM/overflow observation, not that defective
  full-page artifact.

## Review findings

- `P0 auto-fix`: none.
- `P1 defer to BAS-124`: native scoped formal Fact/PromotionRun authority is absent
  by design and remains fail-closed.
- `P1 external-input blocker`: no current real entity/store grant exists, so native
  tenant import reads correctly remain `no_data`.
- `Info`: test warnings are third-party deprecations in Starlette/httpx and Python
  sqlite adapters; they do not change this staging boundary.

## Boundary

This Evidence closes only the BAS-123 engineering slice. Release/Pilot/Final Gates,
real SKU evidence, independent business review, settlements, bank reconciliation and
actual-cash CM3 remain open.
