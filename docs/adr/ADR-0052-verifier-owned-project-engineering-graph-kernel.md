# ADR-0052 — Verifier-owned Project and Engineering Graph Kernel

## Status

Accepted for BAS-128 on 2026-07-28.

## Context

The Agent Harness already provides append-only observations, scoped/as-of reads,
fresh/stale evaluation, upstream invalidation and stable hashed Graph nodes/edges.
However, canonical Graph nodes had no explicit runtime status authority: the UI could
show task state beside a node, but it could not prove which registered GoalTask was
allowed to advance that node.

The project also lacked a first-class Program→Project→Workstream→Release→Milestone
execution spine and several engineering delivery entities. A static diagram or a
model-authored status field would repeat the exact authority problem the Harness is
intended to solve.

## Decision

Add an immutable, project-scoped `graph_node_status_bindings` relation. One canonical
node may have exactly one `status_source` binding to a GoalTask in the same project.
The binding content is hashed; changing its task target is rejected and requires a new
node version.

`AgentHarnessService.workspace()` derives node verification exclusively from the
bound task after all existing observation freshness and dependency propagation has
run. The projection includes:

- state and freshness;
- verifier/version and observation ID;
- why, blockers and next safe action;
- owner, SLA and dependencies;
- exact artifact, Evidence and workspace drill paths;
- immutable binding hash.

Unbound nodes return `verification: null`; they do not inherit a convenient model or
UI status.

The first execution-spine slice adds stable Program, Project, Workstream, Release,
Milestone, Requirement, ADR, Change, Code, Test, Build, Deploy, Observation,
Evidence, Risk, Decision, Owner, SLA, Dependency and Authority nodes and explicit
edges. Engineering delivery nodes bind to a six-step real verifier chain
(pytest→0068 database→images/containers→authenticated API→desktop/390
browser→Evidence). Program/Project/Release bind to M4; milestones and Commerce Gate
nodes bind to their exact M0→M4 tasks. Therefore the release remains blocked until the
real operating loop passes.

## Consequences

- Graph becomes a runtime execution index over the existing GoalTask/Observation
  kernel, not a second workflow engine.
- An upstream observation that changes or expires automatically makes bound
  downstream nodes stale through the existing task dependency rules.
- `as_of`, tenant/store scope, append-only observations and idempotent replay remain
  single-sourced in the Harness.
- Project and Engineering Graph cards can drill into real verifier, observation,
  artifact and Evidence references.
- This migration grants no external commerce authority; Release Gate remains
  `REJECTED`.

## Rejected alternatives

- Store a mutable state column on `graph_nodes`: it would create an unaudited second
  state machine.
- Derive status from node labels, colors or model output: it is self-certification.
- Duplicate task dependencies as executable Graph edges: stable Graph edges describe
  relationships; GoalTask remains the state/dependency authority.
- Add a separate graph database: it adds operational complexity without improving
  authority or freshness.
