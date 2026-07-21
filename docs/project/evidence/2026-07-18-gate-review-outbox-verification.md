# 2026-07-18 Gate Review 事务 Outbox 验证

| 项目 | 结果 |
|---|---|
| 任务 | `BAS-016` |
| 状态 | PASS |
| Alembic head | `20260717_0035`（无新增迁移） |
| 自动测试 | 138 passed |
| G-1 | PASS |
| PostgreSQL Outbox | `transactional_outbox=true` |
| PostgreSQL Gate 链 | `governance_gate_review=true` |

## 验收结果

1. 创建 Gate Review 时，同一事务写入 `gate_review.created`。
2. 提交 Gate Review 时，同一事务写入 `gate_review.submitted`，并引用首个有效证据。
3. 决定 Gate Review 时，同一事务写入 `gate_review.decided`，记录独立 approver。
4. 事件 payload 只包含 gate、状态、决定和计数，不复制目标、理由、预算、回滚正文或凭证。
5. 模拟决定事件写入失败后，Gate Review 保持 `submitted`，`decision` 仍为空，失败事件和业务变化一起回滚。
6. 幂等创建返回同一 Gate Review，不重复生成创建事件。

## 验证命令与证据

- `uv run ruff check .`：PASS。
- `uv run pytest --basetemp .runtime/pytest-bas-016`：138 passed，保留 1 条既有 Starlette/httpx 弃用警告。
- `scripts/verify-g1.ps1`：PASS；迁移升级/回滚/再升级、真实 PostgreSQL Gate API、通用 Outbox 竞态/恢复、API/Web、备份恢复与资源清理全部通过。
- 机器报告：`.runtime/G1_VERIFICATION.json`，完成时间 `2026-07-18T02:51:01.3489051Z`。

## 保留边界

本批不新增消息队列、外部 sink、常驻发布进程或迁移，也不宣称全部直接 Session 领域已完成 Outbox。后续只在某个领域确有跨边界消费者、通知或投影时迁移，外部 sink 仍必须按 `event_id` 幂等。
