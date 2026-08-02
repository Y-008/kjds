# ADR-0053 — Scope Authority Admission and Graph Observation

## Status

Accepted for BAS-129 on 2026-07-28.

## Context

M0 already has an append-only `ScopeGrantAuthority`, but the real tenant currently
has no owner-authorized entity/store grant. Creating a convenient grant from an
admin session would cross the external authority boundary. Leaving only the final
record endpoint also forces an account owner and independent reviewer to discover
Evidence, separation-of-duty and frozen-scope errors at commit time.

The Authority Graph must show this as a live verifier-owned blocker. A static
“missing grant” label or model-authored TODO is not sufficient, and a count of grant
rows is not proof that the current principal has one exact current grant.

## Decision

Add one non-mutating admission operation to the existing deep module:
`ScopeGrantAuthority.preflight(...)`. It freezes the exact same request as
`record(...)` and both paths reuse the same Evidence validation. The verifier checks:

- authenticated tenant and exact store scope;
- an independent recording actor and subject actor;
- a current grade B owner source and accepted grade A review Evidence;
- exact tenant/entity/store/subject/decision/effective-time metadata and immutable
  source→review lineage;
- four distinct authenticated owner/reviewer/recorder/subject actors;
- immutable idempotency-key compatibility.

The response is a point-in-time verifier artifact with a request hash, blocker codes,
Owner, SLA and next safe action. It never records a grant, creates Approval/Permit or
enables an external write.

The existing monitor-owned operating observation loop also reads
`ScopeGrantAuthority.current(...)` for the exact monitor principal and appends a
sixth observation bound to `task-m0-scope-authority-admission`. The stable
`authority:current-scope-grant` node obtains status only from that task. `passed`
requires one current independently evidenced entity grant; missing authority remains
`no_data`, and invalid/ambiguous authority remains `blocked`.

## Consequences

- Owner material can be checked before an immutable governance event is recorded.
- Uploader-authored `reviewed_by` metadata cannot impersonate an independent review;
  the hardening contract is defined by ADR-0054.
- Preflight and commit cannot silently drift because they share validation and
  request hashing.
- The Authority Graph exposes the real current projection, verifier, Observation,
  Owner, SLA and next action.
- A row for another actor or store cannot pass this task.
- Dedicated monitor deployment is still required for continuous freshness; the
  current missing monitor credential/Windows Task remains a deployment blocker.
- Release Gate remains `REJECTED`; all Ozon, supplier, purchase, payment, price,
  inventory and advertising writes remain closed.

## Rejected alternatives

- Create a synthetic grant for engineering acceptance: invents owner authority.
- Treat `scope_grant_events > 0` as ready: ignores actor, store, effective time,
  revocation, ambiguity and damaged Evidence.
- Add a second mutable “grant request” authority table: duplicates the append-only
  ledger and creates another state machine.
- Let Graph labels or model output determine readiness: self-certification.
