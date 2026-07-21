# 2026-07-18 Outbox 覆盖清单验证

| 项目 | 结果 |
|---|---|
| 任务 | `BAS-017` |
| 状态 | PASS |
| Alembic head | `20260717_0035`（无新增迁移） |
| 覆盖范围 | 直接管理 SQLAlchemy 事务的控制面模块 |
| 分类结果 | covered 2 / polling 2 / deferred 4 / internal 15 / infrastructure 2 |
| 自动测试 | 139 passed |
| 密钥扫描 | 234 个非忽略文件 |
| G-1 | PASS |
| 运行基础设施变化 | 无 |

## 验收目标

1. `docs/project/registries/outbox_coverage.json` 逐项登记所有直接事务模块。
2. 每项记录当前交付合同、分类理由和必须重新评审的触发条件。
3. 清单明确 `full_system_outbox=false`，不把内部状态或轮询合同包装成 Outbox。
4. 标准库测试从源码发现直接事务模块，并要求其集合与清单精确一致。
5. 新增、删除或改名直接事务模块而未同步清单时，质量门失败。

## 验证结果

- `uv run ruff check .`：PASS。
- `uv run pytest --basetemp .runtime/pytest-bas-017 -o cache_dir=.runtime/pytest-cache-bas-017`：139 passed，保留 1 条既有 Starlette/httpx 弃用警告。
- `uv run python scripts/verify_secrets.py`：234 个非忽略文件通过。
- `scripts/verify-g1.ps1`：PASS；迁移升级/回滚/再升级、真实 PostgreSQL Outbox/Gate API、API/Web、隔离备份恢复和资源清理全部通过。
- 机器报告：`.runtime/G1_VERIFICATION.json`，完成时间 `2026-07-18T04:36:54.7319825Z`。
- 恢复备份 SHA-256：`c5fe61c8dfea981d8976f14bb8668b1a6bae15ce184a25db5134b73933d02a92`；恢复用时 3.214 秒；商品/订单/证据/只读运行计数分别为 4/0/19/1。

## 保留边界

本批不新增事件、迁移、消息队列、外部 sink 或常驻 worker。清单不授予生产副作用权限；模块只有出现已批准的真实跨边界消费者或到达登记 Gate 时，才进入下一批事务 Outbox 设计与验证。
