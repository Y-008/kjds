# KJDS 项目文档中心

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-DOC-INDEX |
| owner | 项目负责人（待确认） |
| approver | 经营负责人 |
| status | Active |
| version | 5.6 |
| last_reviewed | 2026-08-14 |
| gate | G-1–G8 |

本文件只做导航，不维护迁移号、测试数量或任务状态。

## 唯一真源

| 主题 | 权威位置 | 规则 |
|---|---|---|
| 老板、团队与 Coding Agent 统一入口 | [../../项目.md](../../项目.md) | 只做入口和持续更新规则，不复制动态或机器真相 |
| 稳定需求、边界、架构和验收 | [MASTER_SPEC.md](MASTER_SPEC.md) | 不写动态完成度 |
| 当前任务、状态、依赖和下一动作 | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) | 唯一动态任务真源 |
| Gate 定义 | [02_ROADMAP_AND_GATES.md](02_ROADMAP_AND_GATES.md) | 只定义放行标准 |
| 决策、来源和未知项 | [04_SOURCE_DECISION_UNKNOWN_REGISTER.md](04_SOURCE_DECISION_UNKNOWN_REGISTER.md) | 分开保存事实、假设、决定和未知 |
| 架构决策 | [../adr/](../adr/) | 通过 ADR 修改稳定边界 |
| 能力验收 | [evidence/](evidence/) | 证明对应版本，不自动代表当前仍通过 |
| 商业化与俄罗斯作战合同 | [20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md](20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md) | 定义双轮商业模型、经营/软件 Gate 与多任务调度；动态状态仍回到 `03` |
| 董事会战略与 90 天经营计划 | [22_BOARD_STRATEGY_AND_90_DAY_OPERATING_PLAN.md](22_BOARD_STRATEGY_AND_90_DAY_OPERATING_PLAN.md) | 冻结当前价值楔子、80/20 双线、资本放行、Truth SKU/C0/Stop Gate 与经营 KPI；不替代 `MASTER_SPEC`、动态任务表或一手经营 Evidence |
| 一人主责双引擎经营系统 | [14_ONE_PERSON_DUAL_ENGINE_OPERATING_SYSTEM.md](14_ONE_PERSON_DUAL_ENGINE_OPERATING_SYSTEM.md) | 定义前中后台、逆漏斗、付费 MVP、案例模块化、控制轨与多线程写域 |
| 社媒卖家情报与运营系统 | [15_SOCIAL_COMMERCE_INTELLIGENCE_AND_OPERATIONS.md](15_SOCIAL_COMMERCE_INTELLIGENCE_AND_OPERATIONS.md) | 定义全量采集、多维用户/内容分析、小红书/抖音分线与 campaign 级发布互动回读 |
| 俄罗斯市场需求与事件雷达 | [16_RUSSIA_MARKET_DEMAND_AND_EVENT_RADAR.md](16_RUSSIA_MARKET_DEMAND_AND_EVENT_RADAR.md) | 定义 Ozon/WB/Yandex/Telegram/VK/宏观事件的全量、多源、时序和跨源验证 |
| 全球专家团队与团队总控塔 | [17_GLOBAL_CROSS_BORDER_EXPERT_TEAM.md](17_GLOBAL_CROSS_BORDER_EXPERT_TEAM.md)、[18_TEAM_CONTROL_TOWER.md](18_TEAM_CONTROL_TOWER.md) | 定义 18 核心角色、12 AI 专家、20–40 人专家池容量、5 独立控制角色、90 天关键路径、五类权威投影、四条业务主线与唯一下一动作 |
| A-I 泳道执行租约 | [registries/active_workstream_assignments.json](registries/active_workstream_assignments.json) | 当前真正占用 WIP 与共享写域的机器真源；历史 `IN_PROGRESS` 不自动获得写租约 |
| TeamAgent 进化 Loop | [registries/loop_engineering_registry.json](registries/loop_engineering_registry.json) | 定义角色边界、Eval→Shadow→Review→Promotion/Rollback、Graph 学习和持续更新边界 |
| 前沿技术采用雷达 | [registries/frontier_technology_adoption.json](registries/frontier_technology_adoption.json) | `adopt_now/pilot/watch/reject_now` 的机器真源；注册不等于实现或生产放行 |
| 历史需求追溯矩阵 | [registries/requirements_traceability.json](registries/requirements_traceability.json) | 逐项绑定需求来源、机器合同、实现版本、Owner、Gate、Evidence、状态和未完成项；工程状态不证明业务结果 |
| AI 自动经营与递归扩品 | [19_AUTOMATED_COMMERCE_AND_RECURSIVE_STORE_MINING_PRD.md](19_AUTOMATED_COMMERCE_AND_RECURSIVE_STORE_MINING_PRD.md)、[ADR-0097](../adr/ADR-0097-automated-commerce-loop-and-source-linkback.md) | BAS-219A 主线核心与 BAS-219B 隔离 runtime/API/Web 分期；外写仍走既有治理链 |
| 社媒来源采用注册表 | [registries/social_commerce_source_adoption.json](registries/social_commerce_source_adoption.json) | 固化官方来源、GitHub 候选、固定版本、许可证、全量采集与 campaign 能力选择 |
| 俄罗斯市场来源注册表 | [registries/russia_market_intelligence_sources.json](registries/russia_market_intelligence_sources.json) | 固化站内需求、搜索、社媒、平台与宏观事件来源、限制和下一 Gate |
| 思维与前沿研究 Evidence | [evidence/20260803_DOUYIN_MINDSET_AND_FRONTIER_TECH_RESEARCH.md](evidence/20260803_DOUYIN_MINDSET_AND_FRONTIER_TECH_RESEARCH.md) | 区分 Observation、一手来源、Inference 与 UNKNOWN |
| 项目入口与前沿复核 Evidence | [evidence/20260807_PROJECT_ENTRY_AND_FRONTIER_REVIEW_GOVERNANCE.md](evidence/20260807_PROJECT_ENTRY_AND_FRONTIER_REVIEW_GOVERNANCE.md) | 记录本次相关官方来源 freshness 检查与 `checked_no_change` 结论 |
| 社媒开源研究 Evidence | [evidence/20260803_SOCIAL_COMMERCE_OPEN_SOURCE_RESEARCH.md](evidence/20260803_SOCIAL_COMMERCE_OPEN_SOURCE_RESEARCH.md) | 记录官方平台、GitHub 来源、许可、可借鉴模式、当前缺口与用户指定 CLI 选择 |
| 俄罗斯需求与事件来源 Evidence | [evidence/20260803_RUSSIA_MARKET_DEMAND_AND_EVENT_SOURCE_RESEARCH.md](evidence/20260803_RUSSIA_MARKET_DEMAND_AND_EVENT_SOURCE_RESEARCH.md) | 记录官方来源能力、当前公共观察、来源上限与尚未接入的真实凭据 |
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
uv run python scripts/validate_write_paths.py
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
- [动作政策注册表](registries/action_policy_registry.json) 定义动作风险，[写路径注册表](registries/write_path_registry.json) 定义实际入口、写点、执行器、回读和补偿；两者必须一一对应。
- ComfyUI 只执行受控媒体工作流，输出必须回到 KJDS 的 Blob、Evidence、Lineage、QA 和审批。
- n8n 只能承担定时、通知和外围触发，不得直写数据库或直接调用平台写端点。
- Word 文档和研究母稿保持只读参考，不作为任务、运行或经营事实真源。
- G7 前不建设第二后台、第二审批系统、微服务、Kafka、Temporal、Kubernetes 或任意 Agent 自主高风险执行。
