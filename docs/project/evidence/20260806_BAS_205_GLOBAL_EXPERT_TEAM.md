# BAS-205 全球专家委员会与首席组合调度工程 Evidence

| 字段 | 值 |
|---|---|
| task | BAS-205 |
| requirement | BR-140 |
| adr | ADR-0095 |
| verified_at | 2026-08-06 |
| status | DONE_ENGINEERING |

## 冻结决定

- 团队：`ai_core_human_professional_review`。
- 范围：`global_research_russia_ozon_execution_first`。
- 总负责人：`business_decision_high_risk_dual_sign`。
- 编制：一名 `global_chief_commerce_officer`、十二个有界专家席位、五个独立控制角色。

## 交付

- `global_expert_team_registry.json` 冻结专家、任务路由、真人复核、俄罗斯 Cell、L0–L4
  决策层级、协作节奏和全部 false 的外写控制边界。
- `GlobalPortfolioOrchestrator` 通过 `snapshot()` 与 `route(...)` 两个 Interface 编译团队
  快照和确定性 `ExpertTaskContract`；未知任务、注册表漂移、负责人越权、缺 Evidence、
  非俄罗斯高风险执行均失败关闭。
- 每份 `ExpertTaskContract` 同时编译精确范围、专家工具/数据白名单、成本/时限边界、
  交接合同、Trace、评测策略版本、真人替补要求和禁止输入，不向专家传播凭据或原始客户数据。
- `GET /v1/global-expert-team/registry` 提供认证只读快照；
  `POST /v1/global-expert-team/route` 是 Kill Switch 允许的无副作用控制路径，只编译
  proposal-only 路由，不创建 Task、Decision、Fact、FinanceEntry、Approval 或 Permit。
- Loop Engineering registry 升级到 `2.2`，`subagents` 从 `design_only` 变为 `partial`；
  这只表示受控路由 Interface 已落地，不代表自治专家或真人专家已经投入运行。

## 验证

```text
uv run pytest ... targeted global expert/loop/API tests
25 passed

uv run python scripts/verify_secrets.py
Secret scan passed: 1386 non-ignored worktree files and 1376 historical paths checked

uv run ruff check .
All checks passed

uv run pytest -q -p no:cacheprovider --ignore-glob=tests/*_postgres.py ...
2423 passed, 1 skipped, 37 warnings in 193.65s

git diff --check
PASS（仅 Git 的 LF/CRLF 提示）
```

全量内存测试使用 `KJDS_REPOSITORY=memory` 和仓库测试专用的临时 Strategic Benchmark
sealing key；未读取或输出生产凭据。OpenAPI 固定快照已重新生成，快照一致性与受保护接口
安全声明测试通过。

PostgreSQL 集成全量不在本 Evidence 中声明为通过：当前用户 `.env` 指向的本地共享测试库
存在既有角色授权和迁移状态残留，导致五个 `*_postgres.py` 模块的夹具无法取得干净基线；
故最终可复现基线明确排除这些模块。本切片不含数据库迁移或 PostgreSQL 写入路径。

## 保留边界

- 真实 Business Owner、俄罗斯战区负责人及律师、税务、认证、财务、关务、质检、母语
  和独立 Approver 仍须实名绑定；注册表不证明聘任或执业意见。
- 俄罗斯准入、Ozon 真实订单、结算、银行到账与 Actual Cash CM3 状态不变。
- 非俄罗斯/Ozon 的 L2–L4 路由保持 `blocked_scope`；所有市场仍可进行 L0/L1 研究。
- 本切片不持久化派工或决定；后续若需要动态调度，必须复用现有 OperatingTask、
  Decision、Gate 与 Outbox，而不是建设第二套任务账。
