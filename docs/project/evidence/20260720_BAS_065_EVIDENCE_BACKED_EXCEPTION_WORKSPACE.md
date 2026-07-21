# BAS-065 证据支撑的经营异常工作台实施证据

| 字段 | 值 |
|---|---|
| task | BAS-065 |
| requirement | BR-051 |
| gate | G0–G4 |
| status | DONE_ENGINEERING |
| reviewed_at | 2026-07-20 |

## 结果

`/v1/operations/readiness` 增加只读 `exception_workspace`。每个未满足 requirement 形成稳定 `gate_requirement:{id}` 项，返回 Gate、来源对象、当前/目标数量、责任角色、下一动作和原始 details。页面不重算 readiness，也不把没有发生时间的资料缺口伪造成 SLA 事故。

Web 将 Gate 阻断与现有 `operations-control/queue` 同屏展示：前者用于经营输入导航，后者继续承载真实事故、受限执行命令和观察窗口的风险等级、截止时间与升级记录。两类语义保持分离。

固定边界：

- `advisory_only=true`
- `automatic_resolution=false`
- `platform_write_allowed=false`
- 不自动补证、关闭事故、释放 Kill Switch、批准采购、改价或上架

## Ponytail 取舍

- 复用 `GateReadinessService`、现有 requirement、已有运行队列和 Web 工作台。
- 没有新增数据库表、迁移、队列、端点、调度器或依赖。
- 没有把 Gate 缺资料写入事故表，也没有为其制造假的创建时间、Owner 或 SLA。
- 受控批量 Diff 工作台继续延期，直到真实三候选操作产生可测量的批量瓶颈。

## 验收

| 检查 | 结果 |
|---|---|
| 定向 Python | 7 passed |
| 相关契约回归 | 15 passed |
| Web 契约测试 | 13 passed |
| Ruff 定向检查 | PASS |
| 全量 Python | 286 passed（1 条上游弃用 warning） |
| Ruff 全仓 / Git diff / 已跟踪 JSON | PASS |
| Next.js 生产构建 | PASS（13 routes） |
| G-1 | PASS；`evidence_backed_exception_workspace=true`、`three_candidate_portfolio=true` |

## 未完成的业务事实

工作台显示的是当前系统已知的阻断，不代表阻断已经消除。真实需求报告、三候选原件、三报价、样品/包装/物流实测、真实 Ozon 财务原件、独立双身份审批和经营 Owner 仍需按原 Gate 完成；本任务不改变 G0–G4 状态。
