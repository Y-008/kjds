# KJDS Project Graph Proposal Ledger Contract

`dispatch-wave` and `invalidate` compile internal planning projections. They
remain proposal-only: neither endpoint submits a TeamAgent task, acquires a
lease, issues a Permit, calls an external provider, or mutates an Ozon account.

The planning response is nevertheless an auditable business control-plane
artifact. `project_graph_proposals` stores one immutable row for each scoped
proposal with:

- exact `tenant_id`, registered `entity_id`, `project_id`, `store_ref` and
  proposal `kind` (`dispatch-wave` or `invalidation`);
- a caller idempotency key, complete request SHA-256, proposal SHA-256 and
  payload SHA-256;
- the graph snapshot hash, status, observed/recorded times and recorder;
- the detached JSON response, with `external_write_allowed=false` enforced by
  both the application contract and a database check;
- a monotonic revision per exact scope and kind.

A retry with the same scoped key and request digest returns the original JSON
payload, even if the live graph has changed. Reusing a key with a different
request returns a structured `409 project_graph_proposal_conflict`. Optional
`expected_revision` is a compare-and-swap guard for callers that need to
append a proposal only after a known ledger revision. Concurrent revision
allocation is resolved by database uniqueness and bounded readback retries.

The read contract is:

```text
GET /v1/project-graph/{project_id}/proposals
GET /v1/project-graph/{project_id}/proposals/replay?kind=...&idempotency_key=...
GET /v1/project-graph/{project_id}/proposals/{proposal_id}
```

All reads first authorize the current graph scope and then apply tenant/entity/
store filters in the ledger adapter. A missing graph entity is a hard block;
the service never invents a tenant-wide fallback scope. The ledger is not a
substitute for canonical graph events: reviewed invalidations must still pass
the graph authority's own approval, evidence, Permit, readback and rollback
gates before any future executor can act.

Schema ownership is Alembic revisions `20260906_0110` and
`20260906_0111`; the latter adds database-level append-only triggers.
