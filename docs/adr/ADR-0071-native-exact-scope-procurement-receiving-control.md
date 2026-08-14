# ADR-0071: Native exact-scope procurement and receiving control

- Date: 2026-07-29
- Status: Accepted for BAS-151
- Requirement: BR-125
- Decision owner: Procurement architecture
- Approval owner: Operating and finance leadership

## Context

KJDS already has canonical Product, governed Supplier Offer and Profit
Scenario, independent procurement Approval, Sample Purchase Order and
append-only procurement events. The sale-triggered policy can open an internal
review from a formal Order Fact. These are real implementation seams, but the
sample order and event rows are legacy global records and the current list
routes cannot prove tenant/entity/store authority.

The codebase has no authoritative accounts-payable invoice or supplier
payment ledger. Calling the current surface “Purchase-to-Pay” would therefore
invent a completed business chain.

## Decision

### One deep read module

Add:

`ScopedProcurementReceivingWorkspace.project(...)`.

The module owns exact-scope validation, source reading, event-state
verification, server filtering, pagination, counts, blockers, artifact and
snapshot hashing. Router, Web and Agent prompts remain shallow.

It reuses:

- `sample_purchase_orders`;
- `sample_procurement_events`;
- Canonical `products`;
- `source_offers`;
- `profit_scenarios`;
- independent `approvals`;
- Evidence and scoped Evidence binding.

It does not create another Product, Supplier, Offer, Scenario, Approval,
purchase-order or receipt store.

### Forward-only 0077 authority

Migration 0077 adds complete-or-empty:

- tenant;
- entity;
- store;
- ScopeGrant authority hash;
- source Evidence hash;
- scope as-of.

to existing Sample Purchase Order and Procurement Event rows. A scoped
purchase order additionally references one authority Evidence record. Exact
scope and event timeline indexes support bounded reads. Legacy rows remain
all-null and are never inferred into an entity.

This slice does not modify an already applied migration.

### Projection contract

Each included purchase order exposes:

- exact Product ID, SKU and name;
- supplier, Offer and Profit Scenario identity;
- independently approved procurement basis;
- quantity, unit price, currency and server-calculated order value;
- current stage and ordered event timeline;
- supplier confirmation, shipment, receipt, damage and inspection facts;
- Evidence, Owner, SLA and next workspace;
- AP and Payment as explicit `no_data/gated`;
- stable row and collection hashes.

Server stages remain:

`approved_to_order → order_confirmed → shipped → received → inspected → golden_sample_approved`

with the existing rejection, rework and cancellation branches. Latest invalid
events fail closed; the module never falls back to an older successful stage.

### Failure boundary

The affected order is excluded and its monetary/identity payload withheld
when any of the following occurs:

- malformed or missing entity authority;
- cross-scope or future record;
- damaged, revoked or mismatched Evidence;
- Product, Offer, Scenario or Approval binding drift;
- Approval is not independently approved for the exact Scenario;
- Scenario is incomplete, has unknown cost, nonzero other cost or non-positive
  CM3;
- event sequence, transition, time, required facts or Evidence hash drift;
- duplicate/conflicting event authority;
- receipt, damage or inspection quantities do not conserve.

Source truncation blocks the projection.

### Agent and execution boundary

The projection and its Agent artifact may recommend or create internal tasks
only. They cannot:

- create or edit a purchase order or event;
- contact a supplier;
- place, cancel or confirm an external order;
- confirm receipt or inspection;
- change Product, Offer, Scenario, Approval, Permit or Inventory;
- create a payable or payment;
- initiate refund, dispute or any external write.

Agent self-approval and Permit issuance remain prohibited.

### AP and Payment boundary

No AP/Payment object is introduced in BAS-151. Both remain explicit
`no_data/gated`. A later slice must freeze invoice, payable, payment,
independent Approval, Permit and Bank Readback authority before KJDS can claim
Purchase-to-Pay.

## Rejected alternatives

- Treat legacy sample orders as tenant-scoped: rejected because authority
  cannot be inferred.
- Build business logic in the Web or Router: rejected because it creates a
  second state machine.
- Call Sample Purchase Order a production supplier PO: rejected because the
  object and approval basis are narrower.
- Reuse source URL, Cookie or private Seller ERP/1688 endpoints as order
  authority: rejected because they are revocation-unsafe and unauditable.
- Infer supplier payment from a procurement event or Actual Cash CM3:
  rejected because neither is an AP/Payment source.

## Verification

BAS-151 must prove:

- zero raw read before valid entity authority;
- exact SQL scope and as-of isolation;
- deterministic replay and opaque cursor;
- bad latest Evidence/event failure without fallback;
- event transition and quantity conservation;
- anonymous 401 and unauthorized 403;
- forward-only 0077 empty/live/downgrade-forward replay;
- Web no_data/partial/blocked/error/retry at desktop and 390px;
- fresh Harness/Graph observations;
- all purchase, inventory, payable, payment, Approval, Permit and external
  write flags remain false.
