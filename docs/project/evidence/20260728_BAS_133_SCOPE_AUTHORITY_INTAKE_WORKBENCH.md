# BAS-133 Scope Authority Intake Workbench — Engineering Evidence

## Decision

`BAS-133` makes the M0 owner-source → independent-review → zero-write-preflight
handoff executable through a verifier-owned exact-scope read model and Web workbench.
It does not create or expose a formal scope grant.

## Gap audit

- Dedicated source, review and preflight APIs already existed.
- Authority Graph/TODO explained the next action but offered no endpoint-backed work
  surface.
- The browser could not safely discover exact-scope source/review state, identities,
  Lineage or current authenticated capabilities.
- A client-side scan of the global Evidence ledger would have duplicated domain rules
  and violated scope isolation.

## Implemented slice

- `ScopeGrantAuthority.intake()` owns exact tenant/entity/store/subject/decision and
  `as_of` projection.
- It verifies immutable hash, current effective time, recorded-time cutoff, reserved
  contracts, independent identities, checks and source ID/hash Lineage.
- It returns `input_required/no_data/blocked/ready_for_preflight`, deterministic hash,
  structured blockers, why/next/Owner/SLA and real role capabilities.
- `GET /v1/scope-grants/intake` resolves a registered subject and enforces workflow-role
  access.
- `/authority-intake` reads the real Web session and server projection, exposes only
  source, review and zero-write preflight forms, and links to real Evidence/Lineage.
- The formal grant event route is absent from the workbench.
- Stable BR-109/ADR-0057/change/code/test/observation/Evidence/authority nodes bind to
  separate engineering-test and live API/Web/database observations.

## Contract and regression verification

- focused Scope Authority/route/Graph suite after the deterministic-input
  regression: `30 passed`;
- full backend with a workspace-local `basetemp`: `791 passed, 9 warnings in
  32.60s`;
- full Ruff: clean;
- Web contract tests: `56 passed`;
- production Web build: `34/34` pages, including `/authority-intake`;
- fixed OpenAPI snapshot regenerated and its equality test passed.

The first default full pytest attempt exposed two environment/contract conditions,
not product failures: the newly added GET route required OpenAPI export, and the
system pytest Temp root denied directory enumeration. The repository exporter fixed
the snapshot; rerunning the same full suite with a unique workspace-local
`--basetemp` passed every test.

## Rebuilt runtime

Resolved rebuilt images:

- API:
  `sha256:d1cd463e9763337889232a5f729ca85169289eb07996952cb63c6561310cc53d`;
- media worker:
  `sha256:9c9930b8cb95b849095fade943dd4f01231837cf822efe337682a7b3c74fa053`;
- Web:
  `sha256:5d3a5601b7a5455999cc9bbcd697c11647ec8d7005507f115271505932d9cdbb`.

API, media worker, PostgreSQL and Web were all healthy. `/health/ready` and the
rebuilt `/authority-intake` route returned `200`.

## Real PostgreSQL and external observation

Before the BAS-133 live observer:

- revision `20260728_0070`;
- Evidence/source/review/grant `58/0/0/0`;
- project operating-subject events `1`.

The observer:

1. read those three authority counts;
2. called the authenticated entity-free intake endpoint and required
   `input_required` plus `entity_ref_required`;
3. required API/Web `200`, `external_write_allowed=false`,
   `grant_endpoint_exposed=false` and `grant_created=false`;
4. reread the three authority counts and required exact equality;
5. froze the session-safe response and counts under
   `output/graph/bas133-authority-intake/<content-hash>.json`;
6. appended only Agent Harness observations.

The first documentation-hash replay exposed one adjacent Graph observer fault:
the database observation summary included its pre-seed binding count while its
`input_sha256` did not. The changed binding count therefore changed the result hash
without changing the declared input, and Agent Harness correctly marked downstream
container/API/browser/Evidence tasks stale. `database_observation_input()` now hashes
revision, binding count and migration hashes; a regression test proves replay
stability and count-change propagation.

After the corrected final replay:

- Evidence/source/review/grant remain `58/0/0/0`;
- project operating-subject events remain `1`;
- GoalTasks `29`; append-only Observations reached `105` at the corrected replay
  and may only increase when the finalized Evidence hash is observed;
- Graph nodes/edges/bindings `95/105/62`;
- BAS-133 test and live tasks are `passed/fresh`;
- workspace is `blocked` with `21 passed`, `1 blocked`, `7 stale`, `0 failed`.

The stale count is intentional runtime truth. The project operating-subject,
scope-authority and M0→M4 observations exceeded their one-hour freshness because
the real scheduler remains undeployed. No admin/operator credential was borrowed
to refresh them. BAS-040 remains `blocked/fresh` for the missing Task and dedicated
scheduler-visible readiness.

## Browser acceptance

Playwright CLI drove the rebuilt application without submitting any form:

- desktop Authority Intake showed requester `r0-requester`, role `operator`,
  verifier `scope-authority-intake@1`, `input_required`, formal authority
  `no_data`, external write `false` and grant endpoint exposed `false`;
- owner source, independent review and preflight buttons were all disabled;
- desktop Authority Graph showed the live no-mutation observation and intake
  authority as `passed/fresh`, exact Observation/artifact/Evidence, Owner, SLA,
  dependency and next action; the same projection retained M0 `stale` and scheduler
  `blocked`;
- desktop Engineering Graph connected ADR-0057→BAS-133 Change→backend/Web Code→
  exact-scope Test, all `passed/fresh`;
- desktop Project Graph showed BAS-133 `passed/fresh` while
  `Release 0.59 · Gate REJECTED` remained stale/blocked by the real M4 chain;
- 390px TODO showed both BAS-133 tasks `passed/fresh`, BAS-040 `blocked/fresh` and
  M0→M4 `stale`;
- desktop `clientWidth=scrollWidth=1425`; mobile
  `clientWidth=scrollWidth=375`;
- console errors: `0`; one Next.js CSS preload timing warning only;
- all inspected application/API/RSC requests: `200`.

Screenshots:

- `output/playwright/release-0.59.0/bas133-authority-intake-desktop.png`;
- `output/playwright/release-0.59.0/bas133-authority-intake-390.png`;
- `output/playwright/release-0.59.0/bas133-authority-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas133-engineering-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas133-project-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas133-goal-todo-390.png`.

## Operating boundary

- No real owner source or independent review was submitted.
- No preflight was run with invented scope.
- No formal grant event, Approval or Permit was created.
- No external platform, supplier, procurement, payment or advertising write was
  opened.
- M0 is not complete; M1–M4 remain blocked/stale by upstream truth.
- Release/Pilot/Final Gates remain `REJECTED`.
