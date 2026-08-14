# BAS-167–170 Profit Truth Readiness Evidence

Date: 2026-08-02

Scope: FX truth, finance allocation, variant identity, fifteen-cost evidence, order/settlement/cash
readiness and full-chain visualization. This record does not cover pricing, packages, GTM or any
commercial promise.

## Delivered engineering slices

| Slice | Authority | Result |
|---|---|---|
| BAS-167 | Scoped FX Evidence | Complete directed FX intake, expiry, source/authority/purpose, content hash, idempotency and persistence metadata |
| BAS-168 | Ozon Finance Allocation | Exact-SKU/read-only proposal, itemless and multi-SKU fail-close, amount/count conservation, no proportional allocation |
| BAS-169 | Variant + Cost Evidence | Exact-anchor identity graph, review candidates, source conservation and per-SKU fifteen-cost/quantity/FX/book request queue |
| BAS-170 | Profit Truth Readiness | Exact-scope API and Profit Command truth page from retained Evidence through four separate profit books |

## Current live PostgreSQL facts

The authenticated `GET /v1/profit-command/truth-readiness?store_ref=ozon-primary` returned:

| Fact | Current value |
|---|---:|
| Retained source rows | 374 / 374 |
| Raw Evidence stage | 338 |
| Normalized Observation stage | 36 |
| Reviewed Observation stage | 0 |
| Formal Fact stage / database | 0 / 0 |
| Decision snapshot stage / database | 0 / 0 |
| Ozon Product Info SKUs | 18 |
| Identity sources | 99 |
| Identity accepted / unresolved / quarantined | 93 / 6 / 0 |
| Exact identity groups | 21 |
| Finance operations | 114 |
| Finance entry proposals | 0 |
| Complete scoped FX | 0 |
| Legacy unscoped FX, decision eligible=false | 2 |
| Cost/quantity/FX/book evidence requests | 360 |
| Scoped FinanceEntry rows | 0 |
| Scenario / accrual / settlement / cash profit | `no_data` / `no_data` / `no_data` / `no_data` |

The readiness status is `blocked`. Count conservation passed for the retained bundle, identity
projection and finance operation projection. Finance amount conservation is not asserted because
the raw operations do not provide decision-eligible currency/time evidence.

## Blockers retained, not guessed

- `complete_scoped_fx_missing`
- `legacy_unscoped_fx_not_decision_eligible`
- `ozon_finance_operations_not_entry_eligible`
- `variant_identity_review_required`
- `fifteen_cost_evidence_incomplete`
- `accrual_profit_missing`
- `settlement_profit_missing`
- `cash_profit_missing`

The current Ozon finance payload uses naive `operation_date` values and lacks a decision-eligible
currency basis at operation level. The system retains the original operation ID, posting, item,
amount and Evidence, but does not infer timezone/currency or persist a FinanceEntry.

## Day 0 source-of-truth correction

- Passed: real Ozon catalog and finance read evidence is retained and its exact-scope read-only
  projection succeeds. This does not prove the BAS-160 managed Worker execution path.
- Not passed: real order authority, platform settlement reconciliation, bank receipt reconciliation
  and all provider writes.
- `channel-accounts workspace=ready` means only that the authorization-control workspace has a
  fresh bound account. It does not make BAS-160 or the profit loop ready.
- BAS-160 remains `IN_PROGRESS`; Actual Cash Profit and every scale/Pilot decision remain blocked.

## UNKNOWN requiring human input

The following values are deliberately not configured and must remain `UNKNOWN` until the operating
and finance owners sign an Evidence-backed formula, scope and validity window:

- downside CM3 threshold;
- return/refund rate threshold;
- CAC and ACOS threshold;
- fulfillment lead-time threshold;
- working-capital occupancy amount/rate/days threshold;
- operation timezone basis and currency source for retained Ozon finance rows;
- order, settlement and bank-cash reconciliation keys and source documents.

## External-write state

- `read_only_projection=true`
- `missing_values_guessed=false`
- `currency_inferred=false`
- `proportional_finance_allocation_performed=false`
- `formal_fact_promoted=false`
- `finance_entry_persisted=false`
- `pilot_proposal_allowed=false`
- `automatic_action_allowed=false`
- `external_write_allowed=false`

No listing, repricing, advertising, purchase, payment, refund, Approval, Permit or provider write
was created by this slice.

## Verification evidence

- Focused backend integration: 88 tests passed across truth readiness, FX, finance allocation,
  cost evidence, variant identity and finance regressions.
- API/profit-command contract integration: 63 tests passed after OpenAPI regeneration.
- ZiAgent focused suites: FX 22, finance allocation 10, cost evidence 19, variant identity 18.
- Web contract tests: 139 passed; production build completed with 62 routes, including
  `/profit-command/truth`.
- Ruff passed for all touched Python modules.
- Alembic has one head, `20260802_0087`; full empty-PostgreSQL upgrade, 0087 downgrade to 0086 and
  re-upgrade passed. The live development database is at 0087.
- API and Web containers rebuilt healthy; readiness returned HTTP 200 and unauthenticated truth
  access returned HTTP 401.
- Browser acceptance showed the live 374/99/114/0/360 projection on desktop and 390px. The mobile
  document had no horizontal viewport overflow; Actual Cash Profit remained `no_data`.
- The current `.runtime/G1_VERIFICATION.json` is regenerated by `scripts/verify-g1.ps1`; its result
  must be read directly and is not replaced by this narrative.
