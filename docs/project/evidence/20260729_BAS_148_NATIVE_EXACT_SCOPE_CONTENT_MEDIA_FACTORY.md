# BAS-148 native exact-scope content media factory

- Date: 2026-07-29
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Business state: `no_data`
- External write: `false`
- Requirement: `BR-122`
- ADR: [ADR-0068](../../adr/ADR-0068-native-exact-scope-content-media-factory.md)

## Outcome

BAS-148 replaces the shallow, Router-composed media read with one deep module:

`ScopedContentMediaFactoryWorkspace.project(...)`.

The module composes existing exact-scope Product/content authority,
`ContentAsset`, the fixed template registry, PostgreSQL media executions,
append-only execution events and Delivery Manifests. It does not create a
second Product, ContentAsset, QA, execution, Manifest, Listing, Approval or
Permit truth store.

The canonical API is:

`GET /v1/media-factory/workspace`.

The existing `GET /v1/media/workbench` route delegates to the same projection
and remains response-compatible for current operating-intelligence consumers.
API, Web, Commerce OS and Agent projections no longer calculate media
readiness in Router or React.

## Deep-module boundary

### Exact scope before raw read

The module first validates:

- authenticated Principal;
- exact authorized store;
- current `tenant/entity/store` grant authority;
- timezone-aware `as_of`;
- the exact Product/content projection contract, scope, cutoff and hash.

Missing entity authority returns `no_data`; a malformed ready grant returns
`blocked`. Both paths perform zero Product, ContentAsset, execution, event or
Manifest reads.

Only the ContentAsset IDs already admitted by
`ScopedProductContentAuthority` are passed to
`MediaWorkbenchService.read_sources(...)`. That narrow read source applies the
ID set and cutoff in SQL before materializing:

- `content_assets`;
- `media_executions`;
- `media_execution_events`;
- `media_delivery_manifests`.

It reports independent truncation for each collection and never derives
tenant/entity authority from a caller-supplied Asset ID.

### Server-owned media state

For each Canonical Product + ContentAsset, the service projects:

- source/right Evidence readiness;
- admitted template and fixed-workflow status;
- image role and video ratio coverage;
- latest execution, attempt, lease, cost, latency, error and retry readiness;
- complete append-only execution timeline;
- QA state;
- latest Delivery Manifest and Listing eligibility;
- `brief / source_rights_ready / queued / executing / generated /
  qa_pending / qa_failed / delivery_ready / blocked`;
- source gaps, blockers, Owner, SLA and next workspace;
- deterministic filters, opaque cursor, counts and stable hashes.

The generic image coverage is seven roles: hero, dimensions, benefits, proof,
use cases, package and aftersales. A present product video must deliver
`9:16`, `1:1` and `16:9`. Coverage is reported by the service and is not
recalculated in Web.

### Fail-closed integrity

The affected media payload is withheld when any current authority is bad:

- latest scoped Evidence is invalid;
- Product/content contract, scope, cutoff or snapshot hash drifts;
- an Asset source row is missing or conflicts with the scoped projection;
- mutable Asset generation/QA timestamps post-date `as_of`;
- brief/source/generation/QA shape is invalid;
- execution asset/kind/template/input hash/attempt/currency/time drifts;
- execution event sequence, parent, transition, type, time or current state
  is broken;
- Manifest contract, asset, Product, execution, state hash, payload hash,
  Evidence, cost, latency, encoder, time or Listing eligibility drifts;
- any source collection is truncated or contains an unauthorized parent.

Historical ContentAsset state that cannot be proven from append-only records
is blocked; the service does not infer it from the current mutable row.

## No-write and Agent boundary

The projection has no mutation path. Runtime output proves:

- `asset_created=false`;
- `job_created=false`;
- `qa_decided=false`;
- `manifest_created=false`;
- `listing_created=false`;
- `approval_created=false`;
- `permit_created=false`;
- `external_video_provider_enabled=false`;
- `external_write_allowed=false`.

The versioned `kjds-media-steward-artifact-v1` artifact can only suggest
internal work. It cannot self-approve, issue a Permit, create an Asset/job,
decide QA, create a Manifest or write an external platform.

Existing media mutation endpoints remain separate and retain
`ScopedProductContentAuthority.require_asset(...)` preflight. This slice does
not call ComfyUI, FFmpeg, Ozon or any external media provider. No private
Seller ERP endpoint, Cookie, internal Token, CAPTCHA bypass or copied media is
admitted.

## Backend verification

The focused suite covers:

- missing/invalid entity zero upstream reads;
- deterministic replay and suggestion-only Agent output;
- server search, stage filter, opaque cursor and counts;
- unauthorized store;
- bad Evidence payload withholding;
- future mutable Asset state;
- input hash, event sequence and latest-state drift;
- valid and corrupt Delivery Manifest;
- source truncation;
- a real SQLite SQL-level Asset/as-of isolation read;
- original media execution/idempotency/lease/FFmpeg contracts;
- Commerce OS compatibility;
- API/OpenAPI 401/403/no_data and legacy-route equivalence.

Results:

- focused backend: `67 passed`;
- full backend: `889 passed`, `9 warnings`;
- Ruff: all checks passed;
- OpenAPI snapshot regenerated and matched runtime.

Final repository gates:

- `verify_secrets`: passed across `871` non-ignored worktree files and `581`
  historical paths;
- `git diff --check`: passed;
- `npm ci`: passed with `0` vulnerabilities;
- Web contract tests: `82 passed`;
- Web production build: `44` routes.

No schema authority was missing. BAS-148 is a read composition, so no
synthetic `0075` was created and already-applied `0074` was not modified.

## PostgreSQL and runtime

Alembic:

- script heads: exactly `20260729_0074`;
- live PostgreSQL current: `20260729_0074`.

Live rows:

- Product: `1`;
- ContentAsset: `0`;
- media execution: `0`;
- media execution event: `0`;
- media Delivery Manifest: `0`;
- Ozon Order Fact: `0`;
- Ozon Inventory Fact: `0`.

The one Product is not enough to infer an entity-scoped media factory. The
authenticated exact-scope result remains truthful `no_data`.

After rebuilding current source, PostgreSQL, API, Web and media-worker were
all `healthy`. At fixed `as_of=2026-07-29T00:00:00Z`:

- canonical media factory: `200`;
- legacy media workbench: `200`;
- canonical and legacy JSON: identical;
- anonymous: `401`;
- unauthorized store: `403`;
- entity: `null`;
- all counts: `0`;
- `scoped_input_read=false`;
- snapshot:
  `9ac0b9e3468a25a3cbd7e4d26c40347bf11d970d59fe88edd6c8c8fb508709da`;
- Agent artifact:
  `8c49ba7fbe9ffe7b78830c1ac77192ac03861e93ecba595887c6babf1ae2a15f`;
- all creation and external-write flags: `false`.

Repeated fixed-as-of reads returned the same snapshot and artifact hash and
did not create an OperatingTask or any media row.

## Web and browser

New route: `/media-factory`.

It renders:

- ready/no_data/partial/blocked;
- loading/error/retry;
- Product list and detail;
- server stage filter and opaque pagination;
- image role and video ratio coverage;
- template, execution timeline, QA and Manifest detail;
- source gaps, blocker, Owner/SLA/next;
- explicit no-write and Agent boundaries.

PIM, Listing lifecycle and Commerce OS all link to the same native media
factory.

Web verification:

- `npm test`: `82 passed`;
- production build: `44` routes including `/media-factory`;
- authenticated desktop:
  `inner/client/scrollWidth = 1440/1440/1440`;
- authenticated mobile:
  `inner/client/scrollWidth = 390/390/390`;
- authenticated page reload: console errors `0`, page errors `0`;
- PIM, Listing and Commerce OS media-factory links: all visible and navigable.

Screenshots:

- `output/playwright/bas148-media-factory-desktop.png`
  - SHA-256:
    `85986d7b37aff4e7860b73daa6a21831da5c06317cb5fd4f198a9bc121ada096`
- `output/playwright/bas148-media-factory-mobile-390.png`
  - SHA-256:
    `770205c5fbec635e7c0885f1d46f689f8c4ee173c08a300d0614274fc1d5eea0`

The visible BAS-040 scheduler toast is a truthful unrelated stale runtime
signal; it was not hidden or relabeled as BAS-148 success.

## Harness and Graph

`scripts/seed_bas148_agent_graph.py` independently re-ran the bounded
verification chain and recorded five fresh, dependency-bound observations:

- focused pytest;
- PostgreSQL/Alembic authority;
- authenticated Docker/API runtime;
- desktop and 390px browser Evidence;
- immutable BAS-148 Evidence.

Canonical engineering Graph after BAS-148:

- tasks: `71`;
- nodes: `176`;
- edges: `180`;
- observations: `>=313` (append-only and increases on bounded re-verification).

The Graph state is verifier-owned. A task cannot become passed from an Agent
claim, stale observation or self-reported artifact.

## Gate interpretation

BAS-148 is `DONE_ENGINEERING`, not a claim that media production or commerce
is complete.

Current business truth remains:

- no scoped ContentAsset;
- no media execution or event;
- no QA decision;
- no Delivery Manifest;
- no real Order/Inventory Fact;
- no Listing publish, Approval, Permit, readback or external write.

The 0.59 Release, Pilot and Final Gates remain unchanged. Real business
progress requires exact entity authority, real Product/content Evidence and a
separately governed execution/QA/Manifest/Listing chain.
