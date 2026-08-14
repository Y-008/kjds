# BAS-131 Project Operating Subject Binding — Engineering Evidence

## Decision

`BAS-131` is the next bounded M0 deep slice after BAS-130. It makes the Graph a
Project/Engineering runtime kernel by separating the actor that records an
observation from the operating subject whose real state is verified.

It does not create owner authority, advance M0, deploy the dedicated monitor
task, open an external write, or change the 0.59 Release Gate.

## Gap audit

- BAS-125–130 already provided append-only verifier observations, stable Graph
  nodes/edges, Node→GoalTask bindings, dynamic M0→M4 and scope-authority state.
- The observer still used its monitor/admin recorder identity when loading
  Commerce OS and current scope authority. A monitor could therefore project
  itself instead of a real store operator.
- No canonical append-only project→operating-subject relation existed, so a
  subject change could not enter downstream verifier hashes or stale prior
  projections.
- Project/Engineering/Authority Graph could drill into verifiers and artifacts,
  but could not show which real registered principal was being verified.

## Implemented slice

- Alembic `20260728_0070` adds append-only
  `graph_project_subject_binding_events` with exact project/tenant/store,
  `bind|revoke`, effective/recorded time, stable authority hash and idempotency.
- `AgentHarnessService.operating_subject(...)` resolves one canonical subject at
  `as_of`; missing, revoked, ambiguous, overlapping, out-of-order or future
  events fail closed.
- Only admin may append events. The target must be a registered exact-scope
  operator and must differ from the admin/monitor recorder; privileged subjects
  are rejected.
- `ApiKeyAuthenticator.resolve_actor(...)` resolves registered principals
  without borrowing or disclosing a credential.
- The observer records as the monitor/admin but loads Commerce OS and
  `ScopeGrantAuthority.current` as the bound subject. The subject binding hash is
  included in all subject/scope/M0→M4 input hashes.
- A stable operating-subject GoalTask, Graph node, status-source binding,
  verifier and Observation expose subject, binding hash, why, next action,
  owner, SLA and artifact drilldown.
- Authenticated GET/POST operating-subject endpoints and the optional
  monitor/admin-only `subject_actor_id` scope-current query are exported in
  OpenAPI.
- Health/G-1 checks require revision 0070, a non-monitor operating subject, its
  authority hash, seven observer states, and both external-write and model
  self-certification flags to remain false.

No entity grant, account-owner source/review, Approval, Permit or external
commerce write is created by the binding.

## Migration verification

An isolated PostgreSQL database completed
`base → 20260728_0069 → 20260728_0070 → 20260728_0069 → 20260728_0070`.
The table, indexes, foreign key, checks and unique idempotency constraint were
inspected; the exact temporary database was then force-dropped.

The real database was frozen before the forward-only migration:

- revision `20260728_0069`;
- Evidence `58`, scope grants `0`;
- GoalTasks `24`, Observations `54`;
- Graph nodes/edges/bindings `66/71/33`;
- scope source/review `0/0`;
- subject-binding table absent.

After the real `0069 → 0070` migration, every pre-existing count and stable hash
was unchanged and the new table was empty. The canonical `r0-requester` binding,
observer pass and full Graph seed then produced:

- Evidence `58`, grants `0`, source/review `0/0`;
- GoalTasks `25`, Observations `67`;
- Graph nodes/edges/bindings `75/82/42`;
- operating-subject events `1`;
- revision `20260728_0070`.

The migration was forward-only on the real database. No historical row was
backfilled or rewritten.

## Focused verification

- Agent Harness, observer, health, security, Truth/OpenAPI and seed suites:
  `48 passed`;
- focused final seed suite: `13 passed`;
- focused Ruff: clean;
- Alembic: one head, `20260728_0070`;
- `git diff --check`: no whitespace error; existing CRLF conversion warnings
  only.

## Full regression gates

- full backend: `777 passed, 9 warnings in 35.56s`;
- full Ruff: clean;
- Web contract tests: `55 passed`;
- production Web build: `33/33` pages;
- OpenAPI regenerated with both operating-subject routes and the
  `subject_actor_id` current-scope parameter;
- secret scan: `752` non-ignored worktree files and `581` historical paths;
- final Alembic current/head: the single `20260728_0070` head.

## Container and live API acceptance

Resolved rebuilt images:

- API:
  `sha256:5ac95ae8761709d37c184d786e50c76e0fab718cbde6fe8e3beb4c04997b1338`;
- media worker:
  `sha256:5c2b3ddc986e9103c4514bb7a30cd68b117ef20a9fe2719681a15a8693b7ab7f`;
- Web:
  `sha256:b2481215f309ff8d8bd921b5fa8a669b672918b34f5425e707fc479a43596230`.

API, media worker, PostgreSQL and Web were healthy, and `/health/ready`
returned `200`.

Operating-subject API acceptance:

- unauthenticated: `401`;
- operator event append: `403`;
- admin bind and exact idempotent replay: `200`;
- same idempotency key with payload drift: `422`;
- current binding: `200/ready`, subject `r0-requester`, authority hash
  `c57c5ff...`, `external_write_allowed=false`.

Observer acceptance:

- unauthenticated: `401`;
- operator: `403`;
- admin observe and exact replay: `200`, with identical Observation IDs;
- revision `20260728_0070`;
- recorder and subject are distinct; subject is `r0-requester`;
- `operating_subject=passed`, `scope_authority=no_data`, `M0=no_data`,
  `M1–M4=blocked`;
- external write and model self-certification are both `false`.

Project, Engineering, Authority and workspace APIs all returned `200`.
Workspace remained blocked with zero failed and zero stale projections.

## Verifier truth correction

The first post-migration browser pass exposed an inherited BAS-128 database
observation whose summary still named revision 0068. This was not accepted as a
current verifier conclusion. The seed verifier input was expanded to hash the
actual Agent Harness, router, security, runtime, migration, seed and test
artifacts, then the full external observation chain was rerun.

The resulting current Observation reports real PostgreSQL
`20260728_0070`; the older observation remains append-only history and no longer
drives the fresh projection.

## Browser acceptance

The rebuilt real Web application was inspected with Playwright against the live
containers:

- desktop Authority Graph at `1440px`: subject `r0-requester` is
  `passed/fresh`; scope authority is `no_data/fresh`; subject, binding,
  verifier, Observation, artifact, why/next/owner/SLA are visible;
- Authority Graph at `390px`: no horizontal overflow and zero console errors;
- desktop Project Graph: BAS-131 plan is `passed/fresh`; Release 0.59 remains
  `blocked/fresh` with Gate `REJECTED`; M0→M4 show their real blockers;
- desktop Engineering Graph: migration 0070, ADR-0055, change, code, test and
  current 0070 Observation are drillable;
- Goal TODO at `390px`: operating-subject task is `passed/fresh`,
  scope-authority task is `no_data/fresh`, with the truthful next action;
- all inspected browser requests returned `200`, console logs were empty, and
  desktop/mobile pages had no page-level horizontal overflow.

Screenshots:

- `output/playwright/release-0.59.0/bas131-authority-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas131-authority-graph-390.png`;
- `output/playwright/release-0.59.0/bas131-project-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas131-engineering-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas131-goal-todo-390.png`.

## 24×7 fail-closed result

`scripts/run-24x7-health.ps1 -ControlPlaneOnly` reached the healthy control
plane at `200` but exited non-zero because the local scheduled-task environment
has neither `KJDS_API_KEY` for operations readiness nor
`KJDS_MONITOR_API_KEY` for Evidence and Agent Gate observation. It did not
borrow admin/operator credentials and did not fabricate Evidence or Gate
freshness. Dedicated monitor identity and Windows Task deployment remain the
existing BAS-040 `BLOCKED_CONFIG` boundary.

## Current operating truth

- Bound operating subject: `r0-requester`, distinct from the recorder.
- Current scope grant/source/review: `0/0/0`.
- M0: `no_data`; M1–M4: `blocked`.
- Dedicated monitor credential and Windows Task: not deployed.
- Release Gate: `REJECTED`.
- External commerce writes: closed.
- Model self-certification: disabled.
