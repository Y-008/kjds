# ADR-0073: Native exact-scope returns and after-sales control

- Date: 2026-07-30
- Status: Accepted for BAS-153
- Requirement: BR-127
- Decision owner: OMS and finance architecture
- Approval owner: Operations and finance leadership

## Context

KJDS already owns exact-scope formal Ozon Order/Return Facts through Native
OMS and exact-scope Order/Accrual/Settlement/Bank Cash cycles through Finance
Control. Those authorities are separate by design. Operators currently lack
one reliable view that connects a returned unit to its order, immutable
Evidence and observed refund/settlement consequence.

The system does not yet own a customer-message, service-case, platform
dispute or RMA subledger. A model-generated reply, Seller ERP page or private
endpoint cannot fill that authority gap.

## Decision

Add one pure read deep module:

`ScopedReturnsAfterSalesWorkspace.project(...)`.

It composes only:

- `ScopedOmsWorkspace`;
- `ScopedSettlementCashWorkspace`.

It does not create another Order, Return, Product, financial entry,
reconciliation, refund, service case or message truth. Router, Web and Agent
prompts remain shallow.

### Exact-scope admission

Principal, tenant, entity, store, current ScopeGrant authority and a
timezone-aware `as_of` are validated before either upstream is read. Missing
entity authority returns `no_data` with zero upstream reads. Native OMS is
read first; if no real returned order exists, Finance is not read.

Every upstream response must have the expected contract, exact scope and
cutoff, valid stable snapshot and untruncated result. Any drift fails closed.

### Return unit

The unit is an exact Order with one or more accepted `ozon_return` timeline
events. The server validates:

- unique Return external IDs and Fact IDs;
- exact order, Product and SKU binding;
- positive integer quantities;
- cumulative returned quantity not greater than ordered quantity;
- consistent currency and observed amount semantics;
- deterministic latest Return event and ordering;
- immutable Fact and Evidence lineage already validated by Native OMS.

The finance projection is queried by the exact order key. Zero or one exact
cycle is accepted. Multiple cycles, conflicting key, scope/as-of/hash drift
or a blocked latest reconciliation withhold affected monetary values.

Stages are:

- `return_observed`;
- `refund_finance_pending`;
- `refund_settlement_pending`;
- `refund_cash_pending`;
- `refund_reconcile_pending`;
- `refund_reconciled`;
- `variance`;
- `blocked`.

This projection reports observed state; it does not infer that an Ozon return
necessarily means money moved.

### Customer-service boundary

Until a later slice creates an authorized immutable service-case/message
authority, the response must expose:

- `customer_service_case_authority_available=false`;
- `customer_message_authority_available=false`;
- `platform_dispute_authority_available=false`;
- `rma_authority_available=false`;
- `status=gated`.

No private Seller ERP endpoint, Cookie, internal Token, CAPTCHA bypass or
page scrape may be used as a substitute. Official APIs, formal exports and
explicitly authorized adapters remain the only external intake paths.

### Agent and external-write boundary

The versioned Agent artifact may recommend internal tasks only. It cannot:

- create or change Order/Return Fact;
- create a refund, service case, RMA or dispute;
- send or draft-as-sent a customer message;
- create FinanceEntry or Reconciliation;
- create or decide Approval;
- issue or consume a Permit;
- call Ozon, a Seller ERP, bank, PSP or any external write surface.

## Schema decision

BAS-153 is a pure read composition. It adds no table and no migration.
Alembic remains at the single `20260730_0078` head. Customer-service cases
and messages require their own later authority design rather than a
speculative 0079 schema in this slice.

## Verification

BAS-153 must prove:

- zero upstream reads without entity authority;
- OMS no-return short-circuit before Finance;
- contract/scope/as-of/snapshot failure closure;
- duplicate and over-return rejection;
- deterministic filter/cursor/replay;
- exact finance-cycle binding and monetary withholding on drift;
- anonymous 401 and unauthorized store 403;
- Web all states at desktop and 390px;
- fresh Harness/Graph observations;
- all refund, message, case, Approval, Permit and external writes false.
