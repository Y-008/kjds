# ADR-0087: Profit truth readiness and scoped FX evidence

## Status

Accepted for engineering. Business profit, Pilot, scale and external-write Gates remain blocked.

## Context

The retained Ozon market-recon bundle contains own prices in CNY, marketplace references and
finance operations that require RUB semantics, incomplete quantities, unresolved variant identity,
and no order-to-settlement-to-bank reconciliation. Legacy unscoped FX rows cannot safely authorize
a tenant/entity/store decision. A dashboard that turns these records into a profit number would
repeat the invalid mixed-currency conclusion that was already withdrawn.

The platform needs a single read path that shows every retained record, the exact reason it cannot
enter profit, and the owner/document required to unblock it. It must reuse Evidence, bundle,
Finance, Fact and Profit authorities instead of creating another ERP truth store.

## Decision

1. Complete FX evidence is exact-scope and immutable. It includes directed currency pair, Decimal
   rate, effective/expiry times, Evidence, source type, authority, purposes, content hash and
   idempotency key. Readiness requires the active direct pair needed by the retained product
   currencies and the declared profit purpose; an unrelated or expired pair cannot satisfy the
   Gate. Reverse or triangular conversion is never inferred by the persistence layer.
2. Legacy unscoped FX remains readable as a blocked candidate and is never decision eligible.
3. Ozon finance allocation is a read-only proposal. Exact SKU and single-SKU posting inheritance
   are allowed; itemless fees, missing timezone/currency and multi-SKU allocation remain
   quarantined. No proportional allocation is allowed.
4. Variant resolution accepts exact offer/platform SKU/barcode anchors. Model ID, title and
   category similarity create review candidates only. Source conservation is mandatory.
5. Fifteen cost legs remain individually `missing/observed/reviewed/actual`. Quantity, FX,
   identity and scenario/accrual/settlement/cash book evidence are separate gates.
6. `ProfitTruthReadinessWorkspace` composes these authorities into one exact-scope, read-only
   snapshot. It never writes Fact, FinanceEntry, decision snapshot, Permit or provider state.
7. Scenario, accrual, settlement and cash books are permanently separate. Missing order,
   settlement or bank cash authority produces `no_data`, never zero or a forecast substitute.
8. The Profit Command truth page uses the truth-readiness status, as-of time and snapshot hash in
   its hero. Every table displays server values; the client performs no profit arithmetic.

## Consequences

- Full data is retained even when unusable for decisions.
- Profit and Pilot stay blocked until complete scoped FX, reviewed cost/quantity evidence, formal
  order/accrual Facts, classified settlements and bank cash reconciliation exist.
- The API response can be large because it preserves operation and evidence queues. The Web
  renders bounded rows while the server retains full counts and drillthrough.
- Day 0 capability truth is granular: real Ozon catalog and finance reads passed; real order,
  settlement, bank cash and provider writes did not pass.
- Downside CM3, return/refund rate, CAC/ACOS, fulfillment lead time and working-capital thresholds
  remain `UNKNOWN` until operating and finance owners sign Evidence-backed definitions.

## Alternatives rejected

- Reuse legacy unscoped FX or infer inverse rates.
- Allocate itemless or multi-SKU finance amounts proportionally.
- Treat Product model ID or title similarity as an exact variant.
- Show scenario CM3 as actual cash profit.
- Add Kafka, Temporal, a vector database or a second profit store before the closed loop exists.
