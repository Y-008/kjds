# ADR-0077: Native exact-scope warehouse fulfillment authority

- Status: Accepted
- Date: 2026-07-30
- Requirement: BR-131
- Delivery: BAS-157
- Owners: Fulfillment, OMS, Inventory, Evidence, Agent Team
- Approver: Operating owner

## Context

The native OMS, Inventory and BAS-156 delivery projections do not yet provide
one exact-scope warehouse wave, pick-pack, scan and measured-weight workspace.
Legacy warehouse screens, static templates and carrier pages cannot become
warehouse facts. A source claiming success without an official or formally
authorized immutable read-only contract is not authoritative.

## Decision

`ScopedWarehouseFulfillmentWorkspace.project(...)` is the single composition
seam. It admits tenant/entity/store/as-of authority before every read, then
combines the existing OMS Order and Inventory authorities with a versioned
warehouse scan source. It does not create a second Order, Inventory, Shipment,
Return, Approval or Permit truth.

The persisted scan source is one append-only
`WarehouseExecutionAuthorityService`, introduced by forward-only migration
0080 after native location/bin/lot/reservation/wave/pick/pack/parcel/scan/
weight/handoff history proved to require its own authority. It stores only
formal observations and references the existing Product/SKU and Order
identities; it does not become a second Product, Order, Inventory or Delivery
truth. Updates and deletes are rejected by PostgreSQL triggers.

An admitted event must bind an official public API, authorized formal export
or explicitly authorized warehouse system to exact scope, adapter
identity/version, independent current authorization Evidence, immutable source
payload hash, revocation and as-of semantics. Private endpoints, Cookies,
internal Tokens, CAPTCHA or access-control bypass are prohibited.

The production database currently contains no admitted warehouse execution
event. Until an authorized source and real Order are present, the workspace
returns honest `no_data` or `scan_evidence_pending`; it cannot invent a wave,
package, scan, weight or handover fact.

Missing entity performs zero reads. No formal Order short-circuits before
Inventory or scan reads. Contract/scope/as-of/snapshot drift, revoked or
self-reported authority, private endpoints, Cookies, internal Tokens and
access-control bypass fail closed.

Agent output is suggestion and internal-task only. Wave/scan creation,
Inventory/Order/Shipment mutation, self approval, Permit issuance, carrier or
customer contact and every external write remain false.

Inventory adjustment, outbound confirmation, label purchase and carrier
handoff are L4 `policy_only` actions with no request route, service entry,
external call or executor. If a formal successful Readback is imported, it
must bind an approved database Approval with a distinct requester and decider,
an exact-scope versioned single-use Permit Evidence, a successful immutable
Readback Evidence with remote operation and resulting-state hash, Kill Switch
release Evidence and Compensation Evidence. Permit or receipt reuse fails
closed.

## Consequences

- The seam is executable before a real warehouse source exists, while business
  state remains `no_data/partial`.
- Positive source fixtures prove the contract only; they cannot prove that a
  production source exists.
- Forward-only 0080 adds only the append-only warehouse observation ledger and
  one-time Permit/Readback uniqueness; 0042 and 0079 remain unchanged.

## Acceptance

- exact-scope and zero-read early gates;
- no-Order short circuit;
- official/authorized immutable scan contract and failure closure;
- no invented package/weight/handover fact;
- server-owned counts/filter/cursor/snapshot/artifact;
- API/OpenAPI/Web/runtime/browser/Graph Evidence before
  `DONE_ENGINEERING`.

## Revisit triggers

Revisit when an official warehouse API, signed export or explicitly authorized
adapter is available, or when a governed write executor is independently
authorized. Read authority alone never activates a write path.
