# 项目入口与前沿技术持续复核治理 Evidence

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-EVD-PROJECT-FRONTIER-20260807 |
| date | 2026-08-07 |
| status | Engineering governance evidence; not a Gate approval |
| owner | 项目总控 |
| exact_scope | 根目录项目入口、Coding Agent 前沿复核规则、前沿注册表材料纠正与防漂移测试 |
| frontier_review | changed |
| source_access_date | 2026-08-07 |
| external_write | false |
| runtime_dependency_changed | false |
| registry_decision_changed | true |
| migration | none |

## 1. 本次复核范围

本次复核与“项目入口、Coding Agent 工作流和当前 Web 技术基线”直接相关的既有候选，
并把原先混合在一个条目中的内部能力与退场中的托管产品拆开：

- `agent_run_tracing_and_evals`
- `openai_hosted_evals_graders_dependency`
- `opentelemetry_genai_semantic_conventions`
- `react_19_2_next_16_delivery_patterns`

同时对 A2A、MCP 和 GraphRAG 的当前官方入口做相关性复核，结果为 `checked_no_change`，
但不修改这些条目的 `reviewed_on`。Temporal、PostgreSQL 18、OPA、SPIFFE、WebDriver BiDi、
torchao、ClickHouse 和 Iceberg 条目不做虚假刷新。

## 2. 官方来源与观察

| 候选 | 官方来源（2026-08-07 访问） | 观察 | 结论 |
|---|---|---|---|
| KJDS provider-neutral AgentRun/tracing/eval governance | [Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/)、[Agents SDK releases](https://github.com/openai/openai-agents-python/releases)、[OpenAI deprecations](https://developers.openai.com/api/docs/deprecations) | Agents SDK tracing 仍有官方文档并持续发布；但这只能作为 tracing 参考，不能替代 KJDS 自有 Eval corpus、阈值、Evidence 和晋级权威 | `changed`；`adopt_now` 仅保留给 KJDS provider-neutral 内部合同，生产依赖、外写和自晋级仍为 false |
| OpenAI hosted Evals/Graders | [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations)、[Moving from OpenAI Evals to Promptfoo](https://developers.openai.com/cookbook/examples/evaluation/moving-from-openai-evals-to-promptfoo) | 官方于 2026-06-03 宣布 Evals platform 弃用；2026-10-31 existing evals 转只读，2026-11-30 dashboard/API 计划关闭，documented graders 属于迁移范围；官方迁移方向是本地或 CI 中的可移植代码化评测 | `changed`；新增独立 `reject_now` 条目，禁止新增/保留 hosted Evals 或 Graders 生产依赖，仅允许有界导出和迁移 |
| OpenTelemetry GenAI semantic conventions | [Core semconv 1.44.0](https://opentelemetry.io/docs/specs/semconv/)、[GenAI README](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/README.md)、[GenAI releases](https://github.com/open-telemetry/semantic-conventions-genai/releases) | Core 1.44.0 已把 GenAI 指向独立仓库；独立仓库将 GenAI 标为 `Development`，GitHub releases 当前为空 | `changed`；维持 `pilot`，但改为“独立 Development 仓库且无正式 release”，继续要求版本固定、翻译层和默认不采集敏感内容 |
| React/Next delivery patterns | [React 19.2](https://react.dev/blog/2025/10/01/react-19-2)、[Next.js 16](https://nextjs.org/blog/next-16)、[Next.js 16.3](https://nextjs.org/blog/next-16-3) | React 官方稳定主线仍为 19.2；Next.js 已在 2026-08-03 发布 16.3 stable，其中仍包含少数明确 experimental 的能力。仓库 `web/package.json` 继续固定 Next.js 16.2.11、React/React DOM 19.2.7 | `changed`；纠正“16.3 Preview”旧观察，但上游 stable 不等于 KJDS 自动升级或生产放行，本切片不改依赖 |
| A2A / MCP / GraphRAG | [A2A 1.0](https://a2a-protocol.org/latest/announcing-1.0/)、[A2A docs](https://a2a-protocol.org/latest/)、[MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)、[MCP Tasks](https://modelcontextprotocol.io/extensions/tasks/overview)、[GraphRAG publications](https://www.microsoft.com/en-us/research/project/graphrag/publications/)、[LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/) | A2A 仍为已发布但 KJDS 未验证的跨组织协议；MCP core 与 opt-in Tasks 边界未改变 KJDS exact-scope Gate；GraphRAG 仍是研究/隔离 pilot 候选 | `checked_no_change`；不更新 registry review 日期，不引入 runtime dependency 或生产权限 |

## 3. 决定与日期边界

- `docs/project/registries/frontier_technology_adoption.json` 仍是唯一机器采用真源。
- 注册表 `as_of` 更新为 `2026-08-07`。`agent_run_tracing_and_evals`、
  `opentelemetry_genai_semantic_conventions` 与 `react_19_2_next_16_delivery_patterns` 的材料、
  成熟度、风险和 `reviewed_on` 被纠正；新增 `openai_hosted_evals_graders_dependency=reject_now`，
  使托管产品退场决定不再污染 KJDS 内部能力。
- `agent_run_tracing_and_evals=adopt_now` 只表示 KJDS provider-neutral AgentRun/Trace/Eval
  Evidence 合同可继续受控实现，不表示采用 OpenAI hosted Evals、Graders 或任何 provider-owned
  release authority。
- A2A、MCP 与 GraphRAG 的本轮 `checked_no_change` 只记录在本 Evidence，不更新其机器复核日期；
  不得外推为全部 16 个候选已在该日期重新评审。
- 下一次复核遵循注册表各候选的 `review_due_on`，或在相关重大任务、安全公告、稳定版发布、
  规范破坏性变化出现时提前触发。

## 4. 已实施控制

- 根目录 `项目.md` 只做入口，不复制注册表候选状态和动态任务完成度。
- `AGENTS.md` 要求重大任务在设计前完成相关前沿技术复核，并把 `required/not_required`、
  `checked_no_change/changed` 和官方来源写入任务 Evidence。
- 注册表测试绑定 `as_of` 与条目 `reviewed_on`，并要求复核日期和官方 URL 可在前沿研究
  Evidence 中共同找到，防止只改日期制造“最新”假象。
- 注册表测试冻结 provider-neutral Eval 与 deprecated hosted Evals 的独立决策、三段退场日期、
  OTel `1.44.0` / `Development` / no-release 边界，以及所有生产依赖和外写权限继续为 false。
- 本切片不运行数据库、Alembic 或 G-1，不修改生产依赖、外部权限或运行时业务真相。
