# BAS-134 Evidence — Verifier-owned Authority Workflow Topology

## Decision

`BAS-134` engineering is accepted on 2026-07-29. The live runtime topology is
intentionally `fresh/blocked`, not passed:

- the exact `default / ozon-primary` API identity inventory can form one valid
  four-party chain;
- the running Web is `legacy` and has zero Supabase user bindings;
- the Web workflow therefore cannot yet be completed by four independently
  authenticated people;
- the verifier did not create Evidence, a scope grant, Approval, Permit or external
  write.

Release `0.59` remains `REJECTED`. This Evidence accepts the verifier-owned engineering
slice; it does not accept M0, BAS-040, the Pilot Gate or the Release Gate.

## Requirement and architecture

- Requirement: `BR-110`
- Plan: `BAS-134`
- ADR:
  `docs/adr/ADR-0058-verifier-owned-authority-workflow-topology.md`
- Pure verifier:
  `web/lib/authority-workflow-topology.ts`
- Authenticated live endpoint:
  `web/app/auth/authority-topology/route.ts`
- Workbench projection:
  `web/features/agent-control/authority-intake-workbench.tsx`
- Graph observer:
  `scripts/seed_project_engineering_execution_graph.py`

The module is a deep identity boundary: callers provide running configuration
projections and receive one stable verdict. The UI and Graph do not repeat role or
separation-of-duty rules.

## Live external observation

Artifact:

`output/graph/bas134-authority-workflow-topology/7f1918c507a5f6b232188ef5387c4e55b4cc6f849637eef616aadd741c6cdbd6.json`

- Artifact SHA-256:
  `6dba49426ec6a9c4dec99385cf6ded2ff16b4e78d116502868fbc560571544fb`
- Observation contract:
  `kjds-bas134-authority-topology-observation-v1`
- Verifier:
  `authority-workflow-topology@1`
- `observed_at`: `2026-07-28T17:01:43.943458+00:00`
- Observation bucket: `2026-07-28T17:00:00+00:00`
- Observer input SHA-256:
  `6f0c8c93a24349d85a277b74c1cb66ccdbe555c4b1926de8224ea1474b114131`
- DAG-bound Harness input SHA-256:
  `da9df5e36a003eb19f746f438254e2f7641d94565239fd7356e365503a50f61f`
- Topology input SHA-256:
  `b9949b6cdacec5714334bc125c2fac9fa984c8b5389859b77bdee3b0f27e9de8`
- Topology result SHA-256:
  `9248beb730cb684c6e74bc4a9e17cc6be11674526dca84dcf2f86608a9e2f551`
- Endpoint: HTTP `200`
- State: `blocked`
- Freshness at observation: `fresh`
- Blocker: `web_auth_mode_not_supabase`
- API chains: `1`
- Web chains: `0`
- Registered/exact-scope actors: `6 / 6`
- Web user bindings: `0`

The selected deterministic API chain is:

`r0-requester (subject) → kjds-owner-lunar (owner) → r0-risk (reviewer) →
r0-admin (recorder/preflight)`

These are four different actor references. The observation contains no API key, raw
Supabase user ID, cookie, token or credential value. `role_switch_allowed=false`,
`grant_created=false`, `model_self_certification_allowed=false`, and
`external_write_allowed=false`.

## Zero-mutation proof

The external observer counted authority rows immediately before and after the live Web
request:

| Table/contract | Before | After |
|---|---:|---:|
| `scope_authority_source` Evidence | 0 | 0 |
| `scope_authority_review` Evidence | 0 | 0 |
| `scope_grant_events` | 0 | 0 |

The final real PostgreSQL projection remained:

- Alembic revision: `20260728_0070`
- Evidence: `58`
- Goal tasks: `32`
- Graph nodes / edges: `110 / 123`
- Harness observations: `164`
- Node status bindings: `77`

## Verifier-owned Graph and TODO

The following stable objects were added without a schema migration:

- Project: `plan:BAS-134`
- Requirement: `requirement:BR-110`
- ADR/change/code/test:
  `adr:ADR-0058`, `change:BAS-134`,
  `code:authority-workflow-topology-verifier`,
  `code:authority-workflow-topology-workbench`,
  `test:authority-workflow-topology`
- Runtime/Evidence:
  `observation:bas134-authority-workflow-topology`, `evidence:BAS-134`
- Authority: `authority:four-party-workflow-topology`

Two different GoalTasks preserve the engineering/runtime distinction:

- `task-bas134-verifier-tests`: `passed/fresh`
- `task-bas134-authority-workflow-topology`: `blocked/fresh`

The runtime task is bound to the topology nodes through immutable `status_source`
bindings. Its drilldown returns verifier, Observation ID
`obs_8c426ee5add9768bc98cdfb6a36a298f`, artifact, Evidence path, dependencies,
why, next action, Owner `account-owner+identity-engineering` and SLA `86400s`.
`plan:BAS-134 --blocks_until_verified→ milestone:M0`; it does not mark M0 or Release
passed.

After the observation:

- BAS-040 remained `blocked`;
- BAS-134 runtime topology remained `blocked`;
- BAS-133 tests/intake and BAS-134 tests were restored to `passed/fresh` by the
  BAS-135 full-DAG re-verification recovery;
- M0 operating subject/scope authority and M0→M4 remained stale because their earlier
  monitor-owned observations were not refreshed with a dedicated monitor identity;
- workspace status was `blocked`;
- Release Gate was `REJECTED`.

## Browser acceptance

Playwright CLI used the real Compose Web and API.

### Authority Intake desktop

- Viewport: `1440 × 1000`
- `innerWidth=1440`, document/body width `1425`
- API chain `ready`, Web chain `blocked`
- all four selected actors visible
- operator mutation buttons disabled
- `role switch allowed false`, `grant created false`, `external write false`
- screenshot:
  `output/playwright/release-0.59.0/bas134/bas134-authority-topology-final-desktop.png`
- SHA-256:
  `0df6a54457dd6da845dd130796a4e0027449e8b24c2c764395c7e418139c3dcd`

### Authority Intake 390px

- Viewport: `390 × 844`
- `innerWidth=390`, document/body width `375`
- no horizontal overflow
- four-party chain, blocker, input/result hash and next action remain readable
- screenshot:
  `output/playwright/release-0.59.0/bas134/bas134-authority-topology-final-390.png`
- SHA-256:
  `02b31410fc5d20fe25ff2c828d366fb0f5f827757e5ae73100f847ab8ade8457`

### Graph and TODO drilldown

- Authority Graph screenshot:
  `output/playwright/release-0.59.0/bas134/bas134-authority-graph-final-desktop.png`
  (`e07683cdbeafab09443095503a2879edfbbf5469ff43b513188124e117ce5af5`)
- Engineering Graph screenshot:
  `output/playwright/release-0.59.0/bas134/bas134-engineering-graph-desktop.png`
  (`26ee183f681b56da542e997784be73abeb078a6fd1711bf7d0a4d2db2b1837c2`)
- Project Graph screenshot:
  `output/playwright/release-0.59.0/bas134/bas134-project-graph-desktop.png`
  (`c286236b464d088efbc0b5288ed9b445f57730efe71e137f96b8b6ad1b04d3e9`)
- 390px TODO screenshot:
  `output/playwright/release-0.59.0/bas134/bas134-goal-todo-final-390.png`
  (`1e45260dca6616efc3af43e04c830a052d8f3c3fab1e905acad63009f04ddc5c`)

Browser network observations for session, topology, intake and Graph endpoints were all
HTTP `200`. Console result was `0` errors; the earlier navigation emitted only
non-blocking Next CSS preload warnings.

## Delivery verification

- Full backend:
  `796 passed, 9 warnings in 41.07s`
- Focused Graph/Agent Harness:
  `18 passed`
- Ruff: pass
- Secret scan:
  `767` non-ignored worktree files and `581` historical paths; pass
- OpenAPI contract:
  `32 passed, 1 warning`
- Web after `npm ci`:
  `61 passed`, `0` failed, `0` vulnerabilities
- Web production build:
  `35/35` pages; `/auth/authority-topology` is dynamic
- `git diff --check`:
  exit `0`; existing CRLF conversion warnings only
- Containers:
  PostgreSQL, API, media-worker and Web healthy
- API image:
  `sha256:b2f4a93196d6161bea66f24ebe5a58f027d35e42fd76024d6d799e951b4ba6c7`
- Web image:
  `sha256:4be08ecb133628d37e83202529beb2a462b70233d4ced577088e4bc4d235f52c`

## Review findings

| Severity | Finding | Handling |
|---|---|---|
| P0 | None. | no-op |
| resolved P1 | Malformed or duplicate Web identity configuration originally escaped the normal verifier response path. | endpoint now maps configuration faults to the same secret-free `failed` verifier contract; negative test included |
| P1 | Web is legacy and has zero independent Supabase bindings, so the real four-person workflow is blocked. | defer to account owner + identity engineering; do not synthesize users or add role switching |
| P1 | Dedicated monitor/Windows Task configuration is still absent; earlier M0→M4 observations are stale. | defer under BAS-040; do not borrow operator/admin identity |
| P2 | Next emitted one CSS preload warning in each browser session. | defer; no console error, request failure or layout defect observed |

## Next safe action

The account owner and identity engineering owner must provision Supabase Web auth and
bind four different real users to the selected exact-scope subject, owner, reviewer and
recorder actors. Then obtain a new live topology Observation. Only after that may the
independently authenticated owner submit real authority source Evidence. Formal grant
recording, commerce writes and Release approval remain separate later Gates.
