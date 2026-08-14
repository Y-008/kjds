# ADR-0048 — Agent Harness and Canonical Graph

## Status

Accepted for the first BAS-123 vertical slice on 2026-07-28.

## Context

KJDS needs a persistent goal/TODO contract and seven connected Graph projections.
The status surface must be driven by external verifier observations rather than model
narration or a static diagram. A graph database would add a second operational data
authority before query scale requires it.

## Decision

Use the existing PostgreSQL authority and introduce one deep `Agent Control Plane`
module with append-only verifier observations and canonical graph objects:

- `GraphProject`
- `GoalContract` and `GoalTask`
- `VerifierRegistry`
- `HarnessObservation`
- `GraphNode` and `GraphEdge`
- derived `GraphSnapshot` and `GraphDiff`

The seven projections are `project`, `requirements`, `engineering`, `runtime`,
`evidence`, `commerce`, and `authority`. Stable identities are namespaced strings.
Every mutable representation has a canonical SHA-256. Edges state whether they are
`declared`, `parsed`, `runtime`, `evidence`, or `inferred`; inferred edges never
satisfy a Gate, promote a Fact, or authorize execution.

Verifier observations are append-only and freeze source, scope, observed time,
freshness window, verifier ID/version, input hash, result hash, authority class and
artifact/Evidence reference. A task can become `passed` only from a current successful
observation owned by its registered verifier. Changed upstream hashes make dependent
observations and tasks `stale`.

Authenticated reads are tenant scoped and optionally entity/store scoped. The module
has no connector, Approval, Permit, Repository write, or external-action capability.
Recording an observation is an internal verification write available only to
`admin`/`monitor`; it cannot mutate business facts or Gate decisions.

The first vertical snapshot is:

`BR-099 → ADR-0047 → migration 0065/service/routes/tests → Pytest observation →
real DB revision → image/container → live API → browser observation → Evidence →
Remaining Plan`.

## Consequences

- PostgreSQL remains the only operational database.
- Server-derived projections expose `fresh`, `stale`, `no_data`, `error`, and
  `forbidden` distinctly.
- Status UI shows changed/failed/blocked/stale/next-critical facts; drilldowns retain
  exact immutable observations.
- Verifier fault-injection tests are required so a missing artifact, hash change,
  false-green result, or expired observation cannot pass a TODO.
- A graph database may be reconsidered only after measured traversal latency or scale
  makes the extra operational cost preferable.

## Rejected alternatives

- Static Mermaid/UI graph: cannot establish runtime truth or freshness.
- Model-owned TODO status: allows self-certification and reward hacking.
- Immediate graph database: duplicates authority and increases backup, security and
  migration cost without measured need.
- Reading arbitrary shell commands from the API: creates an unsafe execution surface.
