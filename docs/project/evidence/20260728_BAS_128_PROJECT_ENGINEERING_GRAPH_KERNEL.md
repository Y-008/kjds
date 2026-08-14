# BAS-128 Project and Engineering Graph Kernel — Engineering Evidence

## Decision

`BAS-128` engineering acceptance is `PASS`. This slice makes Graph a dynamic
Project/Engineering execution index over verifier-owned GoalTasks; it does not declare
the operating release ready. Release Gate remains REJECTED.

## Gap audit

Before this slice, the real project contained 17 GoalTasks, 27 append-only
Observations, 43 canonical nodes and 39 edges. It already supported exact
tenant/store scope, `as_of`, freshness, stable hashes and task dependency
invalidation. It did not have:

- a node-to-verifier-task authority relation;
- first-class Program, Project, Workstream, Release, Owner, SLA, Dependency, Risk,
  Decision, Change, Build or Deploy nodes;
- node drilldown to why/next/owner/SLA/verifier/Observation/artifact/Evidence.

## Implemented slice

- Requirement: `BR-104`
- Architecture: `ADR-0052`
- Migration:
  `migrations/versions/20260728_0068_graph_node_status_bindings.py`
- Runtime kernel: `apps/control_plane/agent_harness.py`
- Real execution-spine observer:
  `scripts/seed_project_engineering_execution_graph.py`
- Web projection: `web/features/agent-control/graph-console.tsx`
- Tests: `tests/test_agent_harness.py`,
  `web/lib/agent-graph-contract.test.ts`

The immutable status binding rejects cross-project targets and task drift. Workspace
status is projected only after observation freshness and dependency propagation.
Bound nodes expose state/freshness, why, blockers, owner, SLA, dependency IDs,
verifier/version, observation ID, next action, artifact, Evidence, workspace and the
binding hash. Unbound canonical nodes explicitly have no runtime status.

The stable execution spine covers Program, Project, Workstream, Release, M0→M4
Milestones, Requirement, ADR, Change, Code, Test, Build, Deploy, Observation,
Evidence, Risk, Decision, Owner, SLA, Dependency and Authority. Program/Project/
Workstream/Release derive from M4; each Milestone and Commerce Gate derives from its
exact M0→M4 task. The engineering slice derives from six real external verifiers.

## Migration and focused verification

The isolated database passed a complete empty upgrade to 0068, downgrade to 0067 and
upgrade back to 0068. The real 0067→0068 forward migration preserved
`1 project / 17 tasks / 27 observations / 43 nodes / 39 edges` exactly and created an
empty status-binding table.

Focused Python verifier tests: `19 passed`.
Focused Web contract tests: `55 passed`.
Focused Ruff and Python compilation: clean.

The rebuilt delivery images are:

- API `sha256:b36a3f3bbdf86a3893e37fa92c89b183e5794f97630b26f6ca2032cb12bb1682`;
- media worker `sha256:bbf671cceefaa9857c8d1b620b31a497340a4be9d5dab6923a84f15b98b2e60d`;
- Web `sha256:38106db54fd869ebd294f3f171248f087583c29723b06ccc813370a294896294`.

All four Compose services became externally healthy. The production Web build
generated `33/33` static pages and 33 routes.

## Browser and delivery acceptance

Desktop browser acceptance used the rebuilt delivery at `1280×720`.
`documentElement.clientWidth` and `scrollWidth` both measured `1265`; the page
contained 55 articles. Release 0.59 rendered `blocked · fresh`; the decision and
Milestone cards exposed why, next action, Owner, SLA, dependency, registered verifier,
Observation, artifact and Evidence. The in-app browser log was empty.

390px browser acceptance used an independent Chrome top-level responsive viewport,
calibrated to `391×844`; `matchMedia("(max-width: 420px)")` was true.
`documentElement.clientWidth` and `scrollWidth` both measured `370`, so there was no
horizontal overflow. Engineering Graph contained 34 articles. The
`GraphNodeStatusBinding` verifier-owned node detail was 305.6px wide and exposed its
real dependency and verifier drill path. There was no application error banner or
`Runtime.exceptionThrown`. Chrome reported only two unrelated extension resource
denials (`web_accessible_resources` and `chrome-extension://invalid`); no application
console error was observed.

The first desktop capture found a real overflow regression (`scrollWidth=3822`)
caused by unbroken verifier/Evidence references. The CSS was corrected with bounded
grid tracks and `overflow-wrap:anywhere`, Web was rebuilt, and both desktop and 390px
were remeasured. This acceptance therefore does not rely on a static contract test.

## Current operating truth and authority

M0 remains `no_data`; M1–M4 remain `blocked`. Program, Project, Workstream and Release
therefore cannot become passed. The status rail and TODO remain verifier-owned.

The final execution-spine seed is replay-safe at `23 tasks / 65 nodes / 68 edges /
32 immutable status bindings`. Its six engineering tasks are advanced only by the
external pytest, real 0068 database, resolved healthy images/containers,
authenticated live Graph API, real desktop/390 browser and immutable Evidence
observations. The authenticated live API returned `200` for workspace, Project Graph
and Engineering Graph and exposed 32 verifier-owned nodes.

- Release Gate remains REJECTED.
- External writes remain `false`.
- Model self-certification remains `false`.
- No Fact, Approval, Permit, Ozon write, supplier message, purchase, payment, price,
  inventory or advertising action is created by this slice.
