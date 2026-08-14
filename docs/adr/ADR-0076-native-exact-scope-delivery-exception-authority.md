# ADR-0076: Native exact-scope delivery exception authority

- Status: Accepted
- Date: 2026-07-30
- Requirement: BR-130
- Delivery: BAS-156

## Decision

The next must-have native-parity slice is delivery and logistics exception
control. Existing OMS and Inventory stop at platform lifecycle and fulfillment
demand; quote calculation is not shipment truth. Introduce one deep module,
`ScopedDeliveryExceptionWorkspace`, with one `project(...)` interface.

The implementation will compose exact-scope OMS Order, immutable logistics
events backed by current Evidence, Inventory, Returns, redacted Customer
Service and financial impact. It owns event ordering, state transitions, SLA,
exception classification, server filtering, opaque pagination and stable
artifacts.

## Safety

Missing entity performs zero reads. Latest bad authority fails closed without
fallback. Public tracking pages, legacy quote rows and private ERP endpoints
cannot become delivery facts. The Agent may suggest internal triage only; it
cannot contact a carrier or customer, change Order/Inventory/Return, approve
itself, issue a Permit or write externally.

No schema migration is authorized until immutable logistics-event persistence
is proven necessary. Any such change must be a new forward-only 0080; existing
0042 and 0079 remain immutable.
