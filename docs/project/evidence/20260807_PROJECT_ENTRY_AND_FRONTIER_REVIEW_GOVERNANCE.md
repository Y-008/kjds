# 项目入口与前沿技术持续复核治理 Evidence

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-EVD-PROJECT-FRONTIER-20260807 |
| date | 2026-08-07 |
| status | Engineering governance evidence; not a Gate approval |
| owner | 项目总控 |
| exact_scope | 根目录项目入口、Coding Agent 前沿复核规则、前沿注册表防漂移测试 |
| frontier_review | checked_no_change |
| source_access_date | 2026-08-07 |
| external_write | false |
| runtime_dependency_changed | false |
| registry_decision_changed | false |
| migration | none |

## 1. 本次复核范围

本次只复核与“项目入口、Coding Agent 工作流和当前 Web 技术基线”直接相关的两个既有候选：

- `agent_run_tracing_and_evals`
- `react_19_2_next_16_delivery_patterns`

没有到期且与本次修改无关的 Temporal、GraphRAG、MCP、A2A、PostgreSQL 18、OPA、SPIFFE、
WebDriver BiDi、torchao、ClickHouse 和 Iceberg 条目不做虚假刷新。

## 2. 官方来源与观察

| 候选 | 官方来源（2026-08-07 访问） | 观察 | 结论 |
|---|---|---|---|
| Agent tracing/evals | [OpenAI Agents guide](https://developers.openai.com/api/docs/guides/agents)、[Graders API](https://platform.openai.com/docs/api-reference/graders)、[Evals API](https://platform.openai.com/docs/api-reference/evals/) | 当前官方文档继续提供 Agents、multi-agent、tracing、graders 和 evals；这支持既有 provider-neutral Trace/Eval Evidence 方向，但不证明 KJDS 应引入 provider-owned 业务真源 | `checked_no_change`；维持 `adopt_now` 的有界工程含义，不增加依赖或权限 |
| React/Next delivery patterns | [React versions](https://react.dev/versions)、[Next.js releases](https://nextjs.org/blog) | React 官方当前稳定主线为 19.2，列出的最新补丁为 19.2.7；Next.js 官方将 16.2.11 标为 Active LTS，16.3 仍为 Preview。仓库 `web/package.json` 已使用 Next.js 16.2.11、React/React DOM 19.2.7 | `checked_no_change`；不为 Preview 重写或升级稳定 Web 基线 |

## 3. 决定与日期边界

- `docs/project/registries/frontier_technology_adoption.json` 仍是唯一机器采用真源。
- 本次没有产生采用决定、成熟度、Gate、Owner 或控制边界变化，因此注册表 `as_of=2026-08-03`
  以及两个候选的 `reviewed_on` 不修改。
- 本 Evidence 证明 2026-08-07 对本次 exact scope 做过相关性复核，只能得出
  `checked_no_change`；不得外推为全部 15 个候选已在该日期重新评审。
- 下一次复核遵循注册表各候选的 `review_due_on`，或在相关重大任务、安全公告、稳定版发布、
  规范破坏性变化出现时提前触发。

## 4. 已实施控制

- 根目录 `项目.md` 只做入口，不复制注册表候选状态和动态任务完成度。
- `AGENTS.md` 要求重大任务在设计前完成相关前沿技术复核，并把 `required/not_required`、
  `checked_no_change/changed` 和官方来源写入任务 Evidence。
- 注册表测试绑定 `as_of` 与条目 `reviewed_on`，并要求复核日期和官方 URL 可在前沿研究
  Evidence 中共同找到，防止只改日期制造“最新”假象。
- 本切片不运行数据库、Alembic 或 G-1，不修改生产依赖、外部权限或运行时业务真相。
