# BAS-173 因果/时序检索金标基准 Evidence

## 1. 结论

BAS-173 建立了一个只读、exact-scope、citation-required 的检索评测深模块，复用 PostgreSQL、Evidence 与 canonical Graph，不建立第二套经营检索真相。

- 唯一外部模块接口：`GovernedRetrievalBenchmarkWorkspace.evaluate(...)`。
- 输出合同：`kjds-retrieval-benchmark-observation-v1`，只形成 Observation。
- 当前技术比较：`structured_sql`、`postgresql_fts`、`canonical_graph`、`causal_temporal_graph`。
- `pgvector` 与 `GraphRAG` 固定为 `not_admitted`，本 Gate 未安装、未运行。
- 无迁移、无公共 API、无 OpenAPI 变化、无 runtime 聚合、无新依赖。
- 即使某方法通过全部硬门，winner 仍为 `UNKNOWN`：成本/延迟阈值和独立人工复核尚未签署。

本结果不代表真实模型质量，也不把 repository-owned synthetic fixture 的结果冒充生产经营效果。

## 2. 冻结 Gold Set

文件：`tests/fixtures/retrieval_benchmark/bas173_gold_questions_v1.json`

| 字段 | 冻结值 |
|---|---|
| contract | `kjds-retrieval-gold-set-v1` |
| id/version | `bas173-real-failure-contracts` / `1.0.0` |
| documents | 13 |
| questions | 8 |
| content SHA256 | `1c5527775c815aac0c2feb13aff6d5ad8421fb5eeb4a54ce410ce9107400138a` |
| license class | `repository_owned_synthetic_contract_fixture` |
| customer data | `false` |

问题类别来自仓库已经存在的失败合同或 UNKNOWN：

1. CNY/RUB 利润必须使用 current scoped FX；
2. SKU/变体/shipment profile/数量/有效期绑定后才能提升成本覆盖；
3. 订单、结算、银行到账齐备后才能确认 cash profit；
4. generated/inferred Graph edge 只能是 Observation；
5. downside CM3、退款、CAC/ACOS、履约、现金阈值未签署时保持 `UNKNOWN`；
6. AgentRun/Trace/Eval 成功不能自晋升为 Fact/Approval/Permit/外写；
7. Graph 引用同时满足 recorded-time 与 effective-time；
8. 无反事实证据时，因果 uplift 为 `no_data`。

Gold loader 对 contract/schema、重复 question/document、全局重复 citation ref、逐文档 citation hash、逐题 hash、集合 hash、许可类别、客户数据标记和敏感字段/值执行 fail-closed 校验。answer/UNKNOWN 的 answer key 只能引用 `scope_binding=exact` 文档；跨 scope decoy 不能成为预期 claim/citation。题目和检索文档正文不进入 Observation 输出。

## 3. 唯一真源与读取边界

### 3.1 当前身份授权与历史数据时间分离

每次调用先用服务端可信 UTC clock 调用 `ScopeGrantAuthority.current`，验证当前 Principal 的 tenant/entity/store/authority。调用者的 `as_of` 只作为数据截止时间，不能用于回绕已轮换或撤销的权限。

幂等语义绑定：tenant、entity、store、current authority SHA、actor、project、data as-of、Gold hash、method set 和 idempotency-key hash。检查时间本身不进入 immutable request hash，因此 authority 不变时，时钟推进后的重放仍 byte-equivalent；authority 轮换后形成新 scoped run，旧 Observation 不会被返回。

### 3.2 同一冻结 Corpus

SQL exact 与 PostgreSQL FTS 在同一事务、同一临时表、同一 Gold hash、同一 exact scope/authority/data as-of 上运行。每条可见文档同时满足：

`tenant + entity + store + authority + effective_from <= as_of < effective_until + recorded_at <= as_of + evidence_state=current`

查询词和 FTS query 均使用绑定参数。wrong-scope、stale、revoked、future-effective、future-recorded 和 unsupported decoy 不进入候选。

### 3.3 canonical Graph 时态投影

`AgentHarnessService.temporal_graph_projection(...)` 是 canonical Graph 的只读投影 Seam：

- GraphProject 在 SQL 查询阶段绑定 tenant/entity/store；
- 每个 GraphNode 绑定 tenant/entity/store/scope-grant-authority SHA；
- `created_at <= data as_of`；
- `effective_from <= data as_of < effective_until`；
- edge 的 source/target 必须都属于同一 exact project、scope、authority 和 as-of node 集；
- future node、跨 project endpoint、scope mismatch 均返回 blocked，且不暴露 node/edge；
- inferred edge 或缺 evidence_ref 的 edge 只保留为不可采纳 Observation。

旧 `causal_experiments` / `causal_knowledge` 没有 exact-scope 合同，本基准没有读取它们，也没有把它们作为因果边真源。

### 3.4 Graph Evidence 门

Graph edge 在 retrieval Module 内逐条验证真实 Evidence metadata 和 blob integrity：

- source 为冻结 benchmark fixture source；
- Grade A；
- blob 实际 SHA 与声明 SHA 一致；
- source contract 与 Gold SHA 一致；
- tenant/entity/store/current authority 精确一致；
- Evidence metadata 绑定 Graph edge content SHA；
- `recorded_at <= data as_of`；
- `effective_at <= data as_of < effective_until`。

任一 hash、source、scope、authority、recorded/effective interval 不满足，该 edge 不能生成 claim/citation，也不能成为 winner。

## 4. 状态与评测合同

| 状态 | 含义 |
|---|---|
| `no_data` | 无可采纳记录，claim/citation 均为空 |
| `UNKNOWN` | 合格引用存在，但被询问的经营字段尚未签署或确定 |
| `blocked` | hash、scope、authority、端点或 Evidence 合同冲突 |
| `stale` | 记录存在但已失效；不得进入候选 |
| `not_visible` | 跨作用域记录不进入可见结果；外部保持零泄漏 |
| `not_run` | 当前 Adapter/数据库能力未运行，例如 SQLite 下 PostgreSQL FTS |
| `not_admitted` | 技术未准入；当前为 pgvector/GraphRAG |

逐题输出并核对：citation correctness/completeness、exact-scope isolation、valid-time/currentness、abstention 状态准确性、unsupported-claim rate、latency、cost 和 human-review time。

硬门为 citation precision/completeness 1.0、scope/currentness true、unsupported rate 0、预期状态精确一致。latency/cost 必须有限且非负；本地确定性查询 provider charge 为 0。human review time 保持 `UNKNOWN`。

质量并列不使用观测延迟强行打破。没有签署成本/延迟阈值和独立 review 时，单一硬门通过者或并列通过者都只是 eligible candidate，winner 为 `UNKNOWN`。

## 5. 写入守恒

评测前后对 GraphNode、GraphEdge、Evidence 及数据库全部持久表进行 count/hash 对账。临时 SQL corpus 在事务内创建并删除。运行不生成或修改：

- canonical Graph node/edge；
- Fact；
- FinanceEntry；
- Approval；
- Permit；
- Pilot；
- Outbox；
- 外部系统状态。

输出字段固定声明 `observation_only=true`，以上晋升与外写能力全部为 false；generated/inferred edges 数组只能属于 benchmark Observation。

## 6. 验证矩阵

| Gate | 覆盖 |
|---|---|
| Gold contract | schema/hash drift、重复题/文档/citation、cross-scope answer key、敏感字段/值 |
| Scope | tenant/entity/store/current authority 漂移与跨 scope 零泄漏 |
| Time | current authority + historical data as-of、future-recorded、future node、edge 边界时刻 |
| Evidence | source/hash/scope/authority/Gold hash/edge hash/effective/recorded/Grade A |
| Graph | missing evidence、inferred edge、循环、跨 project endpoint |
| Idempotency | exact replay、同 authority 内容漂移冲突、authority rotation 新 run |
| Retrieval | SQL exact、PostgreSQL FTS、参数注入、同 corpus hash |
| Metrics | citation、abstention、unsupported claim、有限非负 latency/cost |
| Outcome | tie/no eligible winner、`no_data`/`UNKNOWN`/`not_run`/`not_admitted` 区分 |
| Conservation | 持久表、Graph、Evidence 数量与 hash 不变；零外写 |

最终命令与 literal result：

- 聚焦 SQLite：`uv run python -m pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-bas173-p1-focused tests/test_retrieval_benchmark.py tests/test_agent_harness.py` → `28 passed, 1 skipped in 1.03s`。
- PostgreSQL FTS：设置本地测试数据库 URL 后执行 `uv run python -m pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-bas173-p1-postgres tests/test_retrieval_benchmark.py -k postgresql_fts` → `1 passed, 17 deselected in 0.95s`。
- 全后端：设置本地 benchmark sealing key 后执行 `uv run python -m pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-full-bas173-p1` → `1697 passed, 32 skipped, 35 warnings in 96.76s`。
- Ruff：`uv run ruff check .` → `All checks passed!`。
- secret scan：`uv run python scripts/verify_secrets.py` → `Secret scan passed: 1274 non-ignored worktree files and 1267 historical paths checked`。
- diff check：`git diff --check` → exit `0`、无输出。

第一次全后端采集因未提供已有 Strategic Benchmark 测试 sealing key，在 collection 阶段 fail-closed；补入仅用于本地测试的临时环境值后重新执行，得到上述完整通过结果。该值未写入文件或提交。

## 7. Entry / Exit / Rollback

Entry：BAS-172 AgentRun Evidence 已完成；canonical Graph、Evidence、PostgreSQL 可读；BAS-173 机器租约有效。

Exit：冻结 Gold hash；四方法消费相同 corpus/scope/authority/as-of；citation 与 scope/time 硬门通过；PostgreSQL FTS 合同通过；零持久写入；全后端、Ruff、secret、diff gates 通过。

Rollback：移除本票新增的 retrieval Module、两组测试、冻结 fixture 和 Evidence 文档，并回退 `agent_harness.py` 的只读 temporal projection；没有数据库迁移、外部写或数据回填需要逆操作。

## 8. 仍为 UNKNOWN

- 真实客户问题分布上的检索质量；
- 生产数据规模下的 P95/P99 latency 与数据库成本；
- 人工复核耗时；
- 胜者所需成本/延迟阈值与独立 reviewer 签署；
- pgvector/GraphRAG 是否能在相同硬门下超过现有基线；
- 因果 uplift 所需反事实或实验 Evidence。

这些 UNKNOWN 不会被 fixture、模型叙述或单次 benchmark run 自动晋升。
