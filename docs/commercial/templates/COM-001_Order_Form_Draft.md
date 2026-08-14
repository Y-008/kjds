# COM-001 Order Form 草案

> **`internal_review_only / non_binding / not_for_sale`**
> 本草案不构成报价、订单、应收、发票、付款义务、服务开工授权或客户验收。所有金额均为
> `pricing_hypothesis`。只有 C0 全部检查达到 `PASS`、财务/法务批准、客户级主协议/DPA/
> SLA/SOW/退出附表生效，并由双方授权代表另行签署标记为 `binding=true` 的最终 Order
> Form 后，才形成交易。

| 字段 | 草案值 |
|---|---|
| template_id | `COM-001-ORDER-FORM-DRAFT-v1` |
| status | `internal_review_only` |
| binding_effect | `non_binding` |
| sale_state | `not_for_sale` |
| quote_state | `not_created` |
| order_state | `not_created` |
| receivable_state | `not_created` |
| invoice_state | `not_created` |
| payment_obligation | `none` |
| activation_gate | `C0 Commercial Pilot Gate = PASS` |

## 1. 草案主体与作用域

- 服务方合同主体：`[KJDS_CONTRACT_ENTITY_SLOT]`
- 客户合同主体：`[CUSTOMER_LEGAL_ENTITY_SLOT]`
- customer_ref：`[CUSTOMER_REF_SLOT]`
- tenant/entity/store：`[TENANT_REF] / [ENTITY_REF] / [STORE_REF]`
- 客户当前 Ozon 店铺数：`[1–3]`
- 本单拟覆盖：1 个客户主体、1 家 Ozon 店、50–500 个活跃 SKU、最多 3 个实名用户
- 运营验收角色：`[OPERATIONS_OWNER_ROLE]`
- 财务验收角色：`[FINANCE_OWNER_ROLE]`
- 数据处理期间：`[DATA_WINDOW_SLOT]`
- 执行模式：纯只读；第三方业务写 `out_of_scope`

真实客户名称、联系人、联系方式、地址、凭据、银行资料和原始经营数据不得填写在仓库
版本；这里只保存匿名稳定引用和最终文件的 Evidence/SHA-256。

## 2. 拟选服务

在最终 `binding=true` Order Form 中仅选择一项或按明确顺序选择两项：

| 选择 | 服务 | 范围 | 内部价格假设 | 执行合同 |
|---|---|---|---:|---|
| `[ ]` | 五工作日利润真相诊断 | 单店、50–500 SKU、纯只读 | `4,800 RMB`，未税 | [诊断 SOW](COM-001_5_Day_Diagnostic_SOW.md) |
| `[ ]` | 90 天设计伙伴 Pilot | 单店、50–500 SKU、最多 3 用户、单客户隔离 | `19,800 RMB`，未税 | [Pilot SOW](COM-001_90_Day_Design_Partner_SOW.md) |

诊断验收后 10 个自然日内，同一客户主体、同一店铺如签署最终 Pilot Order Form，已付
诊断费可按获批合同全额抵扣 Pilot 总价，拟付余额为 `15,000 RMB`。抵扣只使用一次，
不兑换现金、不跨主体或店铺、不与其他优惠叠加。详细规则见
[定价与转化实验](../COM-001_Pricing_Experiment.md)。

## 3. 本草案不产生交易事件

- 本草案版本不得进入 `quoted/ordered/invoiced/paid/active` 状态。
- 不生成发票、收款链接、银行付款指令、应收、退款或服务信用。
- 不占用客户部署、用户名额、SKU 额度、支持 SLA 或交付日期。
- 不授权 API、导出接入、数据处理、部署、第三方联系或业务外写。
- 不把签署“已阅”或内部审批解释为购买接受。

## 4. 最终 Order Form 生效条件

以下条件全部有当前 Evidence 后，才可另行生成 `binding=true` 最终版本：

1. C0 九项检查全部 `PASS`，且 Release/回滚、隔离、TLS/Secrets、备份恢复、商业生命周期、
   单位经济、Contract/DPA/SLA 和退出删除 Evidence 当前有效。
2. [客户资格与输入模板](COM-001_Customer_Qualification_Input.md)结论为 `qualified`。
3. 客户级主协议、DPA、SLA、对应 SOW 和
   [验收退出附表](COM-001_Acceptance_and_Exit.md)完成签署并冻结哈希。
4. 最终合同主体、税率、开票项目、付款账户和退款规则经财务/法务批准。
5. 客户主体、单店、50–500 SKU、最多 3 用户和只读数据范围已冻结。
6. 最终 Order Form 具有唯一 `order_form_id`、版本、有效期、幂等键及双方授权代表签署。

最终版本的 T0 仍以对应 SOW 为准，不以本草案创建、评审或“已阅”时间起算。

## 5. 拟议商业字段

| 字段 | 草案占位 |
|---|---|
| order_form_id | `[NOT_ASSIGNED]` |
| offer_version | `[PRICING_HYPOTHESIS_VERSION]` |
| currency | `RMB` |
| tax_basis | `未税；待财务/法务批准` |
| diagnostic_amount | `[4,800_RMB_HYPOTHESIS]` |
| pilot_amount | `[19,800_RMB_HYPOTHESIS]` |
| eligible_credit | `[0_OR_4,800_RMB_AFTER_FINAL_APPROVAL]` |
| cash_due | `[NO_PAYMENT_OBLIGATION_IN_DRAFT]` |
| payment_due | `[NOT_APPLICABLE_IN_DRAFT]` |
| valid_until | `[NOT_APPLICABLE_IN_DRAFT]` |
| service_start/T0 | `[DEFINED_ONLY_BY_SIGNED_SOW]` |

## 6. 退款、提前结束与退出

本草案不触发服务费退款。最终交易的退款、客户暂停/违约、服务方未交付/重大缺陷、提前
结束、服务信用、导出、返还、保留和删除，以已签对应 SOW、主协议和
[验收退出附表](COM-001_Acceptance_and_Exit.md)为准。SOW 中 `out_of_scope` 的 Ozon 买家
订单退款是第三方业务写边界，与 B2B 服务费退款分别处理。

## 7. 内部审阅记录

下表仅记录内部审阅，不构成客户订单或付款承诺：

| 角色 | 结论 | Evidence ref | 日期 |
|---|---|---|---|
| Commercial Owner | `[review_pending]` | `[REF]` | `[DATE]` |
| Finance Reviewer | `[review_pending]` | `[REF]` | `[DATE]` |
| Legal Reviewer | `[review_pending]` | `[REF]` | `[DATE]` |
| Independent Verifier | `[review_pending]` | `[REF]` | `[DATE]` |

> **结束状态：`internal_review_only / non_binding / not_for_sale`。本草案不产生报价、订单、
> 应收、发票、付款义务或服务开工。**
