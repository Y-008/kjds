# BAS-127 Operating Gate Observation Loop — Engineering Evidence

## Decision

`BAS-127` engineering implementation is accepted. Scheduled runtime deployment is
still `BLOCKED_CONFIG` under BAS-040. Release, Pilot and Final Gates remain open, and
Release Gate remains `REJECTED`.

## Implemented contract

- Requirement: `BR-103`
- Architecture: `ADR-0051`
- Runtime observer: `apps/control_plane/operating_gate_observer.py`
- Authenticated endpoint:
  `POST /v1/agent-control/projects/{project_id}/observe`
- Scheduler integration: `scripts/run-24x7-health.ps1`
- Deployment preflight: `scripts/manage-evidence-health-task.ps1`
- G-1 verification: `scripts/verify-g1.ps1`
- Tests: `tests/test_operating_gate_observer.py`,
  `tests/test_health_loop.py`

The observer uses the caller's authenticated tenant/store scope, reads the real
PostgreSQL revision and bounded aggregate counts, requests the Commerce OS projection,
calls the pure M0→M4 verifier, updates observed Gate hashes and appends five registered
runtime observations. It returns a sanitized
`kjds-operating-gate-observer-v1` contract and cannot perform a commerce write.

The health loop requires Alembic `20260728_0068`, an exact observer contract, closed
external writes and disabled model self-certification. Missing monitor identity,
identity drift, an API failure or a contract mismatch returns non-zero.

## Live result and deployment boundary

The endpoint was exercised against the real delivery stack with an authorized admin
identity before the dedicated scheduled identity exists. It returned `200`, M0
`no_data`, M1–M4 `blocked`, external write `false` and model self-certification
`false`; the observed hour-bucket result hash was
`2990d786fd9768c3b185c45bd5cb327444b5498c9387ec2f7e0845930f3ad34f`.

The real `.env` has no `KJDS_MONITOR_API_KEY`, its multi-identity map has no monitor
profile, and the Windows Evidence health task is absent. `ControlPlaneOnly` therefore
failed closed after the public health probe, and explicit Install returned
`mutation_performed=false`, `status=preflight_failed`; no task was registered.

This is the correct least-privilege outcome. The configuration owner must provide a
dedicated task-visible monitor identity; an admin/operator key was not reused. BAS-040
then still requires registration audit and three consecutive native successful runs.

## Safety

- No Fact, Approval, Permit or business ledger was written.
- No Ozon, supplier, purchase, payment, price, inventory or ad action was sent.
- No credential is stored in Graph, Evidence, logs or this document.
- External writes remain closed.
