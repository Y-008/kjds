# COM-001 最小商业 Pilot 包

| 字段 | 当前值 |
|---|---|
| status | internal review only |
| commercial_gate | `C0 Commercial Pilot Gate` 未通过 |
| sale_state | `not_for_sale` |
| customer_scope | 1 个主体、1 个 Ozon 店铺、50–500 个活跃 SKU、最多 3 个用户 |
| execution_scope | 纯只读；全部外部写 `out_of_scope` |

本目录是“俄罗斯 Ozon 利润真相与止损 Pilot”的最小内部评审包，不是公开要约、
可签合同、正式报价、盈利保证或自动运营承诺。

## 包含内容

- [ICP 资格与拒绝清单](COM-001_ICP_Qualification_and_Reject_List.md)
- [90 天 Pilot 范围](COM-001_90_Day_Pilot_Scope.md)
- [C0 商业放行清单](COM-001_C0_Checklist.md)
- [销售访谈与异议边界](COM-001_Sales_Interviews_and_Objections.md)
- [Evidence 案例模板](templates/COM-001_Evidence_Case_Template.md)
- [五工作日利润真相诊断 SOW](templates/COM-001_5_Day_Diagnostic_SOW.md)
- [90 天设计伙伴 Pilot SOW](templates/COM-001_90_Day_Design_Partner_SOW.md)
- [条件设计伙伴意向书](templates/COM-001_Conditional_LOI.md)
- [定价与转化实验](COM-001_Pricing_Experiment.md)
- [验收、数据返还与退出模板](templates/COM-001_Acceptance_and_Exit.md)

## 已有事实基础

- 运行时已经具备 Evidence、`no_data`、精确作用域和外部写关闭等治理基础。
- Ozon 商品和财务只读链已有真实 Evidence，但不代表订单、结算、到账或盈利闭环完成。
- 商业 Pilot 本地预检、计费/权益内核和持久商业事件账本已经形成工程 Evidence，
  但尚未证明托管生产、真实收退款、税务、合同、SLA 或客户退出闭环。
- 所有价格仍是 `pricing_hypothesis/internal_preview/not_for_sale`。

关键来源：

- [双轮商业化与俄罗斯 GTM 合同](../project/20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md)
- [Ultimate Product Blueprint](../project/ULTIMATE_PRODUCT_BLUEPRINT.md)
- [M0 Truth/Governance Evidence](../project/evidence/20260727_M0_TRUTH_GOVERNANCE.md)
- [Ozon Seller Read-only Observation](../project/evidence/2026-07-18-ozon-seller-read-only-observation.md)
- [Ozon Pilot Offline Preflight](../project/evidence/20260719_BAS_033_OZON_PILOT_OFFLINE_PREFLIGHT.md)
- [PostgreSQL Restore Drill](../project/evidence/2026-07-17-postgres-restore-drill.md)
- [Settlement and Cash Control](../project/evidence/20260729_BAS_149_NATIVE_EXACT_SCOPE_SETTLEMENT_CASH_CONTROL.md)
- [Channel-account Governance](../project/evidence/20260801_BAS_160_CHANNEL_ACCOUNT_GOVERNANCE.md)
- [Profit Truth and Full Bundle](../project/evidence/20260802_BAS_161_PROFIT_TRUTH_AND_FULL_BUNDLE.md)
- [C0-001 Commercial Pilot Deployment Preflight](../project/evidence/20260802_C0_001_COMMERCIAL_PILOT_DEPLOYMENT_PREFLIGHT.md)
- [C0-002 Billing / Usage / Entitlement Kernel](../project/evidence/20260802_C0_002_BILLING_USAGE_ENTITLEMENT_KERNEL.md)
- [C0-003 Commercial Lifecycle Ledger](../project/evidence/20260802_C0_003_COMMERCIAL_LIFECYCLE_LEDGER.md)

## 定价假设

- `4,800 RMB / store / five-working-day diagnosis`
- `19,800 RMB / store / 90 days`
- `39,900 RMB / store / year`

诊断价格为未税、启动前 100% 支付。同一客户主体、同一店铺在诊断验收后 10 个自然日
内签署 90 天设计伙伴 Pilot 时，已付 `4,800 RMB`全额抵扣 `19,800 RMB`，Pilot 开工
前支付余额 `15,000 RMB`。抵扣只使用一次，不兑换现金、不跨主体或店铺、不与其他优惠
叠加。

以上价格均保持 `pricing_hypothesis/internal_preview/not_for_sale`，C0 通过并完成财务、
法务及正式 Order Form 批准后才进入交易。

## 当前 C0 结论

- `PASS`: 0
- `PARTIAL`: 5
- `MISS`: 4
- `UNKNOWN`: 0

因此当前结论固定为 `NO-GO / not_for_sale`。
