# ADR-0093: Isolated Local Demo Client Boundary

- Status: Accepted for BAS-190 contract freeze
- Date: 2026-08-03
- Owners: Local Demo Product, Web, Risk
- Machine lease: Lane K / `019fc654-03dc-7c71-a520-8f85918f3e44` / `10a07abb6575bf733110d49f0209b1172bfb4908`
- Scope: `ScenarioPack`, `DemoSession`, `LocalDemoGateway`

## Context

KJDS needs a portable full-chain commerce demonstration that can show sourcing,
PIM, listing, OMS, fulfillment, customer service, growth and profit workflows
without depending on a production account or network. A display-only package,
quota counter or connected-store badge must never become evidence of a real
Principal, entitlement, quota balance, Approval, Permit or provider action.

The production Web root also contains authenticated control-plane integration.
The demo therefore cannot be a mode flag inside that application. It is a
separate local client whose data, state and transitions are synthetic.

## Decision

The only module chain is:

```text
versioned ScenarioPack -> isolated DemoSession -> LocalDemoGateway -> local UI
```

`ScenarioPack` is immutable and content-addressed. It contains only `demo-*`
identities, deterministic timestamps and explicitly synthetic projections.
`DemoSession` is bound to one exact scenario ref, version and SHA-256 for its
whole lifetime. `LocalDemoGateway` is the only application interface and exposes
exactly `open_session`, `query`, `apply` and `reset`.

Every success, error, 404, 409 and idempotent replay uses the same top-level
envelope constants:

```json
{
  "demo": true,
  "synthetic": true,
  "non_billable": true,
  "external_side_effect_allowed": false,
  "real_principal_ref": null,
  "real_entitlement_ref": null,
  "real_quota_ledger_ref": null,
  "real_approval_ref": null,
  "real_permit_ref": null
}
```

No caller can override these values. Inputs containing tenant, entity, store,
Principal, credential, entitlement, quota-ledger, Approval or Permit identity
are rejected before a session is opened or advanced.

## Session and idempotency rules

1. Session identity is the only query and transition scope.
2. Access to another session returns the same non-enumerable 404 envelope for
   missing and foreign sessions. It contains no foreign ref, count or data.
3. `apply` requires an idempotency key and canonical payload hash.
4. Reusing a key with the same hash returns the original sequence, state hash
   and response with `network_invoked=false` and no new transition.
5. Reusing a key with a different hash returns 409
   `demo_idempotency_payload_drift`; sequence and state remain unchanged.
6. A changed SHA-256 for an existing scenario ref/version returns 409
   `demo_scenario_hash_drift`; existing sessions remain bound to their original
   pack and are not migrated.
7. `reset` deletes only the addressed local session and never touches browser
   login, production cache, account configuration or server data.

## Isolation contract

The local demo has no production imports, SQL repository, production API,
`/backend` proxy, external network, credential read, provider call, worker,
outbox, analytics SDK, remote font, update check or external write. It does not
read `.env`, `KJDS_API_KEY`, channel credentials, OAuth state, cookies or browser
storage used by another application.

Demo actions produce only `DemoTransition`. They do not create Evidence, Fact,
FinanceEntry, CommercialEntitlement, UsageLedger entry, Approval, ExecutionPlan,
Permit, Command, Receipt, CampaignGrant or platform write. UI labels use
`企业演示包 · DEMO`, `演示容量`, `场景店铺已连接`, `本地模拟完成`,
`生成预览` and `合成利润场景`; they never claim a real subscription,
authorization, billable quota, listing publication or Actual Cash CM3.

The future client lives below `clients/local-demo` and is not mounted under the
production Web root layout. Its build-time network policy must reject any
external hostname and any `/backend` request.

## Consequences

- BAS-190 freezes documentation and machine contracts only.
- BAS-191 may implement the domain package after a new lease.
- Migration, OpenAPI, API aggregation, MASTER_SPEC and production Web remain
  outside this lane.
- A future product can replace in-memory state only after a new ADR proves the
  persistence layer remains local, synthetic and non-authoritative.

## Rejected designs

- Modifying real entitlement, quota or authorization checks for a demo.
- Loading synthetic data into KJDS production repositories.
- Reusing production Principal or store scope as demo scope.
- Calling a provider and relabeling its result as an offline simulation.
- Hiding the demo markers in error, replay or export responses.
