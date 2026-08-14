# ADR-0051 — Monitor-owned Operating Gate Observation Loop

## Status

Accepted for BAS-127 on 2026-07-28.

## Context

ADR-0050 defined a pure dynamic M0→M4 verifier and a bounded seed adapter. A seed
proves the verifier, but it does not make freshness operational: a current observation
can expire while the Commerce OS or PostgreSQL changes. The existing 24×7 health loop
already owns fail-closed Evidence scans and Windows Task deployment controls.

The scheduler must not inherit an admin/operator credential, and a missing monitor
identity must not be hidden by a successful readiness probe.

## Decision

Add one runtime `OperatingGateObserverService` and one authenticated endpoint:

`POST /v1/agent-control/projects/{project_id}/observe?store_ref=...`

Only a `monitor` or `admin` principal in the exact tenant/store scope may call it. The
service reads bounded PostgreSQL aggregates at Alembic `20260728_0069`, requests the
authenticated Commerce OS projection at a UTC hour bucket, calls the pure
`OperatingStageVerifier`, and appends five Agent Harness observations. It performs no
commerce write and returns only a sanitized result/hash/count contract.

`run-24x7-health.ps1` calls this endpoint with the dedicated monitor identity and
fails non-zero on missing identity, non-200 response, revision/contract drift, open
external writes or model self-certification. The Windows Task manager and G-1
verification preflight require this observation together with the Evidence scan.

The observation endpoint remains available while the Kill Switch is engaged because
it is a read/verification safety function, not a business mutation.

## Consequences

- Freshness has a real runtime entry point and a single scheduler seam.
- Repeating the same identity/input/hour bucket is idempotent; changed external
  state creates an append-only observation.
- Deployment remains blocked until the configuration owner supplies a dedicated
  monitor credential visible to the scheduled task. No existing admin/operator key
  is silently reused.
- The endpoint cannot create Fact, Approval, Permit, Listing, purchase, payment,
  price, inventory, advertising or any other external write.

## Rejected alternatives

- Treat the seed script as a scheduler: it has no deployed identity or health-loop
  ownership.
- Reuse an admin/operator credential: it violates least privilege and hides the
  configuration blocker.
- Let the model report that freshness is current: it is not an external observation.
- Mark scheduler deployment complete after registration alone: three consecutive
  native successful task results are still required by BAS-040.
