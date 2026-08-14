# ADR-0057 — Exact-scope Authority Intake Workbench

## Status

Accepted for BAS-133 on 2026-07-28.

## Context

The scope authority domain already had dedicated owner-source, independent-review,
zero-write preflight and formal grant routes. The Authority Graph could explain the
missing chain, but it did not provide a safe executable handoff. A user would have
needed to assemble API payloads manually, and the Web client had no server-derived
read model for current exact-scope source/review Evidence or authenticated role
capabilities.

Rendering three forms without a read authority would only create a static shell. Letting
the browser scan the global Evidence ledger would leak scope and duplicate admission
rules outside their owner.

## Decision

Extend the existing `ScopeGrantAuthority` deep module with one read-only
`intake(principal, subject, store_ref, entity_ref, event_type, as_of)` interface:

1. It validates requester/subject tenant and store scope and permits cross-subject
   inspection only to registered authority-workflow roles.
2. An absent legal entity returns `input_required`; the service does not infer entity
   from tenant, store, session or Graph text.
3. Source and review records are selected by reserved contract, exact
   tenant/entity/store/subject/decision, effective time and `recorded_at <= as_of`.
4. Every included record passes immutable hash/current checks. Review acceptance also
   requires independent reviewer identity, exact checks and immutable source
   ID/hash Lineage. Invalid exact-scope records fail closed.
5. The projection returns stable contract/verifier identity, point-in-time freshness,
   requester roles, server-derived allowed actions, candidates, counts, blockers,
   why/next/Owner/SLA and a deterministic snapshot hash.
6. The Web workbench reads the real Web session and this projection. It submits only
   owner source, independent review and non-mutating preflight requests. The backend
   remains the authority for every role and separation-of-duty check.
7. The formal grant event endpoint is not referenced or exposed by the workbench.
   Artifact links drill into real Evidence and Lineage.
8. A registered external observer probes the live API/Web and compares real database
   source/review/grant counts before and after the read. It freezes the response and
   counts in a content-addressed artifact and drives stable BAS-133 Graph nodes.

## Consequences

- M0 now has an executable, endpoint-backed owner→reviewer→compliance handoff without
  fabricating Evidence or weakening admission.
- An operator-only session sees the real blocker and disabled actions; role UI is not
  treated as authorization.
- Historical intake does not see Evidence recorded after its `as_of`.
- The engineering slice can pass while formal M0 remains `no_data`.
- No grant, Approval, Permit or external commerce write is created by observation or
  browser acceptance.

## Rejected alternatives

- Add forms directly to the Graph with client-side filtering: duplicates authority and
  can leak cross-scope Evidence.
- List all Evidence through the generic endpoint: not an exact-scope authority.
- Enable the formal grant event route in the same workbench: collapses preflight and
  recorder separation into an unsafe shortcut.
- Seed a source/review pair for acceptance: synthetic authority Evidence cannot satisfy
  a real M0 Gate.
- Treat a role label in the session response as sufficient authorization: the API must
  re-enforce identity, store and separation-of-duty rules.
