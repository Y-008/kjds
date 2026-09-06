# KJDS Analytics Metric and Period Contract

| Field | Value |
|---|---|
| `doc_id` | `KJDS-ANALYTICS-METRIC-PERIOD-001` |
| `status` | `PROPOSED_FOR_IMPLEMENTATION` |
| `owner` | analytics and finance owners |
| `scope` | daily, monthly, quarterly, annual, scenario and rule-replay analysis |

## 1. Fact grain

Every fact declares its grain before a join:

```text
order_line       one order line
inventory_point  one SKU/warehouse/time snapshot
ad_event         one advertising event
settlement_line  one platform settlement line
bank_transaction one bank transaction
return_line      one return line
media_usage      one asset/listing/campaign use
```

Aggregations across grains use explicit bridge tables and never silently multiply rows.

## 2. Period model

Each period carries start/end, timezone, currency, `as_of`, source watermark, partial/closed status and rule versions. Supported views are day, week, month, quarter, year, YTD, previous period, same period last year, rolling 7/30/90 days and custom range.

Partial periods, cross-timezone dates, historical FX and late settlement are visible in the result. A closed period is read-only; late evidence produces an adjustment period and a new result hash.

## 3. Metric families

```text
sales: gross_sales, discount, refund, net_sales, units, asp, orders
traffic: impressions, clicks, ctr, product_views, add_to_cart, conversion
inventory: available, reserved, in_transit, stockout_days, cover_days, turnover
profit: CM1, CM2, CM3, accrual_profit, settled_contribution, cash_cm3
cash: receivable, bank_cash, committed_payables, reserves, cash_floor
quality: return_rate, defect_rate, freshness, completeness, unmatched
```

Every metric has a registered formula, grain, dimensions, currency rule, aggregation rule, status filter, formula version and evidence requirement. `Scenario`, `accrual`, `settled` and `cash` metrics are never substituted for one another.

## 4. Decomposition and comparison

Sales and CM3 changes support price, volume, mix, store, advertising, promotion, seasonality, stockout, FX and cost bridges. Reports show the contribution of each factor and the source rows behind it.

Category and SKU analysis supports price bands, percentile ranks, ABC/XYZ/FSN, lifecycle, stockout-adjusted velocity, ad dependency, return risk and cash quality. `hero_sku` requires stable demand, positive CM3, acceptable returns, sustainable stock and sufficient evidence; volume alone never defines a bestseller.

## 5. Scenario and experiment

Scenarios are immutable projections based on a base snapshot. Changed variables include price, discount, ads, costs, FX, stock, return rate and lead time. Scenarios cannot write Facts or cash. Experiments register control, treatment, changed variables, exposure, duration, sample size, primary metric, stopping rule and attribution method.

## 6. Rule evolution

`RuleVersion` contains `rule_id`, version, expression, source evidence, effective window, supersedes, backtest, impact scope and rollback version. Reports can compare the historical rule with the current rule and identify affected SKUs, orders, ads and cash.

## 7. Query result

Every result includes `scope`, `period`, `as_of`, `metric_versions`, `rule_versions`, `source_watermarks`, `included_count`, `excluded_count`, `status`, `quality`, `lineage` and `result_hash`.

## 8. Acceptance

Daily totals must reconcile to monthly totals, monthly totals to quarterly totals and quarterly totals to annual totals. Replaying an identical snapshot and version set must yield the same result hash. Stockout, late refund, historical FX, partial month and rule-replacement fixtures are mandatory.
