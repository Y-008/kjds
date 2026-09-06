# KJDS Resource Budget Ledger Contract

## Purpose

`resource_budget_ledger.py` is the append-only control-plane authority for
resource limits used by Agents, models, tokens, databases, external APIs and
media generation. It records the budget and every reservation, consumption,
release and overrun as immutable events. It does not authorize payment or an
external platform write. This is the durable accounting foundation; until a
reservation is bound to an `ActionEnvelope`, Permit, actor, causation and
readback receipt, it is not sufficient to admit a side effect.

## Scope and invariants

- Every budget and event is exact-scoped by `tenant_id` and `budget_id`.
- Amounts are finite, non-negative `Decimal` values with one budget currency.
- `idempotency_key` is unique per tenant; a changed payload with the same key
  is rejected.
- `consumed` and `released` lifecycle events must reference a `reserved` event
  in the same tenant and budget, and their cumulative amount cannot exceed the
  parent reservation. `overrun` events may stand alone for explicit loss
  accounting.
- PostgreSQL reservation admission locks the budget row, checks available
  capacity and inserts the event in one transaction. This prevents two workers
  from reserving the same remaining capacity.
- The gross counters remain visible for reconciliation. A settled child reduces
  the parent's outstanding reservation, so available capacity is
  `limit - consumed - overrun - outstanding_reserved`.
- PostgreSQL update, delete and truncate triggers keep both budget tables
  append-only. Corrections are new events, never overwrites.

## API

- `POST /v1/economics/budgets/{budget_id}` creates a tenant budget (admin or
  compliance).
- `POST /v1/economics/budgets/{budget_id}/events` records a lifecycle event
  (operator, executor or admin).
- `GET /v1/economics/budgets/{budget_id}` returns the reconciliable snapshot,
  including `reserved`, `consumed`, `released`, `overrun`, `available` and
  `external_write_allowed=false`.
- `GET /v1/economics/guard-status?budget_id=...` can bind the economic guard to
  this exact tenant budget; when `budget_remaining` is omitted, it uses the
  ledger's `available` value and returns the source snapshot for drill-down.

Budget exhaustion is a fail-closed error. Any automation that reacts to a
threshold must still pass the existing Permit, readback, rollback and Kill
Switch gates.
