# BAS-161 Currency-safe profit truth and full bundle evidence

- Date: 2026-08-02
- Requirement: BR-136
- Status: COMPLETED_ENGINEERING
- ADR: `docs/adr/ADR-0084-profit-truth-bundle-ingestion-and-command-center.md`

## Delivered

- Evidence-bound Decimal `MoneyAmount` and `FxBasis` with no implicit currency.
- Invalidated mixed CNY/RUB report and currency-isolated replacement outputs.
- Exact-scope, bounded, idempotent `MarketReconBundleIngestion` with full
  accepted/quarantine conservation and immutable raw Evidence.
- Separate scenario, accrual, settlement, cash and risk-adjusted Profit Command
  bases, immutable decision snapshots and proposal-only Pilot requests.
- Workspace, candidate detail, server collection, analytics, portfolio and
  lineage projections with no synthetic history.

## Current PostgreSQL observation

```text
bundle_id: mrb_914c77fce9c5458aa247762f28a02806
source_total: 374
accepted: 49
quarantined: 325
conservation: 49 + 325 = 374
profit_candidates: 18
needs_data: 18
pilot: 0
actual_cash_profit: no_data
external_write_allowed: false
```

The bundle contains the current Ozon Catalog/Product/Analytics/Finance, 1688
supply collection and Browser Capture files. Quarantine is retained raw data,
not deletion. No FX, exact variant, settlement or bank cash fact was invented
to make candidates profitable.

## Verification

- Money, report, ingestion and Profit Command focused tests passed.
- Bundle replay is idempotent; content drift conflicts.
- Cross-tenant and cross-store reads fail closed.
- The live database is at Alembic head `20260802_0086` after the additive
  BAS-162 migration.

This is engineering and local-data acceptance, not evidence of achieved
commercial profit or a production Pilot.
