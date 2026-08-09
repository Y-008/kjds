# ADR-0021：供应商线索、确认报价与三报价权威边界

- 状态：Accepted
- 日期：2026-07-26
- 决策 Owner：供应链负责人、财务负责人、合规复核人
- 影响 Gate：SKU-003、G1、G3

## 背景

公开 1688 商品页展示价、聊天截图、报价单、形式发票和付款后的真实成本具有不同权威性。原
`SupplierComparisonIntakeService` 把操作者上传的任意文件直接声明为 A 级 Evidence，并立即创建
`SupplierOffer` 与 CM3 场景。这会让公开展示价、引流价、错误规格或上传者自述直接进入采购决策。

2026-07-26 对当前 Ozon SKU `2216781923` 的只读研究进一步验证了该风险：1688 同类公开展示价从
100 CNY 到 856 CNY，无法单凭页面判断具体 500 kg / 7.6 m / 三控规格、包装、交付、MOQ 和报价有效期。

## 决策

采用 Evidence Ledger 上的双层权威，不增加第二套报价事实表：

1. 所有商品页、聊天、报价单和形式发票首先以 B 级 `supplier_quote_source` 原件进入线索层。
2. 原件必须声明 `document_kind`：
   - `public_display_price` 只用于研究，永远不能晋升正式报价；
   - `supplier_confirmed_quote` 与 `proforma_invoice` 可进入独立复核。
3. 独立复核人必须与上传者不同，并逐项确认原件真实性、供应商身份、冻结规格、金额/币种/MOQ、
   有效期与交付条件。接受结果形成 A 级不可变复核凭证和 Evidence lineage，但不覆盖原件。
4. `SupplierOffer` 只能从已接受的原件生成；调用方不得重新提交或覆盖已复核条款。
5. 三报价最终化必须同时满足同一候选 Product、三个不同供应商、三份当前有效且已接受的原件。
   之后才生成三个 `SupplierOffer` 和三个 CM3 场景。
6. 报价在付款前仍是 `estimate`。只有供应商发票与付款记录通过 BR-057 实际成本权威复核后，
   `product_cost` 才能标为 `actual`。
7. RFQ 草稿、AI 比价和公开研究均不得自动联系供应商、下单、付款、改价、上架或写入 Ozon。
8. 确认报价包含数量阶梯时，全部阶梯继续作为同一 `offer_data.attributes.price_tiers` 的不可变
   条款保存，不新增第二张报价事实表。每档只含唯一正整数 `minimum_quantity` 与正 Decimal
   `unit_price`，规范化后严格升序；同时冻结正整数 `selected_quantity`。正式
   `SupplierOffer.unit_price` 必须等于 `selected_quantity` 可适用的最高起订档单价，且不得低于
   报价 MOQ。任一缺项、重复档、非有限金额、无适用档或单价不一致均在复核前失败关闭。
9. 三报价中只要有一份使用数量阶梯，三份都必须声明相同 `selected_quantity`；否则不得生成
   `SupplierOffer` 或 CM3。完整阶梯保留在现有 `source_offers.attributes_json`，利润场景明确使用
   已冻结比较数量对应的单价，不能把公开最低档、样品价或其他数量档偷换为比较成本。

## 接口边界

- `POST /v1/sourcing/quote-evidence`：上传单份线索/报价原件。
- `GET /v1/sourcing/quote-evidence`：读取当前报价工作队列。
- `POST /v1/sourcing/quote-evidence/{id}/authority-review`：独立复核。
- `GET /v1/sourcing/quote-evidence/{id}/authority-review`：读取复核状态。
- `POST /v1/sourcing/comparison-finalize`：使用三份已接受原件生成正式比较。
- 旧 `comparison-intake` 不再允许上传即生成正式报价。

## 被否决方案

- 继续把上传文件自动标 A：无法区分展示价、错误规格和供应商确认条款。
- 把 1688 页面采集结果直接写 `SupplierOffer`：公开页面不是询价回复，且常有 SKU 低价与促销干扰。
- 新增可变 `supplier_quotes` 工作流表：与不可变 Evidence、复核凭证和 lineage 重复，增加双真源风险。
- 为每个数量档复制一个 `SupplierOffer`：会把同一供应商伪装成多份独立报价，并破坏三供应商门。
- 只保存当前选中的一档：无法复核 100/300/500 原始条款，后续切换采购量时会丢失权威依据。
- AI 自动联系供应商并提交采购：属于外部高风险动作，缺少单次审批、回读与付款控制。

## 失效条件与复核

当正式供应商 API 能提供签名报价、稳定报价版本、规格与有效期合同，并通过安全、条款、撤销、
审计和对账验收时，可重新评估是否引入连接器。最迟于 2026-10-26 复核本 ADR。
