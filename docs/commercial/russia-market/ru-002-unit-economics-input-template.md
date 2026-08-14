# RU-002 Unit Economics Input Template

**Purpose**: fillable companion to `docs/commercial/russia-market/unit-economics-inputs.md` for RU logistics evidence.

**Rules**

- If a value is not directly supported by a source file, leave it as `UNKNOWN`.
- Do not infer tax inclusion, VAT, or duty treatment.
- Do not collapse different warehouse modes, shipment types, or providers into one number.
- Use the cited source location as the primary key for any filled row.

## Channel / fee candidates

| Channel family | Location | Fee expression | Mode | Currency | Notes |
|---|---|---|---|---|---|
| `CEL rFBS Extra Small` | `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx -> CEL运费价格测算表!A4:K6` | `50.5 元/kg + 3.37 元/票` / `39.3 + 3.37` / `28.1 + 3.37` | `到取货点` | `CNY` | Weight cap `0.5kg`; `UNKNOWN` tax |
| `CEL rFBS Budget` | `... -> CEL运费价格测算表!A7:K9` | `37.1 + 25.83` / `28.1 + 25.83` / `19.1 + 25.83` | `到取货点` | `CNY` | Weight cap `0.5-25kg` |
| `CEL rFBS Small` | `... -> CEL运费价格测算表!A10:K12` | `50.5 + 17.97` / `39.3 + 17.97` / `28.1 + 17.97` | `到取货点` | `CNY` | Weight cap `0.001-2kg` |
| `CEL rFBS Premium Small` | `... -> CEL运费价格测算表!A13:K15` | `50.5 + 24.71` / `39.3 + 24.71` / `28.1 + 24.71` | `到取货点` | `CNY` | Weight cap `0.001-5kg` |
| `CEL rFBS Big` | `... -> CEL运费价格测算表!A16:K19` | `28.1 + 40.44` / `19.1 + 40.44` / `31.4 + 69.64` / `25.8 + 69.64` | `到取货点` | `CNY` | Big and premium big use mixed weight / volume weight |
| `WB Economy` | `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx -> WB 运费价格测算表!A4:F5` | `58 元/kg + 2 元/票`; `43 元/kg + 8 元/票` | `到取货点` | `CNY` | Warehouse code `326005` |
| `Yandex Russia` | `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx -> yandex 运费价格测算表!A4:G7` | `550 RUB/kg + 78 RUB/票`; `715 + 161`; `287 + 78`; `465 + 161` | `到取货点` | `RUB` | `UNKNOWN` tax |
| `Yandex FBP/rFBS legacy` | `wuliu/【2025.11.26】Yandex产品测费表(1).xlsx -> Sheet1!B3:H10` | `703/158`, `538/76`, `457/158`, `280/76` | `FBP` / `rFBS` | `RUB` | Early comparison table |
| `GUOO Ozon official` | `wuliu/GUOO产品资费测算表【2026.7.20更新】.xlsx -> GUOO realFBS资费试算表 / GUOO FBP资费试算表` | `28.1/39.3/50.55/19.1/25.8/31.4 元/kg` with corresponding ticket fees `3.37/17.97/24.71/40.44/69.64` | `PUDO` / `Courier` / `空运` / `陆运` | `CNY` | Choose per SKU / cargo profile |
| `Ural Ozon official` | `wuliu/Ural国际物流报价单20260721.xlsx -> Ozon官方伙伴Ural线上物流!A3:H24` | `18 RMB/票 + 10.5 RMB/100g`; `18 + 5.5`; plus mainland rate families | `PUDO` / `Courier` / `空运` / `陆运` | `RMB` / `CNY` | Mixed currency in source |
| `Xingyuan / OYX / Albart` | `wuliu/兴远rFBS全渠道计算器2026-07-17.xlsx`, `wuliu/欧亚兴rFBS全渠道计算器2026-07-17.xlsx`, `wuliu/阿尔巴特rFBS全渠道计算器2026-07-17.xlsx` | Same family: `3.37/0.0281`, `25.83/0.0191`, `17.97/0.0281`, `40.44/0.0191`, `24.71/0.0281`, `69.64/0.0258` | `PUDO` / `Courier` | `CNY` | Retain the provider name in the final chosen channel |

## Fillable variables

| Variable | Value | Status | Source / note |
|---|---|---|---|
| `asp_rub` | `UNKNOWN` | `unknown` | Needs SKU price evidence |
| `units_sold` | `UNKNOWN` | `unknown` | Scenario-specific |
| `product_cost_cny_per_unit` | `UNKNOWN` | `unknown` | Needs supplier invoice / payment |
| `discount_rate` | `UNKNOWN` | `unknown` | Needs campaign / pricing evidence |
| `refund_rate` | `UNKNOWN` | `unknown` | Needs actual refund history |
| `cancellation_rate` | `UNKNOWN` | `unknown` | Needs actual order history |
| `return_rate` | `UNKNOWN` | `unknown` | Needs actual return history |
| `commission_rate_by_category` | `UNKNOWN` | `unknown` | Needs platform settlement or commission schedule tied to category |
| `fulfillment_fee_per_order` | `UNKNOWN` | `unknown` | Needs platform settlement / warehouse bill |
| `last_mile_fee_per_order` | `UNKNOWN` | `unknown` | Do not reuse line-haul as last mile |
| `storage_fee_per_sku_day` | `UNKNOWN` | `partial` | Candidate storage fees exist, but route / warehouse choice must be fixed first |
| `return_handling_fee_per_return` | `UNKNOWN` | `partial` | Candidate return / interception / destroy fees exist |
| `unredeemed_order_fee_per_order` | `UNKNOWN` | `unknown` | No platform receipt in this batch |
| `cancellation_fee_per_order` | `UNKNOWN` | `unknown` | No platform receipt in this batch |
| `other_platform_fee_per_order` | `UNKNOWN` | `unknown` | No platform receipt in this batch |
| `fx_rate_rub_cny` | `UNKNOWN` | `unknown` | Needs booked conversion rate and fee record |
| `fx_spread_rate` | `UNKNOWN` | `unknown` | Needs booked conversion rate and fee record |
| `bank_transfer_fee_rate` | `UNKNOWN` | `unknown` | Needs bank / PSP quote |
| `main_leg_freight_cny_per_shipment` | `UNKNOWN` | `partial` | Pick one channel family from the table above and compute from actual shipment profile |
| `cargo_insurance_cny_per_shipment` | `UNKNOWN` | `partial` | `Ural` shows `0.5% / 1%` candidate insurance, but actual policy is still provider-specific |
| `units_per_shipment` | `UNKNOWN` | `unknown` | Must come from packing plan / actual shipment |
| `customs_duty_rate` | `UNKNOWN` | `unknown` | No customs declaration / duty receipt in this batch |
| `import_vat_rate` | `UNKNOWN` | `unknown` | No tax opinion in this batch |
| `recoverable_import_vat_rate` | `UNKNOWN` | `unknown` | No tax opinion in this batch |
| `brokerage_fee_per_shipment` | `UNKNOWN` | `partial` | `GUOO` shows `500元/单` export declaration candidate only |
| `clearance_fee_per_shipment` | `UNKNOWN` | `unknown` | No import clearance bill in this batch |
| `incoterm` | `UNKNOWN` | `unknown` | Must be tied to the actual contract |
| `certification_cost_per_sku` | `UNKNOWN` | `unknown` | No certification quote in this batch |
| `labeling_cost_per_sku` | `UNKNOWN` | `partial` | Candidate rows exist: `1-3元/件` depending provider / warehouse |
| `translation_cost_per_sku` | `UNKNOWN` | `unknown` | No translation quote in this batch |
| `chestny_znak_cost_per_unit` | `UNKNOWN` | `unknown` | No Chestny Znak evidence in this batch |
| `packaging_cost_per_unit` | `UNKNOWN` | `partial` | Candidate rows exist for bags / cartons / bubble film / bubble柱 / protective packaging |
| `rework_cost_per_unit` | `UNKNOWN` | `partial` | Candidate rows exist for repack, photo, weighing, interception, re-label |
| `support_cost_per_order` | `UNKNOWN` | `unknown` | No support bill in this batch |
| `claims_cost_per_order` | `UNKNOWN` | `partial` | `Ural` shows claim / insurance limits; not enough for a universal amount |
| `penalty_rate_or_fee` | `UNKNOWN` | `partial` | Some provider docs show `1.5x` return freight or `<=100`赔偿上限 |
| `loss_shrink_rate` | `UNKNOWN` | `partial` | Destroy / forced return / compensation cap exist, but not a modeled rate yet |
| `writeoff_rate` | `UNKNOWN` | `unknown` | Needs actual inventory adjustment evidence |

## How to use

1. Pick one channel family from the candidate table.
2. Bind it to one shipment profile and one provider.
3. Fill only values that have an explicit source row.
4. Keep every absent field as `UNKNOWN`.
5. Do not collapse mixed-currency docs into one rate without the original bill.
