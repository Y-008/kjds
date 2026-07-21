# BAS-046 候选测量合同与报价筛选策略验收

| 字段 | 值 |
|---|---|
| requirement | BR-033 |
| task | BAS-046 |
| gate | G0 工程准备；不放行 G0 |
| status | DONE_ENGINEERING |
| verified_at | 2026-07-19T01:54:23Z |
| API | 0.34.0 / v1 |

## 问题

旧候选入口要求录入需求、竞争缺口、供货、合规和退货五类指标，但需求、缺口和退货数值并不参与最终判断；即使需求为 0、缺口为 0、退货风险为 100，也可能进入三报价。指标还没有固定方法、单位、观察窗口或最小样本，无法复算。

## 已实现合同

- 服务端固定 `ozon-ru-candidate-measurement-v1`，客户端不能自定义方法和单位。
- 需求信号：`category_demand_percentile` / percentile / 28–90 天 / 样本至少 30。
- 竞争缺口：`demand_supply_gap_percentile` / percentile / 28–90 天 / 样本至少 30。
- 退货风险：`expected_30d_return_rate_pct` / percent / 28–90 天 / 样本至少 30。
- 供货与合规：版本化布尔结论 / 1–90 天 / 至少一个可核验对象。
- 方法、单位、窗口、样本量和策略 ID 随观测进入维度与幂等摘要；旧的无口径观测不能参与候选放行。
- 同一指标的有效观测按可信度加权，`ozon-ru-quote-screen-v1` 要求需求 ≥50、缺口 ≥50、退货风险 ≤30%，同时保留双来源、供货确认、合规红线和 Evidence 完整性门。
- 响应返回策略 ID、策略状态、聚合值和逐项阈值失败。Web 直接显示口径、样本输入和失败原因。

## 风险与权限边界

50/50/30 是 `engineering_default_requires_owner_review`，用于分配低风险询价精力；经营负责人须在 G0 前用三个真实候选回放并确认或修改。它不创建采购、不批准样品、不批准 Listing，也不调用 Ozon 写接口。低于阈值只代表当前策略不建议询价，不证明市场永久无机会。

## 验证

| 检查 | 结果 |
|---|---|
| Python 全量测试 | 218 passed；含低需求/低缺口/高退货淘汰、样本不足原子失败 |
| Web 契约测试 | 7 passed；含窗口、样本量、阈值和 Owner 复核提示 |
| Web production build | PASS |
| Ruff | PASS |
| OpenAPI snapshot | 0.34.0 已同步，PASS |
| Secret scan | 294 个非忽略工作区文件，PASS |
| 完整 G-1 | PASS；候选原件→测量筛选→人工交接→三报价真实 API 链通过 |
| 隔离恢复 | `0359619075aac45186a66cec2760ef84d9eea541e1009d31620a99719346c329` |

运行事实以 `.runtime/G1_VERIFICATION.json` 为准。当前真实阻塞仍是三个候选的一手需求/竞争/退货原件、三家报价、样品/包装/物流实测、合规判断及经营负责人阈值复核；本次工程通过不改变这些状态。
