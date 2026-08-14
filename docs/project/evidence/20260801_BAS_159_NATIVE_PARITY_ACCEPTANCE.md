# BAS-159 capability-granular native-parity acceptance Evidence

- Slice: `BAS-159`
- Engineering disposition: `DONE_ENGINEERING`
- Business/runtime disposition: `contract/no_data`, `implemented_unverified`
- Captured: 2026-08-01, Asia/Shanghai
- Scope: exact `tenant/entity/store/provider/capability/version/as_of`
- Global objective: this closes one engineering slice only; the global `0.59→M4` goal remains in progress.

## Claim boundary

The delivered authority is the single deep module `NativeParityAcceptanceWorkspace.project(...)`. It replaces Commerce OS family-wide, stage-derived `implemented` claims with capability-granular acceptance across eight independently bound dimensions: code, migration, API/OpenAPI, Web, permission/write path, runtime replay, immutable Evidence, and a fresh external Graph verifier observation.

Mapping, menus, internal readiness, shared stage Evidence, and `DONE_ENGINEERING` do not produce `verified_native`. Missing, stale, malformed, self-certified, cross-scope, version-drifted, or hash-drifted records fail closed. The read-only workspace creates no business Fact, credential, Approval, Permit, or external write.

The live exact-store identity currently has no authoritative entity binding. The verified runtime result is therefore `no_data`, `items=0`, and `verified_native=0`; the projection performs no provider acceptance read in that state. This is not market coverage and is not native parity completion. Provider-specific mappings remain gated until every required dimension has an exact, independently verified bundle.

## Engineering gates

- Focused deep-module, SQL Graph adapter, API, Commerce OS, and API-contract suite after final P1 hardening: `80 passed`.
- Full backend suite: `1149 passed`, 9 warnings.
- Secrets gate: 1026 current nonignored paths and 581 historical commits verified.
- Ruff: passed.
- `git diff --check`: passed; only pre-existing line-ending warnings were emitted.
- Web executable contract/state suite: `126 passed`.
- Web strict production build: passed, 55 routes including `/native-parity`.
- Alembic single head and current: `20260731_0081`.
- No schema change was required; BAS-159 reuses canonical Graph/Harness rows and adds no forced migration.
- Rebuilt PostgreSQL, API, Web, and media-worker containers: all running and healthy.

## Live API and runtime truth

`scripts/verify_bas159_runtime.py` independently observed:

- anonymous request: 401;
- authenticated exact-store request: 200;
- unauthorized store request: 403;
- readiness: 200;
- deterministic replay: true;
- `entity_ref=null`, `status=no_data`, `items=0`, `verified_native=0`;
- OpenAPI exposes GET only at `/v1/native-parity-acceptance/workspace` and matches the repository snapshot;
- live OpenAPI SHA-256: `27d85024176aa17f63d631548c85f38518d5340ed94ad02cb9272c7e4cbae498`;
- projection snapshot SHA-256: `5d6c670992e77114ee2371f23774c138dc6045106baa780173cf4c0d28df23e4`;
- `mapping_is_implementation=false`;
- `engineering_done_is_verified_native=false`;
- `client_can_recalculate_or_promote=false`;
- `self_certification_allowed=false`;
- `business_fact_created=false`;
- `credential_created_or_read=false`;
- `approval_created=false`;
- `permit_created=false`;
- `external_write_allowed=false`.

## Browser evidence

The live rebuilt Web application was exercised with authenticated browser state on `/native-parity`.

- Desktop viewport: `1440/1440` (`innerWidth/documentElement.scrollWidth`), zero console errors.
- Mobile viewport: `390/390`, zero console errors.
- Both views showed the real `no_data` state, zero total/verified counts, exact scope, authority boundaries, error/retry-capable client state, and a Commerce OS drill-down.
- Two non-failing Next.js CSS preload warnings were observed in each viewport.
- Desktop screenshot: `output/playwright/bas159-native-parity-desktop.png`, SHA-256 `71df5a6fba38c9badf9a3ec054dedd0a191163e6cb67073e29b1489e8cb9f2da`.
- 390px screenshot: `output/playwright/bas159-native-parity-mobile-390.png`, SHA-256 `d47f4903555bc5d761348b25178110351fe8263508b24031648611b3f210d6ef`.

## External verification and remaining blockers

The engineering Graph materializes separate test, database-compatibility, runtime, Web-artifact, and immutable-Evidence tasks. The seed executes the full backend, secrets, Ruff, diff, Web test/build, live runtime and container gates; it verifies the byte hashes of browser captures produced by the preceding live Playwright measurement. The database task proves PostgreSQL head/current compatibility with the reused canonical Graph schema; it does not claim a new migration replay. Each task advances only from its own observation, and none of these engineering observations can promote a provider capability. Runtime native acceptance still requires a separate complete dimension-specific Graph bundle.

Current business blockers remain explicit:

- no exact-scope real entity and provider capability Evidence bundle in the live scope;
- no provider-specific runtime replay/readback bundle satisfying all eight dimensions;
- no real Order, Inventory, Shipment, Settlement, or Cash facts;
- all Ozon, supplier, procurement, payment, advertising, and other external writes remain disabled.

Accordingly BAS-159 is `DONE_ENGINEERING`, while every unproven capability remains `implemented_unverified`, `gated`, `blocked`, or `no_data`. Release, pilot, and final gates remain closed.
