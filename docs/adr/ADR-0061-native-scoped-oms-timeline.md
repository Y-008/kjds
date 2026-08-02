# ADR-0061: Native scoped OMS current-order timeline

- Status: Accepted for BAS-141 implementation
- Date: 2026-07-29
- Owners: OMS, Evidence, Fulfillment, Customer Service and Agent Operations
- Requirements: BR-084, BR-093–096, BR-101, BR-114, BR-115
- Depends on: ADR-0037, ADR-0047, ADR-0049, ADR-0060

## Context

KJDS has a legacy mutable `orders` table and create-order route, but those rows
do not carry tenant/entity/store/grant or immutable Evidence authority. Native
Ozon imports now promote scoped append-only `ozon_order` and `ozon_return`
Facts. An AI ERP must not merge the legacy table into the same truth surface or
let an Agent infer the current order from whichever row it sees first.

## Decision

Add one read-only `ScopedOmsWorkspace` deep module. Its interface accepts an
authenticated Principal, the current entity-scope projection, store and
deterministic `as_of`; its implementation:

1. reads only formal Facts under the exact tenant/entity/store/grant;
2. rejects facts outside `scope_as_of/effective_at/recorded_at <= as_of`;
3. verifies immutable Evidence bytes and the Fact-bound source hash;
4. groups order Facts by `external_id`, keeps an ordered immutable timeline and
   derives current state only from the latest candidate row; if that latest row
   fails hash/Evidence/contract validation, the order becomes `blocked/unknown`
   and the prior valid state is retained only as history, never reused as current;
5. attaches return/cancellation Facts only through explicit external order and
   exact Product/SKU identity;
6. exposes Decimal strings, explicit currency and Evidence/Fact IDs without
   customer PII;
7. projects deterministic Owner/SLA/next-workspace and Agent suggestions as
   internal decision support only;
8. may read related existing OperatingTasks, but creates no task on GET.

The module never reads the legacy `orders` table. Legacy rows remain available
only to old compatibility paths and cannot become native OMS truth.

## Status semantics

- `no_data`: entity authority or formal Order Facts are absent.
- `partial`: at least one valid order exists, but another scoped row has bad
  Evidence, unknown lifecycle semantics or an unresolved Product/SKU link.
- `ready`: all returned current orders and timeline events satisfy the contract.
- `blocked`: scoped candidate rows exist but none can safely become an order.

Current lifecycle values are server-normalized from explicit Ozon statuses.
Unknown statuses remain visible as `unknown` plus a blocker; they are never
guessed into shipped, delivered, cancelled or returned.

Pagination uses an opaque cursor over the complete server sort key
`(current_event.effective_at, external_order_id)`. The cursor is part of the
read contract and cannot be replaced by client sorting or a bare order ID.

## AI authority

The OMS Agent receives only the frozen server snapshot and may propose an
internal next-action artifact. It cannot change order state, contact a buyer,
create supplier orders, pay, approve itself, issue a Permit or call Ozon write
operations. Agent input and output include the workspace snapshot SHA-256.

## Compatibility and delivery

- Add authenticated `GET /v1/oms/workspace`.
- Anonymous access is 401 and cross-store access is 403.
- No schema migration is required; 0072 already provides the exact-scope order
  lookup index.
- OpenAPI and Web must consume the same server result; clients must not
  recalculate current status.

## Verification

BAS-141 must cover exact scope, as-of determinism, latest-state wins, ordered
timeline, distinct orders, return linkage, replay, cross-tenant isolation, bad
Evidence, unknown status, missing entity authority, legacy exclusion, anonymous
401, cross-store 403, no read side effects and external writes false.
