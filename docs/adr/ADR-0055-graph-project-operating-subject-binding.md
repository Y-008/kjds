# ADR-0055 — Graph Project Operating Subject Binding

## Status

Accepted for BAS-131 on 2026-07-28.

## Context

The BAS-127 observer correctly required a dedicated `monitor` or `admin` recorder,
but it also used that recorder as the subject of Commerce OS and current scope-grant
verification. A monitor intentionally has no operating authority, so this projected
the monitor's scope state instead of the operator whose store state the Project Graph
is meant to verify. Reusing an admin recorder hid the defect but weakened the
dedicated-monitor boundary.

An environment-only actor name or request query parameter would not be a stable,
`as_of`-replayable project fact. Adding subject selection independently to Commerce
OS, the scope grant service and each Graph workspace would scatter identity policy and
make verifier inputs disagree.

## Decision

Keep operating-subject selection inside the existing Agent Harness deep module as an
append-only project event stream:

1. Alembic `20260728_0070` adds
   `graph_project_subject_binding_events` with `bind|revoke`, exact project,
   tenant/store, registered actor, effective time, recorder, reason, idempotency key
   and request hash.
2. Only an authenticated `admin` may bind or revoke. The target must be a registered
   non-admin, non-monitor `operator` in the exact project tenant/store and must differ
   from the recorder.
3. Exact retries are idempotent; payload drift, overlapping binds, mismatched revokes,
   future events and out-of-order history fail closed.
4. `operating_subject(project_id, as_of)` deterministically returns the binding that
   existed at the cutoff, or explicit `no_data` after no binding or revocation.
5. The observer remains owned by the monitor recorder, but resolves the bound subject
   through the server identity registry and evaluates Commerce OS plus
   `ScopeGrantAuthority.current` as that subject.
6. The binding hash and target actor enter every downstream verifier input hash.
   Changing the subject therefore appends new observations and makes older downstream
   results stale instead of silently reusing them.
7. A stable subject task, Authority Graph node, `status_source` binding and verifier
   Observation expose `why`, `next`, Owner, SLA and immutable drilldown. The current
   scope-grant task depends on this subject task.

The monitor still only records observations. The binding grants no entity authority,
Approval, Permit or external-write capability.

## Consequences

- Recorder identity and operating subject are explicit and independently auditable.
- A dedicated monitor can refresh Graph freshness without borrowing an operator or
  admin identity for the observed business projection.
- Historical Graph snapshots can reproduce subject changes with `as_of`.
- Missing or revoked binding blocks the observation cycle with zero Observation
  writes; an unregistered, privileged, cross-tenant or cross-store target is rejected.
- Release remains `REJECTED`; scope owner source/review/grant counts remain zero and
  all external commerce writes remain closed.

## Rejected alternatives

- Evaluate the monitor's own Commerce OS projection: observes the recorder, not the
  operating subject.
- Pass a subject actor in every observe request: mutable caller input is not canonical
  project state.
- Store one mutable `subject_actor_id` on `GraphProject`: loses event history and
  deterministic revocation replay.
- Bind an admin or monitor as the operating subject: collapses authority and
  observation roles.
- Create a synthetic operator or scope grant for acceptance: crosses the real
  external-authority boundary.
