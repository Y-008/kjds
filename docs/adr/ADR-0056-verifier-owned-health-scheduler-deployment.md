# ADR-0056 — Verifier-owned Health Scheduler Deployment Observation

## Status

Accepted for BAS-132 on 2026-07-28.

## Context

BAS-040 requires a real Windows Task that runs the control-plane health loop every
15 minutes, uses a secret-free command, refuses overlap and has at least three
consecutive successful completions. BAS-127 provided the health and installation
scripts, but the live deployment remained visible only as a plan row and transient
shell output.

That state was not part of the canonical Project/Runtime/Authority Graph. A static
`BLOCKED_CONFIG` label could become stale, could not link to the exact Task definition
or health result, and could not be advanced exclusively by an external verifier.

## Decision

Create one pure `HealthSchedulerDeploymentVerifier` deep module with a single
`evaluate(task_audit, health_preflight, observed_at)` interface:

1. The caller obtains real JSON from read-only
   `manage-evidence-health-task.ps1 -Mode Audit` and
   `run-24x7-health.ps1 -ControlPlaneOnly`.
2. The verifier validates the exact Task name/path, 15-minute interval, 5-minute
   execution limit, `IgnoreNew`, one exact secret-free Action, working directory,
   last result, completion history and at least three consecutive result-0 events.
3. It independently recomputes `definition_valid` and `accepted`; contradictory
   self-reported booleans are contract failure, not success.
4. It requires current `snapshot`, control-plane readiness, operations readiness,
   Evidence integrity and Agent Gate observation to be healthy.
5. Malformed or contradictory contracts return `failed`. Missing Task, credentials,
   successful history or health return `blocked`. Only every exact external
   condition being true returns `passed`.
6. The orchestration adapter freezes both raw payloads, both process exit codes,
   observed time and verifier hashes into a content-addressed local artifact, then
   appends a registered Agent Harness Observation.
7. Stable BAS-132 engineering nodes use the external pytest verifier. Stable
   scheduler/runtime/authority nodes use the deployment verifier, so engineering
   completion and real deployment truth remain separate.

The observation path never calls Install. Installation remains an explicit operations
action after scheduler-visible configuration is supplied.

## Consequences

- Project/Runtime/Authority Graph, status rail and TODO show the real current Task and
  health blockers with immutable artifact drilldown.
- A later valid installation and three real successes can advance the same stable
  nodes without code or plan edits.
- The deployment verifier expires after 20 minutes, matching the 15-minute cadence
  with bounded scheduling tolerance.
- Current missing Task and credentials remain `blocked`; Release remains `REJECTED`.
- No credential is stored in the artifact, no runtime identity is borrowed, and no
  business fact, Approval, Permit or external write is created.

## Rejected alternatives

- Mark BAS-040 passed because the installer script exists: code presence is not
  deployment evidence.
- Parse only process exit code: it cannot prove the exact Task definition, history or
  current health sections.
- Trust `accepted=true` from the audit JSON: a drifted producer could self-certify.
- Install the Task during Graph observation: a read verifier must not mutate external
  scheduler state.
- Copy admin/operator credentials into the Task command: violates separation of duties
  and leaks secrets into scheduler metadata.
