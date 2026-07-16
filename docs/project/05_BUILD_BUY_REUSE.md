# Build / Buy / Reuse 决策

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-ARCH-REUSE-001 |
| owner | 工程负责人（待确认） |
| approver | 项目负责人 |
| status | Active |
| version | 1.0 |
| last_reviewed | 2026-07-16 |
| next_review | 2026-08-16 |
| gate | G-1–G8 |

## 当前组合

| 层 | 当前 Owner | 决策 | 边界 |
|---|---|---|---|
| 业务控制平面 | KJDS 模块化单体 | Build | 事实、Passport、账本、审批、证据、业务状态由 KJDS 持有 |
| API/Schema | FastAPI + Pydantic | Reuse | 服务层执行业务规则，Agent/连接器不得直连 Repository |
| 事实库 | PostgreSQL/Supabase | Reuse | Decimal、币种、双时间、迁移和审计事件 |
| 浏览器探索 | Playwright | Reuse | 探索/采集可用；生产写动作仍需确定性代码与审批 |
| Agent 操作工具 | OpenClaw + Hermes | Reuse | 仅操作员与研究调度，不成为业务唯一真源 |
| Agent 运行时 | 现有壳层；后续评估官方 Agents SDK/PydanticAI | Defer | 先完成真实闭环和 Agent 需求合同 |
| Durable Workflow | 当前服务+状态机 | Build/Defer | Temporal 仅在长事务、补偿、重放压力实证后 ADR |
| 可观测/评测 | 业务审计账本优先；Langfuse/Promptfoo 候选 | Defer | 不能替代业务证据和黄金 Oracle |
| AI 网关 | 官方 API/现有本地 Provider | Reuse | 不采用共享订阅池 |

## sub2api 结论

当前不引入、不部署、不占用 G-1–G4 开发窗口。它提供多账号池、Key 分发、计费、调度和后台，但不是项目监控、Codex 多窗口调度或跨境电商工作流。它还会引入第二套用户/权限/计费、PostgreSQL 和 Redis 运维面，并存在许可证声明与上游服务条款张力。

保留研究项：`R&D-AI-GW-001`，优先级 P3。只有在至少一个 SKU 完成订单—结算—人民币 CM3 闭环，且官方云模型成本、并发或故障切换成为实际瓶颈后，才做隔离 PoC。PoC 只能使用官方 API Key，不得导入订阅 Cookie/OAuth Token 或生产业务数据。

## 新技术准入问题

1. 它解决哪个当前 Gate 的实证瓶颈？
2. 现有模块为何不能用更小修改解决？
3. 谁拥有该层，是否形成双 Owner？
4. 数据、密钥、许可、上游条款和退出成本是什么？
5. 最小隔离 PoC 的成功/失败标准是什么？
6. 如何回滚和完全移除？

