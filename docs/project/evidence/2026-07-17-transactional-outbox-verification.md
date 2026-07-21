# 事务 Outbox PostgreSQL 验证记录

| 项目 | 结果 |
|---|---|
| 日期 | 2026-07-17 |
| 数据库 | 一次性 `kjds_g1_smoke` PostgreSQL 数据库 |
| Alembic head | `20260717_0029` |
| G-1 | PASS |
| 自动测试 | 119 passed |
| 报告 | `.runtime/G1_VERIFICATION.json` |

## 已验证

- 业务行与 Outbox 事件在同一事务提交；强制事件写失败时业务行不存在。
- 两个 worker 同时领取同一待发布事件时，仅一个获得该事件。
- worker 领取后不确认，租约过期可由新 worker 接管，`event_id` 保持不变。
- 失败会保留错误、增加尝试次数并按时间重新开放；重试后可发布。
- 发布语义为 at-least-once，sink 必须按稳定 `event_id` 幂等。
- 0029 已完成全新升级、回滚到 0024、再升级到 head。
- Web build、API/DB/UI smoke 和一次性资源清理均通过。

## 未宣称完成

- 尚未选择或配置生产外部 sink；当前只提供发布器内核和状态端点。
- 其他直接使用 SQLAlchemy Session 的领域服务尚未形成完整 Outbox 覆盖矩阵。
- “sink 已接收、DB 尚未标记”仍会重投，这是 at-least-once 的预期行为，不是 exactly-once；消费者必须去重。

验证入口：`scripts/verify_outbox_postgres.py`，由 `scripts/verify-g1.ps1` 在一次性数据库内执行。
