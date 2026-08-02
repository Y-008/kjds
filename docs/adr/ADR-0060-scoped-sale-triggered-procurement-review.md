# ADR-0060: Exact-scope sale-triggered procurement review

- Status: Accepted for BAS-140 implementation
- Date: 2026-07-29
- Owners: OMS, Procurement, Evidence, Finance and Agent Operations
- Requirements: BR-070, BR-084, BR-093–096, BR-101, BR-114
- Depends on: ADR-0035, ADR-0037–0040, ADR-0047, ADR-0049

## Context

KJDS already preserves a safe business rule: no supplier order or payment
before a real Ozon order. The existing `SaleTriggeredProcurementPolicy`,
however, reads only the legacy unscoped `FactRepository.list()` projection.
Native Ozon order Facts promoted under tenant/entity/store authority are
therefore invisible to the procurement review. The legacy implementation also
evaluates every historical row independently, so an old `awaiting_packaging`
row could survive a later cancellation for the same order.

That gap prevents the native OMS Fact ledger from handing a real order to
Procurement, and makes a future automatic purchase unsafe.

## Decision

### One current-order authority

`SaleTriggeredProcurementPolicy` remains the only order-to-procurement
decision module. Its native path reads `FactRecordRow` directly under the
frozen tuple:

`tenant_ref + entity_ref + store_ref + scope_grant_authority_sha256`.

It also requires an exact scoped Product, `scope_as_of`, `recorded_at` and
`effective_at` at or before the requested cutoff. Native evaluation never
falls back to legacy rows and never infers another tenant, entity, store or
grant.

For every Ozon `external_id`, the module first selects the latest row by
`effective_at`, `recorded_at` and stable Fact ID. Only that current row is
eligible. A later cancelled, returned or otherwise non-trigger status
supersedes an older `awaiting_packaging` row. Multiple distinct current
triggering orders are summed exactly as integer units; the response retains
all triggering Fact, Evidence and external order IDs.

### Procurement is still an internal review

A current order may create one stable task in the existing
`OperatingTask`/`OperationsQueue` ledger:

- `sale_triggered_procurement_review` when current supply checkout and complete
  positive downside CM3 are still valid;
- `sale_triggered_procurement_escalation` when the order exists but supply or
  economics must be repaired.

The task freezes exact scope, Product, current order set, quantity, Evidence,
blockers, Owner, SLA and next action. It does not create a new queue or workflow
engine.

`eligible_for_procurement_review` is not purchase approval. The invariant
remains:

- `supplier_order_created=false`;
- `payment_created=false`;
- `automatic_procurement=false`;
- `external_purchase_write=false`.

A later purchasing slice must still use independent Approval, a one-time
purchase Permit, checkout Readback, Kill Switch and Compensation. This ADR
does not authorize that slice.

## Data and compatibility

The policy contract advances to `sale-triggered-jit/1.1.0`. Legacy calls without
scope remain readable and retain the no-write semantics. Scoped batch runs pass
their already validated authority tuple into the policy.

Forward-only migration 0072 adds a composite read index for exact-scope
order/Product/as-of lookup. It changes no Fact rows and creates no new source
of truth.

## Verification

BAS-140 must prove:

1. native Fact rows are selected only under exact tenant/entity/store/grant;
2. legacy and another tenant/store/grant cannot trigger a scoped review;
3. an exact scoped Product is required;
4. future `scope_as_of`, recorded or effective rows are invisible at cutoff;
5. latest cancellation supersedes an earlier triggering status;
6. distinct active orders sum integer quantities without replay duplication;
7. missing/bad Evidence, SKU, currency, quantity or revenue fails closed;
8. eligible and escalation states create stable internal tasks visible through
   the existing Operations Queue;
9. no supplier order, payment, Approval, Permit or external write is created;
10. empty PostgreSQL base→0072, 0072→0071→0072 and real 0071→0072 preserve
    current Observation, Evidence and Fact rows;
11. backend, Web/API contract, container health and anonymous/cross-store
    authorization gates remain green.

## Consequences

The native OMS ledger can now wake Procurement from real orders without buying
anything. Cancellations and scope changes fail closed, while supply or profit
drift becomes an explicit internal escalation instead of an accidental order.
