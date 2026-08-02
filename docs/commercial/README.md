# COM-001 最小商业 Pilot 包

| 字段 | 当前值 |
|---|---|
| status | internal review only |
| commercial_gate | `C0 Commercial Pilot Gate` 未通过 |
| sale_state | `not_for_sale` |
| customer_scope | 1 个主体、1 个 Ozon 店铺、最多 500 个活跃 SKU、3 个用户 |
| execution_scope | 纯只读；全部外部写 `out_of_scope` |

本目录是“俄罗斯 Ozon 利润真相与止损 Pilot”的最小内部评审包，不是公开要约、
可签合同、正式报价、盈利保证或自动运营承诺。

## 包含内容

- [ICP 资格与拒绝清单](COM-001_ICP_Qualification_and_Reject_List.md)
- [90 天 Pilot 范围](COM-001_90_Day_Pilot_Scope.md)
- [C0 商业放行清单](COM-001_C0_Checklist.md)
- [销售访谈与异议边界](COM-001_Sales_Interviews_and_Objections.md)
- [Evidence 案例模板](templates/COM-001_Evidence_Case_Template.md)

## 已有事实基础

- 运行时已经具备 Evidence、`no_data`、精确作用域和外部写关闭等治理基础。
- Ozon 商品和财务只读链已有真实 Evidence，但不代表订单、结算、到账或盈利闭环完成。
- 本地 PostgreSQL 恢复演练只证明本地样本可恢复，不代表生产灾备通过。
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

## 定价假设

- `19,800 RMB / store / 90 days`
- `39,900 RMB / store / year`

两项均不得在 C0 通过前用于报价成交、收款或形成应收。

## 当前 C0 结论

- `PASS`: 0
- `PARTIAL`: 3
- `MISS`: 5
- `UNKNOWN`: 0

因此当前结论固定为 `NO-GO / not_for_sale`。
