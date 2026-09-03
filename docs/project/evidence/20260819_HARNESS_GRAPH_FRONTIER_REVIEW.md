# Harness Graph / AI-native 前沿复核 Evidence

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-EVD-HARNESS-GRAPH-FRONTIER-20260819 |
| date | 2026-08-19 |
| status | Engineering governance evidence; not a Gate approval |
| owner | 项目总控 |
| exact_scope | Harness Graph 多智能体编排、前沿采用复核、只读控制快照 |
| frontier_review | checked_no_change |
| source_access_date | 2026-08-19 |
| external_write | false |
| runtime_dependency_changed_by_this_review | false |
| registry_decision_changed | false |
| migration_delivered_by_this_review | none |
| external_resolver_connected | false |
| independent_reviewer_registry_connected | false |

## 1. 复核结论

本次复核不改变 `docs/project/registries/frontier_technology_adoption.json` 的机器真源。
当前结论仍是：

- `agent_run_tracing_and_evals` 保持 `adopt_now`，但只表示 KJDS 的 provider-neutral tracing / eval
  合同可继续实现，不表示接受托管 Evals 或托管 Graders；
- `durable_workflow_adapter` 仍是 `pilot`，适合隔离试验，不是当前运行时权威；
- `causal_temporal_graphrag_memory` 仍是 `pilot`，只可做受控试验；
- `mcp_oauth_resource_authorization` 保持 `pilot`；
- `mcp_tasks_durable_protocol`、`a2a_cross_agent_interoperability`、`webdriver_bidi_browser_provider`、
  `torchao_local_inference_optimization` 仍保持 `watch`；
- `openai_hosted_evals_graders_dependency` 仍保持 `reject_now`；
- `clickhouse_iceberg_platform_expansion` 仍保持 `reject_now`。

本次只记录 `checked_no_change`，不把观察误写成新采用，不把浏览证据误写成生产批准。该结论仅描述
本次前沿复核，不描述整个并行工作树是否存在 runtime、API、migration 或 persistence 候选文件；
这些并行文件不是本 Evidence 的交付、采用或发布证明。

## 2. 访问的官方来源

以下官方页面在 2026-08-19 的只读人工复核中可访问，观察结果与现有 registry 结论一致。当前没有
接入外部 resolver 来保存带内容哈希、时间戳或签名的解析回执，也没有独立 reviewer registry 为本次
复核签发 attestation；因此下列链接是可追溯来源定位，不是外部认证证据：

- [Temporal](https://temporal.io/)
- [MCP Tasks overview](https://modelcontextprotocol.io/extensions/tasks/overview)
- [MCP Tasks draft specification](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks)
- [MCP 2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28)
- [A2A latest](https://a2a-protocol.org/latest/)
- [GraphRAG publications](https://www.microsoft.com/en-us/research/project/graphrag/publications/)
- [OpenAI Agents SDK integrations and observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)
- [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations)

## 3. 关键观察

| 候选 | 观察 | 结论 |
|---|---|---|
| Temporal | 官方站点仍明确强调 durable execution、replay、recovery、retry 和长期运行工作流。 | 说明 Temporal 仍成熟，但不改变 KJDS 当前“进程内隔离核”的选择。 |
| MCP Tasks | Tasks 扩展页显示这是 MCP core 之外的任务扩展，且文档明确为 draft；扩展需要 client/server 双端显式支持。 | 继续保持 watch，不升级为运行时权威。 |
| MCP 2026-07-28 | core 协议支持扩展协商和资源/授权边界，但没有把 KJDS 的业务真源自动变成 protocol status。 | 维持 `mcp_oauth_resource_authorization=pilot`。 |
| A2A | 最新站点显示 v1.0 及 agent interop 叙事，但仍需要 KJDS 侧做权威和 scope 映射。 | 继续 watch。 |
| GraphRAG | Microsoft Research 公共页面仍把 GraphRAG 放在 publication / research 语境。 | 仍是 pilot，不进入 runtime authority。 |
| OpenAI Agents tracing | 官方文档确认 Agents SDK 内建 tracing，可记录 model calls、tool calls、handoffs、guardrails 和 custom spans。 | 支持 KJDS provider-neutral tracing contract，但不把 hosted dashboard 变成真源。 |
| OpenAI hosted evals | deprecations 页面仍是迁移依据。 | 继续 reject_now，不新增生产依赖。 |

## 4. 对仓库注册表的影响

本次复核确认以下边界不变：

- `docs/project/registries/frontier_technology_adoption.json` 仍是唯一机器真源；
- `external_write_allowed=false`；
- 本次复核没有改变 runtime dependency；该结论不覆盖工作树中的并行候选变更；
- `formal_fact_promotion_allowed=false`；
- `checked_no_change` 只表示“访问并核验过”，不表示 registry 已改写；
- BAS-223 仍占用 `MASTER_SPEC` 写域；本 Evidence 不授权、不验收也不归因任何并行的
  `MASTER_SPEC` 修改。

## 5. 控制面结果

本次复核支持新增只读控制脚本，用于把当前控制对象编译成队列视图：

- `GlobalPortfolioOrchestrator.snapshot()`
- `LoopEngineeringService.registry_snapshot()`
- `LoopEngineeringService.evolution_snapshot()`
- Harness / workspace 只读快照

脚本只能输出控制队列和控制边界，不能发起业务写、权限写或外部动作。没有提供 Harness project
标识时，Harness 部分只能报告 `unavailable`，不能被解释为已完成实时 Harness 解析或业务核验。

## 6. Evidence 能力边界

- `external_resolver_connected=false`：本次没有外部 source resolver、内容快照哈希、签名回执或
  可独立重放的 resolver receipt。
- `independent_reviewer_registry_connected=false`：本次没有把复核者身份绑定到独立 reviewer
  registry，也没有注册复核者 attestation。
- `ControlEvent`、checkpoint、测试结果和只读控制快照只在进程内恢复与工程治理边界内可信；它们
  不是 Operating Fact、Approval、Permit、FinanceEntry、业务 Evidence 或外部写授权。
- 工作树中并行存在的 runtime/API/OpenAPI/Alembic/PostgreSQL/`MASTER_SPEC` 文件不属于本次
  frontier review 的交付，不能用于扩大 `checked_no_change` 的含义。
