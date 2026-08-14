# COM-001 90 天 Pilot 范围

本文是内部评审草案。C0 通过前保持 `not_for_sale`。

## 产品阶梯与合同索引

1. 五工作日利润真相诊断：单客户、单店、50–500 个活跃 SKU、纯只读，价格假设为
   `4,800 RMB`，未税、启动前 100% 支付。执行模板见
   [五工作日诊断 SOW](templates/COM-001_5_Day_Diagnostic_SOW.md)。
2. 90 天设计伙伴 Pilot：同一客户、同一店铺、50–500 个活跃 SKU 和最多 3 个实名用户，
   价格假设为 `19,800 RMB`，未税。执行模板见
   [90 天设计伙伴 SOW](templates/COM-001_90_Day_Design_Partner_SOW.md)。
3. 同一主体、同一店铺在诊断验收后 10 个自然日内签署 Pilot，诊断费 `4,800 RMB`
   全额抵扣 Pilot 总价，Pilot 开工前支付余额 `15,000 RMB`。抵扣只使用一次，不兑换
   现金、不跨主体或店铺、不与其他优惠叠加。

条件意向、定价实验及终验/退出分别见
[条件 LOI](templates/COM-001_Conditional_LOI.md)、
[定价与转化实验](COM-001_Pricing_Experiment.md)和
[验收、数据返还与退出模板](templates/COM-001_Acceptance_and_Exit.md)。

## 固定范围

- 1 个客户主体。
- 1 个 Ozon 店铺。
- 1 套单客户隔离交付环境。
- 50–500 个活跃 SKU。
- 最多 3 个实名业务用户。
- 最长 90 个自然日。
- 全程纯只读；平台发布、改价、采购、付款、广告、消息、退款、VK/Telegram 和所有其他外部写均为 `out_of_scope`。

## Pilot 目标

- 找到 SKU 利润数据缺失、错误或不可解释的位置。
- 显示成本、退货、结算、到账、币种和 Evidence 缺口。
- 形成经客户复核的 `stop / fix / continue / no_data` 结论。
- 测量首次可信价值时间、实施工时和每客户交付成本。

## 交付物

- 准入与作用域确认单。
- 只读数据地图、完整度和隔离区报告。
- SKU scenario/downside/settlement/cash 利润视图；缺数据时保持 `no_data`。
- 带 Owner、SLA、下一动作的阻断与补证清单。
- 每周事实复核记录和最终退出/数据返还包。

## 客户责任

- 提供合法、最小权限、可撤销的只读授权或官方导出。
- 指定运营负责人和财务负责人。
- 复核只有客户能确认的来源、费用、结算和到账事实。
- 按周确认事实修正、阻断和继续/退出决定。

## KJDS 责任

- 保持单客户、单店、纯只读和 Evidence 优先。
- 分开事实、假设、预测与 `UNKNOWN`。
- 不承诺盈利，不接管店铺，不联系平台、银行、客户或交易对手。
- 不把供应商应付、情景利润或模型建议冒充客户计费和实际现金利润。
- 提供可审计导出、数据返还和保留/删除说明。

## 验收

- 只有约定主体、店铺和用户可访问。
- 输出包含经复核事实和明确 `no_data`，不只是建议。
- 客户能够导出约定数据和审计引用。
- 完成退出与数据返还演练。
- 全周期外部写次数严格为 0。

交付验收与首次可信价值分开记录。真实的 `no_data` 可以进入交付验收；首次可信价值还
要求完成受权只读接入和数据质量诊断、至少 1 个 SKU 的 Evidence-backed 利润投影，
并由客户运营和财务角色共同确认至少 1 个止损、补证或增长动作。五工作日计时从 T0
开始；T0 是 C0 全 PASS、客户级主协议/DPA/SOW/退出附表签署、款项到账、精确作用域
冻结且输入准入通过后的首个工作日。

在客户按时提供约定输入的前提下，Pilot 联合结果目标为：首次可信价值不超过 5 个工作
日、标准实施不超过 12 人时、100% 金额带币种、至少 80% 活跃 SKU 的 downside CM3
可解释、至少 90% 结算金额已分配或明确标记 `unallocated`。硬性边界始终是零跨客户/
跨店泄漏、零未授权外部写，以及最终导出、返还、保留和删除演练完成。

## 停止条件

- 数据、授权、法务或合规前提不足。
- 发生跨客户/跨店访问或任何外部写。
- 连续无法形成可复核事实。
- 实施和支持成本超出签署包络。
- C0 任一项保持 `MISS/PARTIAL` 却试图成交。

## 定价假设

- `4,800 RMB / store / five-working-day diagnosis`
- `19,800 RMB / store / 90 days`
- `39,900 RMB / store / year`

三项均为未税、非公开、内部验证价格。C0 通过并完成财务、法务与正式 Order Form 批准
后才进入交易。

## 证据引用

- [M0 Truth/Governance Evidence](../project/evidence/20260727_M0_TRUTH_GOVERNANCE.md)
- [PostgreSQL Restore Drill](../project/evidence/2026-07-17-postgres-restore-drill.md)
- [Settlement and Cash Control](../project/evidence/20260729_BAS_149_NATIVE_EXACT_SCOPE_SETTLEMENT_CASH_CONTROL.md)
- [Channel-account Governance](../project/evidence/20260801_BAS_160_CHANNEL_ACCOUNT_GOVERNANCE.md)
- [Profit Truth and Full Bundle](../project/evidence/20260802_BAS_161_PROFIT_TRUTH_AND_FULL_BUNDLE.md)
