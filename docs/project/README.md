# KJDS 项目文档中心

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-DOC-INDEX |
| owner | 项目负责人（待确认） |
| approver | 经营负责人 |
| status | Active |
| version | 5.0 |
| last_reviewed | 2026-07-21 |
| gate | G-1–G8 |

本文件只做导航，不维护迁移号、测试数量或任务状态。

## 唯一真源

| 主题 | 权威位置 | 规则 |
|---|---|---|
| 稳定需求、边界、架构和验收 | [MASTER_SPEC.md](MASTER_SPEC.md) | 不写动态完成度 |
| 当前任务、状态、依赖和下一动作 | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) | 唯一动态任务真源 |
| Gate 定义 | [02_ROADMAP_AND_GATES.md](02_ROADMAP_AND_GATES.md) | 只定义放行标准 |
| 决策、来源和未知项 | [04_SOURCE_DECISION_UNKNOWN_REGISTER.md](04_SOURCE_DECISION_UNKNOWN_REGISTER.md) | 分开保存事实、假设、决定和未知 |
| 架构决策 | [../adr/](../adr/) | 通过 ADR 修改稳定边界 |
| 能力验收 | [evidence/](evidence/) | 证明对应版本，不自动代表当前仍通过 |
| 当前运行验证 | `.runtime/G1_VERIFICATION.json` | 本地生成，不提交 |

[13_PROJECT_HANDOVER_AND_TASK_STATUS.md](13_PROJECT_HANDOVER_AND_TASK_STATUS.md) 只是一页交接导航，不复制任务表。

## 真实业务启动

Web 控制台直接读取服务端 readiness，在唯一 `SKU-000` 中区分研究闭环与真实经营：

- 合格研究原件可以继续候选、模拟利润、ComfyUI、Listing 草稿和审批演练；
- 付款、采购、发布、广告、补货和正式事实晋升必须满足真实经营门；
- 公开示例、固定测试和第三方信号不能放行真实经营。

公开空模板位于 [`web/public/startup/`](../../web/public/startup/)。真实资料只能填写在 Git 忽略的本地副本：

```powershell
.\scripts\prepare-startup-package.ps1
uv run python scripts/validate_startup_package.py .runtime/startup-intake
uv run python scripts/validate_startup_package.py .runtime/startup-intake --require-review-ready
```

模板只帮助收集资料，不会读取原件、写数据库、晋升事实或放行 Gate。禁止在模板中保存密码、API Key、Token、完整银行账号和身份文件。

## 工程验证

基础检查：

```powershell
uv run python scripts/verify_secrets.py
uv run ruff check .
uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
git diff --check
```

Web 变更另运行：

```powershell
Set-Location web
npm ci
npm test
npm run build
```

数据库/API 变更还必须验证唯一 Alembic head、PostgreSQL 升级、`/health/ready` 和对应 G-1 场景。完整本地链：

```powershell
.\scripts\verify-g1.ps1
```

## 长期边界

- KJDS 拥有商品、利润、Evidence、Gate、审批和执行授权真相。
- ComfyUI 只执行受控媒体工作流，输出必须回到 KJDS 的 Blob、Evidence、Lineage、QA 和审批。
- n8n 只能承担定时、通知和外围触发，不得直写数据库或直接调用平台写端点。
- Word 文档和研究母稿保持只读参考，不作为任务、运行或经营事实真源。
- G7 前不建设第二后台、第二审批系统、微服务、Kafka、Temporal、Kubernetes 或任意 Agent 自主高风险执行。
