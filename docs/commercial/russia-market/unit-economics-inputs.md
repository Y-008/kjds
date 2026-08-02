# Unit Economics Inputs

**目的**: 只定义变量和公式，不编造任何费率。  
**用法**: 这些变量必须由 Ozon 官方费率、货代报价、认证报价、税务意见和银行报价填充后，才能算单品经济性。

## 必采变量

### 商品与销售

- `asp_rub`: 售价
- `units_sold`
- `discount_rate`
- `refund_rate`
- `cancellation_rate`
- `return_rate`

### 平台与履约

- `commission_rate_by_category`
- `fulfillment_fee_per_order`
- `last_mile_fee_per_order`
- `storage_fee_per_sku_day`
- `return_handling_fee_per_return`
- `unredeemed_order_fee_per_order`
- `cancellation_fee_per_order`
- `other_platform_fee_per_order`

### 跨境与关税税务

- `fx_rate_rub_cny`
- `fx_spread_rate`
- `bank_transfer_fee_rate`
- `customs_duty_rate`
- `import_vat_rate`
- `brokerage_fee_per_shipment`
- `clearance_fee_per_shipment`
- `incoterm`

### 合规与包装

- `certification_cost_per_sku`
- `labeling_cost_per_sku`
- `translation_cost_per_sku`
- `chestny_znak_cost_per_unit`
- `packaging_cost_per_unit`
- `rework_cost_per_unit`

### 客服与风险

- `support_cost_per_order`
- `claims_cost_per_order`
- `penalty_rate_or_fee`
- `loss_shrink_rate`
- `writeoff_rate`

## 核心公式

```text
gross_revenue_rub
  = asp_rub * units_sold

net_revenue_rub
  = gross_revenue_rub
  - discounts
  - refunds

platform_cost_rub
  = commission
  + fulfillment
  + delivery
  + storage
  + returns
  + cancellations
  + penalties
  + other_platform_fee

border_cost_rub
  = customs_duty
  + import_vat
  + brokerage_fee
  + clearance_fee
  + bank_transfer_fee
  + fx_spread_cost

compliance_cost_rub
  = certification_cost_amortized
  + labeling_cost
  + translation_cost
  + chestny_znak_cost

contribution_margin_rub
  = net_revenue_rub
  - platform_cost_rub
  - border_cost_rub
  - compliance_cost_rub
  - support_cost
  - claims_cost
  - loss_shrink_cost

contribution_margin_pct
  = contribution_margin_rub / net_revenue_rub
```

## 计算规则

1. 所有费率都必须按 SKU、类目、仓配模式、币种和主体分别建表。
2. 认证和标签费用必须做摊销，不能一次性平到首单里掩盖真实毛利。
3. 退货成本必须与履约模式分开，不能只看销售佣金。
4. 进口 VAT 与关税必须和申报主体、Incoterms 一起算，不能单独拿税率做结论。
5. 如果 `fx_spread_rate`、`bank_transfer_fee_rate` 或 `penalty_rate_or_fee` 无法取得书面报价，则该 SKU 不能进入可售结论。

