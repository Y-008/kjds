# BAS-088：唯一经营工作台 Agent 简报

## 结论

KJDS 已新增版本化只读合同 `kjds-operating-workbench-briefing-v1`，通过
`GET /v1/operating-workbench/briefing` 聚合既有 Gate readiness、候选组合、运行异常队列和
Recommendation。首页 Agent 团队不再使用写死的演示状态，而是只显示该服务端简报投影。

该能力没有新增数据库表、迁移、依赖、模型调用、外部连接器或第二套选品/采购/Listing 流程。
所有工作项固定 `automatic_execution=false`、`platform_write_allowed=false`；第三方信号不得自动晋升事实。

## 变更控制

| 项目 | 内容 |
|---|---|
| 变更目的 | 把 KJDS 收敛为唯一经营工作台，并让 Agent 状态来自真实控制面而非静态演示 |
| 影响 Gate | G0–G4 的解释与人工导航；不改变任一 Gate 放行规则 |
| 解决的真实问题 | Web 需要分别拼装 readiness、运行队列和建议，Agent 卡片与真实状态脱节 |
| 输入证据 | 既有 `GateReadinessService`、`OperationsQueueService`、`AutomationService` 输出 |
| 新增数据/权限 | 无新数据 Owner；新增已认证只读 GET；允许 operator/reviewer/compliance/approver/risk/monitor/admin |
| 风险与最大损失 | 错误排序可能浪费人工注意力；无法产生采购、Listing、定价或平台写入损失 |
| 回滚方式 | 回退新模块、运行时组合、GET 路由和 Web 展示；原 readiness、队列、建议接口保持不变 |
| Owner / Approver | 工程负责人 / 经营负责人 |
| 复杂度税 | 一个深模块、一个只读接口、一个前端合同；无迁移、Provider 或状态机 |
| 冻结条件 | 未经 Evidence、Authority、Approval 和 Execution Gate，不增加外部副作用或第三方事实晋升 |

## 接口与不变量

- 外部 Interface 只有 `OperatingWorkbenchService.snapshot(limit=20)`。
- Gate 阻断保留稳定 `requirement_id`、Gate、当前/目标和下一动作，不填 `due_at`、`overdue` 或
  `escalation_level`。
- 运行异常沿用真实队列的 priority、due time、overdue 和 escalation。
- Recommendation 保留 Evidence ID，仍须人工建立正式 Decision Contract。
- Snapshot 使用规范 JSON 计算 SHA-256，输入不变时输出与摘要不变。
- 九个 Agent 只做动态责任投影；没有工作项时显示“等待有证据的上游输入”，不猜测进度。

## Verification

```text
uv run python scripts/verify_secrets.py
  PASS：433 个非忽略工作树文件、434 个历史路径

uv run ruff check .
  PASS

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
  PASS：360 passed

npm test
  PASS：23 passed

npm run build
  PASS：Next.js 生产构建与 TypeScript

uv run alembic heads
  PASS：20260721_0040（单 head）

全新 PostgreSQL：
  PASS：upgrade -> 20260721_0040
  PASS：GET /health/ready -> 200 / database ok
  PASS：GET /v1/operating-workbench/briefing -> 200
  PASS：8 个 Gate blocker、9 个 Agent、64 位 snapshot SHA-256
  PASS：automatic_execution=false、platform_write_allowed=false

git diff --check
  PASS
```

## Review findings

| 级别 | 结论 | 处理 |
|---|---|---|
| P0 | 无 | no-op |
| P1 | 无本次变更新增项 | no-op |
| P2 | 无 | no-op |
| Info | `npm audit --omit=dev` 在当前锁文件报告 Next 间接 PostCSS 的 2 个 high；本次未改依赖，`npm audit fix --force` 给出不可信的降级式主版本建议 | defer 到依赖安全轨，不在本功能 PR 强制改写 |

## 未被解除的业务阻塞

该工程交付不提供真实 28 天 Ozon 候选数据、三家正式报价、样品实测、合规结论、实际全成本、
正式 Listing 批准或真实平台验收。`SKU-000/001/002/003` 和 `OZN-003` 仍按任务真源失败关闭。
