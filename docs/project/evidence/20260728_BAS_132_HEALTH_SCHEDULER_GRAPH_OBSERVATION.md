# BAS-132 Health Scheduler Graph Observation — Engineering Evidence

## Decision

`BAS-132` turns the remaining BAS-040 scheduler deployment into real verifier-owned
Project/Runtime/Authority Graph state. It does not install the Task or reinterpret a
missing deployment as success.

## Gap audit

- The health loop and safe Plan/Audit/Install script already existed.
- BAS-040 remained a Markdown `BLOCKED_CONFIG` row and shell exit code.
- Graph/TODO did not expose the exact Task definition, completion history, health
  sections, immutable audit artifact, Owner or next safe action.
- No verifier independently recomputed the script's `definition_valid` and `accepted`
  claims.

## Implemented slice

- `HealthSchedulerDeploymentVerifier` is pure and versioned.
- Exact Task identity, cadence, execution limit, overlap policy, Action, working
  directory, last result, seven-day history and three-success threshold are checked.
- Control plane, operations readiness, Evidence integrity and Agent Gate observation
  must be concurrently healthy.
- Contract drift and false acceptance claims are `failed`; valid missing deployment
  inputs are `blocked`; only all external checks true can be `passed`.
- The Graph seed runs both read-only PowerShell observers, freezes raw JSON and exit
  codes in a content-addressed artifact, and appends registered external observations.
- Stable BR-108/ADR-0056/change/code/test/scheduler/observation/Evidence/authority
  nodes and causal edges are bound to separate engineering-test and runtime-deployment
  GoalTasks.

## Current real external observation

At the first BAS-132 audit:

- Task Plan contract: valid, no mutation, fixed 15-minute cadence and 5-minute limit;
- Task Audit exit: non-zero and `not_accepted`;
- scheduled task found: `false`;
- definition/history accepted: `false/false`;
- control plane: `200/ok`;
- operations readiness: unavailable because scheduler-visible `KJDS_API_KEY` is absent;
- Evidence and Agent Gate observation: unavailable because the dedicated
  `KJDS_MONITOR_API_KEY` is absent.

The expected verifier state is therefore `blocked`, with
`scheduled_task_missing` and three health readiness blockers. It is not `failed`
because the external payload is valid and truthfully reports missing deployment.

## Initial verification

- pure verifier: `5 passed`;
- verifier plus Graph seed contract tests after stable-artifact fault correction:
  `9 passed`;
- Agent Harness, scheduler and Graph focused suite: `18 passed`;
- external-write and model-self-certification flags: both `false`.

## Stable-node fault correction

The first full seed correctly rejected
`scheduler:evidence-integrity-health` as canonical node drift. The initial
implementation had placed a content-addressed one-run JSON path in the stable
node's canonical artifact field, so the next real audit produced a different
path.

No BAS-132 Observation had been written when the rejection occurred. The node
interface was corrected to reference the stable
`output/graph/bas132-health-scheduler` artifact collection, while each Task and
Observation drilldown retains the exact content-addressed JSON. A compatibility
guard accepted only the three just-created BAS-132 scheduler nodes whose old
source matched that exact hashed-path pattern; all other canonical drift still
fails closed.

## Real PostgreSQL append-only result

Before BAS-132:

- revision `20260728_0070`;
- Evidence `58`, grants `0`;
- GoalTasks/Observations `25/67`;
- Graph nodes/edges/bindings `75/82/42`;
- subject-binding events `1`;
- Evidence hash `4afcdd2f247f17bec04bfddc2cbf1b88`;
- subject-event hash `b2e3a795cf47e883839276f62b471267`.

After stable structure, external observation, rebuild and final replay:

- revision remains the single `20260728_0070` head;
- Evidence `58`, grants/source/review `0/0/0`;
- GoalTasks/Observations `27/82`;
- Graph nodes/edges/bindings `85/92/52`;
- subject-binding events `1`;
- the same Evidence and subject-event hashes were retained.

Only Agent Harness structure and append-only verifier observations were added.
No business Evidence, scope authority or operating-subject history was changed.

## Full regression and rebuilt runtime

- full backend: `785 passed, 9 warnings in 37.48s`;
- full Ruff: clean;
- Web contract tests: `55 passed`;
- production Web build: `33/33` pages;
- secret scan: `756` non-ignored worktree files and `581` historical paths;
- OpenAPI regenerated;
- `git diff --check`: no whitespace error; existing CRLF conversion warnings
  only.

Resolved rebuilt images:

- API:
  `sha256:0bedd2881e5953dfd837b22fc9ef969c2ff626737d0db0d047127a0d03975502`;
- media worker:
  `sha256:d73c08c569a962bbd41eb95fd2fc4cc6ec715be52b424a0e9681d4997e82ba90`;
- Web:
  `sha256:699ed79f51750525fe9905eccea0b415045a12dccae300ae55da5249f6d3d3d2`.

API, media worker, PostgreSQL and Web were all healthy.
`/health/ready` returned `200`.

## Live Graph/API acceptance

The authenticated workspace returned:

- status `blocked`;
- `27` tasks, `85` nodes, `92` edges and `52` verifier-owned nodes;
- `20 passed`, `5 blocked`, `2 no_data`, `0 failed`, `0 stale`;
- external write and model self-certification both `false`.

The scheduler deployment Task is `blocked/fresh` with:

- verifier `bas132-health-scheduler@1`;
- structured blocker `verifier_state:blocked`;
- Observation `obs_ec81e96e35cbbaee92dc70c52607b1f6`;
- exact artifact
  `output/graph/bas132-health-scheduler/5923ab6079793e911c82d524edd35d0d2ed6d7b4c2924adfcccbfd66c9f7417a.json`;
- real why:
  `scheduled_task_missing`,
  `health_operations_readiness_not_ready`,
  `health_evidence_integrity_not_ready`, and
  `health_agent_gate_observation_not_ready`;
- Owner `engineering+operations`, SLA `86400s`, dependency
  `task-bas132-verifier-tests`, and an explicit install/configure/three-success
  next action.

The BAS-132 engineering plan/task is independently `passed/fresh`. Runtime
deployment remains blocked; the two states are not collapsed.

## Browser acceptance

Playwright CLI inspected the rebuilt live application:

- desktop `1440px` Runtime Graph: the exact scheduler/audit nodes are
  `blocked/fresh` with why, Owner, SLA, dependency, next action and artifact;
- desktop Project Graph: BAS-132 is `passed/fresh`, while Release 0.59 and its
  risk remain `REJECTED`;
- desktop Engineering Graph: BR-108, ADR-0056, change, pure verifier code and
  anti-spoof tests are connected and `passed/fresh`;
- desktop Authority Graph: the dedicated scheduler-visible monitor identity
  governs the blocked Windows Task and exposes the same external Observation;
- `390px` Goal TODO: the BAS-040 Task shows `blocked/fresh`, exact verifier and
  next safe action;
- `390px` Runtime Graph retains all four real blocker reasons;
- desktop `clientWidth=scrollWidth=1425`; mobile
  `clientWidth=scrollWidth=375`;
- console errors/warnings: `0/0`; all inspected application/API requests:
  `200`.

Screenshots:

- `output/playwright/release-0.59.0/bas132-runtime-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas132-project-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas132-engineering-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas132-authority-graph-desktop.png`;
- `output/playwright/release-0.59.0/bas132-goal-todo-390.png`;
- `output/playwright/release-0.59.0/bas132-runtime-graph-390.png`.

## Operating boundary

- BAS-040 remains `BLOCKED_CONFIG`.
- No Task installation was executed.
- No credential was read into a command line or written to an artifact.
- Current scope source/review/grant rows remain zero.
- M0 remains `no_data`; M1–M4 remain `blocked`.
- Release Gate remains `REJECTED`.
- External commerce writes remain closed.

## BAS-135 external-audit correction — 2026-07-29

The current Windows host emits a missing scheduled task as
`Microsoft.PowerShell.Cmdletization.Cim.CimJobException` with
`ObjectNotFound`, rather than the previously caught base CIM exception. The audit now
maps both forms to the same secret-free missing-task result.

Latest verifier-owned runtime truth:

- Observation: `obs_42bdd8f2a815356d01b85967f49f2bb4`;
- artifact:
  `output/graph/bas132-health-scheduler/919a263fbbdac639b92f37fae97c72d2fff102d93ecf899726f4bbe1dc3592be.json`;
- artifact SHA-256:
  `fd46ad17d86c53cffeed01dcb68b4575f2f1ee66eb2dc4d631ba277121ba8dfd`;
- state: `blocked/fresh`;
- task missing classification is exact;
- scheduler verifier tests: `passed/fresh`,
  `obs_d735553807433974c38e936a2a3e4728`;
- Task Install was not run and `mutation_performed=false`.

The full dependency invalidation/recovery Evidence is
[BAS-135](20260729_BAS_135_GRAPH_DEPENDENCY_REVERIFICATION.md).
