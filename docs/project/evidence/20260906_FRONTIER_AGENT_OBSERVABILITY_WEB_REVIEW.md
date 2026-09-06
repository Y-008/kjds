# Agent 可观测性、OTel GenAI 与 Web 框架前沿复核 Evidence

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-EVD-FRONTIER-AGENT-OBSERVABILITY-WEB-20260906 |
| date | 2026-09-06 |
| status | Engineering governance evidence; not a Gate approval |
| owner | 项目总控（agent_platform / observability / web_platform） |
| exact_scope | `agent_run_tracing_and_evals`、`opentelemetry_genai_semantic_conventions`、`react_19_2_next_16_delivery_patterns` |
| frontier_review | checked_no_change |
| source_access_date | 2026-09-06 |
| external_write | false |
| runtime_dependency_changed | false |
| registry_decision_changed | false; review metadata advanced after a completed source review |
| next_review | 2026-10-06 |

## 1. 复核结论

三个候选的采用决定、成熟度和控制边界均保持不变。本次只在完成当前官方材料复核后推进
`reviewed_on`、`review_due_on` 与注册表 `as_of`，没有以裸日期模拟新鲜度：

- `agent_run_tracing_and_evals` 继续为 `adopt_now`，仅指 KJDS 自有 provider-neutral
  AgentRun/Trace/Eval 合同可受控实现。
- `opentelemetry_genai_semantic_conventions` 继续为 `pilot`，仍通过固定版本翻译层隔离，
  不把 Development 语义直接变成领域真相。
- `react_19_2_next_16_delivery_patterns` 继续为 `adopt_now`，仅进入有测量目标的实现切片，
  不因上游稳定版自动升级当前依赖。

## 2. 官方来源与观察

### Agent tracing/evals

- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/) 当前文档
  描述内建 tracing 可记录 workflow、LLM generation、tool call、handoff、guardrail 和
  custom event，并明确 generation/function span 可能包含敏感数据，可通过配置关闭敏感
  内容采集。该材料支持 KJDS 的脱敏、provider-neutral 和自有 Evidence 边界，不授权采用
  OpenAI 托管 Trace/Evals 作为经营真相。
- [openai-agents-python releases](https://github.com/openai/openai-agents-python/releases) 当前
  release 列表仍有维护中的版本（页面列出 v0.22.0 等版本），因此“有维护的 tracing 参考”
  观察保持有效；版本变化仍需单独依赖评估。
- [OpenAI API deprecations](https://developers.openai.com/api/docs/deprecations) 仍说明 Evals
  platform 于 2026-06-03 宣布弃用、2026-10-31 转只读、2026-11-30 计划关闭 dashboard/API，
  且 documented graders 属于迁移范围。该边界支持 KJDS 不新增托管 Evals/Graders 依赖。

### OpenTelemetry GenAI

- [OpenTelemetry semantic conventions 1.44.0](https://opentelemetry.io/docs/specs/semconv/) 当前
  页面将 Generative AI semantic conventions 标记为已移至专门仓库。
- [GenAI semantic conventions README](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/README.md)
  当前标记 `Status: Development`，列出 events、exceptions、metrics、model spans 和 agent
  spans；因此仍需版本固定、映射隔离和默认禁用内容字段。
- [GenAI semantic conventions releases](https://github.com/open-telemetry/semantic-conventions-genai/releases)
  未提供可作为 KJDS 兼容承诺的正式发布版本；本次不把仓库状态解释成生产稳定性证明。

### React/Next

- [React 19.2](https://react.dev/blog/2025/10/01/react-19-2) 的官方材料继续描述
  `<Activity />`、`useEffectEvent`、`cacheSignal`、partial pre-rendering 等能力；候选仍限于
  有测量目标的局部使用。
- [Next.js 16](https://nextjs.org/blog/next-16) 描述 opt-in Cache Components、DevTools MCP、
  proxy 边界以及稳定/实验能力的区分；缓存和服务端权威边界仍是 KJDS 的进入条件。
- [Next.js 16.3](https://nextjs.org/blog/next-16-3) 明确在 stable release 旁仍包含若干
  experimental features（如 Rust React Compiler 路径）；因此上游发布不构成 KJDS 自动升级
  或生产放行。

## 3. KJDS 边界与未决项

- 三个候选的 `production_dependency_allowed`、`external_write_allowed` 和
  `formal_fact_promotion_allowed` 均保持 `false`。
- 本次没有安装、升级或修改 Web/OTel/Agents SDK 依赖，也没有把第三方 dashboard、trace 或
  eval 服务设为 canonical truth。
- 本次没有连接外部 resolver、内容哈希/签名回执或独立 reviewer registry；官方链接用于可追溯
  来源定位，不能替代发布物、运行时、隐私或业务 Gate 证据。
- 各候选的 exit gate（脱敏、租户隔离、回归、缓存安全、完整 Web 测试和 measured benefit）
  仍须在对应实现切片中单独验证。

## 4. 关联机器真源与合同

- `docs/project/registries/frontier_technology_adoption.json`
- `docs/project/registries/requirements_traceability.json`
- `docs/adr/ADR-0089-one-person-dual-engine-operating-system-and-frontier-adoption.md`
- `docs/project/evidence/20260807_PROJECT_ENTRY_AND_FRONTIER_REVIEW_GOVERNANCE.md`
