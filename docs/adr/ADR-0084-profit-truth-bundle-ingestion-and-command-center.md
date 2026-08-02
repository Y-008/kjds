# ADR-0084: Currency-safe profit truth, bundle ingestion, and command center

- Status: Accepted; implementation in progress
- Date: 2026-08-02
- Requirement: BR-136
- Delivery: BAS-161
- Owners: Product, Finance, Data, Engineering

## Context

The market-recon files contain valuable real observations, but their current
report crosses an unsafe semantic boundary: own Ozon prices are denominated in
CNY while market reference prices are denominated in RUB. The report renamed
the own price as RUB and compared the values directly. Finance captures and
some 1688 records also contain amounts without an explicit, evidenced currency.
Those artifacts may be retained as raw evidence, but their profit and repricing
conclusions are invalid.

KJDS already has deep authorities for Evidence, marketplace observations,
catalog, batch opportunity, actual profit, settlement, OMS, inventory,
sourcing and growth experiments. Creating a parallel ERP or a second fact
store would reduce cohesion and make profit results impossible to reconcile.

## Decision

1. Introduce an immutable `MoneyAmount` value with Decimal amount, ISO currency,
   aware occurrence time and Evidence ID. Currency conversion requires an
   explicit `FxBasis` with source/target currencies, positive Decimal rate,
   aware effective time and Evidence ID. The conversion operation rejects a
   mismatched basis; no implicit platform-default currency is allowed.
2. Permanently separate scenario, accrual, settlement and cash profit. A
   projection must label each basis and may not substitute one for another.
3. Invalidate the existing mixed-currency report. Keep the original artifact
   for audit, but remove it from decision input. A regenerated report may show
   currency-isolated observations; cross-currency margins require supplied FX
   Evidence.
4. Add one deep `MarketReconBundleIngestion` seam. It stores content-addressed
   raw artifacts through the existing Evidence authority, expands recognized
   records, classifies them without deletion, and records a bounded bundle run.
   It does not create a second Observation, Catalog, SupplierOffer or Fact
   authority.
5. Every source record has exactly one disposition: accepted or quarantined.
   `accepted + quarantined = source_total` is a database/application invariant.
   Missing currency, unresolved variants, identity conflicts and parse errors
   retain raw payload, artifact location and stable reason codes. Quality
   determines the highest usable stage, not whether the data is stored.
6. Bundle writes are exact tenant/entity/store scoped, idempotent and
   content-addressed. Reusing an idempotency key with different content is a
   conflict. Preflight performs no writes. Archive expansion is bounded and
   path-safe.
7. Add one `ProfitCommandWorkspace` composition seam over existing authorities.
   It does not reimplement their algorithms. It returns separate actual,
   estimated and risk-adjusted profit, raw money and FX lineage, quality,
   blockers and evidence drill-through. Missing authority returns `no_data` or
   `blocked`; it never manufactures a profitable candidate.
8. Persist executable decisions as immutable `ProfitDecisionSnapshot` records
   with scope, as-of, input/output hashes, algorithm version, FX/evidence
   lineage and expiry. Pilot creation is proposal-only and requires evidenced,
   positive downside CM3. Agent, dashboard and proposal records cannot create
   formal facts, approvals, permits or external writes.
9. Keep PostgreSQL, FastAPI, SQLAlchemy, Next.js and the existing Graph/Harness.
   Kafka, Temporal, a vector database, a second ERP and a PostgreSQL major
   upgrade are not prerequisites for this profit loop.

## Public Interface

```text
POST /v1/intelligence-ingestion/bundles/preflight
POST /v1/intelligence-ingestion/bundles
GET  /v1/intelligence-ingestion/bundles/{bundle_id}
GET  /v1/intelligence-ingestion/bundles/{bundle_id}/quality

GET  /v1/profit-command/workspace
GET  /v1/profit-command/candidates/{candidate_id}
POST /v1/profit-command/candidates/{candidate_id}/pilot-proposals
```

The Profit Command interface is intentionally smaller than the functionality
it hides. Drill-through links resolve to existing authorities rather than
duplicated details.

## Consequences

- All captured data can enter the system, but only sufficiently evidenced data
  can influence high-risk decisions.
- Existing invalid conclusions remain auditable while becoming unusable by
  Dashboard and Agent consumers.
- Initial candidates will often be `needs_data`; this is a correct business
  result until currency, variant, cost, settlement and cash evidence improve.
- The first revenue-oriented gate is stop-loss and small-pilot decision
  quality, not infrastructure expansion or autonomous execution.
