# KJDS 项目交接入口

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-HANDOVER-001 |
| status | Active |
| snapshot_at | 2026-07-21 |
| repository | `D:\KJDS\kjds` |
| canonical_task_source | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) |
| master_spec | [MASTER_SPEC.md](MASTER_SPEC.md) |

本文件不保存任务副本、测试数量、迁移号或完成度。交接时直接读取任务真源和当前运行证据，避免快照过期后继续被引用。

## 交接判断

KJDS 已具备可运行、可审计、可恢复的经营控制面工程骨架，但真实经营闭环尚未完成。工程工作不能替代账户主体决定、官方需求原件、真实候选、三报价、样品、Passport、结算、银行和 FX 证据。

## 接手顺序

1. 阅读 [AGENTS.md](../../AGENTS.md) 和 [MASTER_SPEC.md](MASTER_SPEC.md)。
2. 从 [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) 取得当前任务、状态、依赖、Owner 和下一动作。
3. 检查 `git status`、当前分支、远程 PR 和三项 GitHub CI。
4. 运行最小本地质量门；数据库/API 变更再运行 G-1。
5. 查看对应 [evidence/](evidence/)；历史证据只证明当时版本。
6. 外部输入缺失时保持 `BLOCKED` 或 `PARTIAL_BLOCKED`，不得用新增代码掩盖。

## 关键运行命令

```powershell
uv run python scripts/verify_secrets.py
uv run ruff check .
uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
git diff --check
```

完整 G-1：

```powershell
.\scripts\verify-g1.ps1
```

实时结果位于 `.runtime/G1_VERIFICATION.json`，该文件不提交。

## 不可越过的边界

- `research` 产物不得冒充真实经营事实。
- 付款、采购、发布、广告、补货、`actual` 晋升和自动入账必须重新授权。
- KJDS 是业务控制面；ComfyUI 是媒体执行器；n8n 只做外围自动化。
- 不在文档、日志、提交或对话中保存密钥、银行资料和客户数据。
- 当前公开仓库 `Y-008/kjds` 已启用 GitHub 强制分支保护；所有变更必须经过 PR、三项 CI 和已解决的 Review 会话，禁止强推或删除 `main`。
