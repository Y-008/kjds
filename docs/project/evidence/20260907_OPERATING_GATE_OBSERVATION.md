# 2026-09-07 operating Gate observation

The local control plane was restarted after a targeted fix in
`ScopedContentMediaFactoryWorkspace`: the blocked product-content projection
now passes its explicit `raw_product_content_read` state into the read-only
result envelope. Before the fix, the monitor route raised a `TypeError` and
returned an unstructured HTTP 500. The fix is covered by
`tests/test_scoped_media_factory.py` and the focused media/project-contract
tests pass.

With the same local PostgreSQL runtime and the exact `ozon-primary` scope, the
monitor-owned route completed successfully:

```text
POST /v1/agent-control/projects/kjds-059-bas123/observe?store_ref=ozon-primary
HTTP 200
database_revision=20260907_0120
observation_bucket=2026-09-07T02:00:00+00:00
status=blocked
operating_subject=r0-requester
scope_authority=passed
m0..m4=blocked
tasks=133 observations=923 nodes=267 edges=260
external_write_allowed=false
model_self_certification_allowed=false
workspace_snapshot_sha256=11c6c083dc74e2f265de4c9c061ae0665fb9d37c00cf6e4d3c38f82b84700322
result_sha256=9edfc6934efd5e4579f893e821606cf61fa544d8b0d50d60afb612c5f8d37fb1
```

The observation only appends internal graph evidence. It did not call an
external Ozon endpoint and did not issue a Permit, listing action, price
change, inventory change, or publication.

The subsequent exact-scope graph read remains `BLOCKED`. Its current state
counts are 333 `STALE`, 33 `NO_DATA`, 29 `BLOCKED`, and 5 `PROVEN`; the critical
path targets `task-m4-actual-cash` and has length 17. These states represent
freshness and evidence debt in the existing graph, not a claim of Ozon
production readiness. Official Ozon readback, a current managed runtime lease,
RealFBS confirmation, and bank-origin evidence remain separate blockers.
