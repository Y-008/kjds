# BAS-177 受治理 Team Agent 演进 Evidence

## 1. 结论

BAS-177 建立了一个 exact-scope、append-only、Evidence-backed 的 Team Agent / Skill 生命周期深模块。它只治理候选版本及其评测、Shadow、独立复核、晋级、回滚和退役记录，不安装运行时代码、不修改权限、不生成经营事实，也不执行外部写。

- 唯一服务边界：`GovernedTeamAgentEvolutionWorkspace`。
- 唯一机器合同：`kjds-governed-team-agent-evolution-v1`。
- 状态序列：`observation -> skill_candidate -> evaluation -> shadow -> independent_review -> promoted -> active`；各中间态可按冻结规则进入 `rolled_back`，终态只允许进入 `retired`。
- `promoted` / `active` 只是治理状态，不等于部署或经营启用。
- canonical Graph 只形成 `Observation` 投影；`graph_gate_eligible=false`。
- 不增加公共 API、OpenAPI、runtime 聚合或新依赖。
- 不生成 Fact、FinanceEntry、Approval、Permit、Pilot、Outbox 或外部连接器写入。

## 2. 冻结 Eval Set

文件：`tests/fixtures/team_agent_evolution/bas177_eval_set_v1.json`

| 字段 | 冻结值 |
|---|---|
| contract | `kjds-team-agent-frozen-eval-set-v1` |
| id/version | `bas177-skill-candidate-eval` / `1.0.0` |
| cases | 5 |
| categories | quality、negative_scope、security、cost、latency |
| content SHA256 | `9d977e24c114c9383bafe1d550a00d7de0bb7e03746ff8a0ffb412686bfecf7e` |
| classification | `repo_owned_synthetic` |
| customer/cross-tenant data | `false` / `false` |

Loader 对顶层 schema、许可、case schema、case/input 唯一性、类别、状态、hard gate、逐项 SHA 和集合 SHA 执行 fail-closed；fixture 禁止 tenant、store、customer、Prompt、输入/输出正文、工具参数、Provider ID、secret、token、credential 等字段。

## 3. exact-scope 与时间边界

每次 create/get/list/transition/replay 均使用服务端可信 UTC clock 重新调用 `ScopeGrantAuthority.current`，冻结：

`tenant_ref + entity_ref + store_ref + scope_authority_sha256`

调用方 `as_of` 仅作为 Evidence/候选历史的数据截止，不可回绕已轮换或撤销的当前权限。候选、事件、Evidence link 的查询、幂等唯一键、复合外键和投影均绑定 current authority。authority 轮换后旧候选统一不可枚举；同一 idempotency key 在新 authority 下不会命中旧 winner。并发幂等冲突的 winner replay 会在新事务中重新取得 scope advisory lock、重验 current authority，并使用该次重验返回的最新 `checked_at`/scope 投影 winner；锁外发生的 authority rotation 或 revocation epoch 变化不会借旧 scope 返回 winner。

Supporting Evidence 同时验证：blob 实际 SHA、purpose-specific Grade A/B、专用 authority contract、source/ref、purpose、canonical claims、exact scope、`effective_at <= as_of`、`recorded_at <= as_of` 和 current expiry。保留 source 只能由 `TeamAgentEvidenceAuthorityAdapter` 或内部事件审计接口签发，通用 `EvidenceService.capture` 不接受这些 source/contract。跨租户模式额外要求 license、不可逆 deidentification、revocation 三项绑定同一 subject 与同一正整数 epoch，并且每次读取/重放都按可信当前时钟复核最新 epoch；新 revocation 出现后，旧历史不可借 `as_of` 回绕恢复可见。三类 authority Evidence 的 INSERT 与候选 mutation 使用同一个 exact scope + subject advisory lock；mutation 取得锁后刷新可信时间并重新验证 current/latest/revoked，消除预检到提交之间的撤销窗口。

## 4. 生命周期与职责分离

| 目标状态 | 必要 Evidence | 独立职责 |
|---|---|---|
| `skill_candidate` | AgentRun、冻结 Eval Set、Rollback | author 与 human owner 不同 |
| `evaluation` | AgentRun、Eval Set、Baseline | evaluator 不得为 author/owner |
| `shadow` | AgentRun、Baseline、Shadow | shadow operator 不得为 author/owner/evaluator；零外写 |
| `independent_review` | Review、Shadow | reviewer 不得为 author/owner/evaluator/shadow actor |
| `promoted` | Baseline、Shadow、Review、Risk | promoter 不得为 author/owner/evaluator/shadow/reviewer/risk actor |
| `active` | Baseline、Shadow、Review、Risk | 仅 human owner 执行，risk actor 必须独立且 current |
| `rolled_back` | Rollback | human owner 或独立 risk/compliance |
| `retired` | Retirement | human owner 或独立 risk/compliance |

Eval、negative、scope 和 shadow Gate 由 Evidence canonical claims 投影，调用者的布尔值必须逐项一致。Review Evidence 的签名者必须等于实际 independent-review 事件 actor，晋级/激活时继续绑定该历史 reviewer；Risk Evidence 签名者与 author、owner、evaluator、shadow reviewer、independent reviewer、promoter 分离。上述关系由服务和数据库共同执行。cost、latency、tokens 必须有限且非负；任何 `external_write_observed=true` 在服务和数据库两层拒绝。

rolled-back/retired 候选不可在同一事件链重新进入 `skill_candidate`。新版本必须创建新的候选，绑定 terminal predecessor、旧 content SHA 和 canonical `major.minor.patch` 版本；successor 版本必须严格高于 predecessor。数据库保证每个 predecessor 只有一个 exact-scope successor。

## 5. PostgreSQL 0094

迁移 `20260803_0094` 新增：

1. `team_agent_evolution_candidates`：不可变候选合同、版本链、exact-scope 幂等和单一 successor。
2. `team_agent_evolution_events`：append-only 状态/hash 链、冻结 Eval/Baseline/Runtime/AgentRun/Review/Risk/Rollback/Graph 快照、DB 自动 `insert_xid`。
3. `team_agent_evolution_evidence_links`：事件与 Evidence 的 exact-scope、id/hash/source/ref/grade/effective-at 复合绑定。

数据库触发器执行：

- 候选/事件/link、专用事件审计 Evidence 及十类 TeamAgent authority Evidence 的 UPDATE/DELETE 拒绝；
- 初始事件、合法 transition、ordinal、prev hash、冻结合同和职责分离校验；
- event 与全部 link 必须在同一 PostgreSQL transaction/XID 写入，后续补链拒绝；
- 每个 event 恰好一个 Grade D 专用审计 Evidence，并恰好包含该状态要求的 purpose-specific Grade A/B supporting Evidence；
- event 冻结 `data_as_of` 并纳入事件 hash；数据库和读取路径按 event、candidate、完整 supporting snapshot 与 predecessor 重建 canonical audit receipt，任一字段或额外字段漂移均拒绝；
- 数据库解析内容寻址 Evidence 的 canonical JSON，逐项绑定 AgentRun/Eval/Baseline/Shadow/Review/Risk/Rollback 与事件字段，任意无关高等级 Evidence 均不可替代目标声明；
- Graph 始终 observation-only；风险/成本/延迟/Token、包括初始事件在内的跨租户同 subject/epoch/current/latest Gate 与 authority 事务锁全部 fail-closed；
- downgrade 先按固定顺序取得 `ACCESS EXCLUSIVE` lock；任一新表、专用 Evidence 或相关 lineage 非空即中止，空库可 0093↔0094 重放。

## 6. Graph 与输出守恒

Graph projection 只返回版本化 `AgentRole`、`SkillVersion`、`EvalSetVersion`、`ModelProfileVersion`、`ToolContractVersion`、`PolicyVersion`、Evidence/Outcome/FailurePattern Observation，以及 `derived_from`、`evaluated_by`、`shadowed_against`、`reviewed_by`、`supersedes`、`rolled_back_to`、`supported_by`、`invalidated_by` 等观察边。

每个事件冻结 Graph snapshot/type/version/effective interval，要求 observation-only=true、gate-eligible=false；模块不调用 canonical Graph writer。服务输出固定：

- `runtime_activation_performed=false`
- `formal_fact_created=false`
- `finance_entry_created=false`
- `approval_created=false`
- `permit_created=false`
- `pilot_created=false`
- `outbox_created=false`
- `external_write_performed=false`

## 7. 验证矩阵

| Gate | 覆盖 |
|---|---|
| Eval fixture | schema/hash/license/唯一性/敏感字段/硬门 |
| Scope/time | current authority、data as-of、rotation 后零可见、Evidence hindsight/expiry |
| Lifecycle | 全正向链、跳态、终态回流、expected-state、hash/ordinal |
| SoD | author/owner/evaluator/shadow/reviewer/promoter/risk actor 分离 |
| Evidence | blob integrity、Grade、source/ref/purpose/claims、复合 FK、同事务、数量守恒 |
| Numeric/privacy | NaN/Infinity/负值、零外写、正文/secret 不落账 |
| Idempotency | 8 并发同请求单 winner、drift conflict、authority 精确隔离 |
| Persistence | ORM/DDL 列一致、append-only、late link、downgrade fail-closed、空库 replay |
| Graph | observation-only、零 canonical write、零业务晋升 |

当前 literal result：

- TeamAgent 单元/metadata 隔离：`15 passed in 2.37s`；Loop registry/service：`11 passed in 0.08s`；Evidence 隔离：`14 passed in 0.44s`。
- 隔离 PostgreSQL（含首次绑定、等价重放、内容漂移、跨 scope、rollback 目标快照、successor 单调版本、跨租户最新 epoch/并发撤销、初始 subject/epoch 守恒、完整 audit receipt 漂移、authority/review/risk signer SoD、无关 Evidence、并发、0093↔0094 replay）：`31 passed, 12 warnings in 63.44s`。
- 完整后端：`1717 passed, 63 skipped, 35 warnings in 93.34s`。
- target Ruff 与全仓 Ruff：`All checks passed!`。
- secret scan：`1315 non-ignored worktree files and 1304 historical paths checked`。
- `git diff --check` 与 `git diff --cached --check`：exit `0`。
- Alembic：唯一 head `20260803_0094`。

最终 G1 由总控在功能提交与租约释放后的最终 HEAD 独立重跑；本 Gate 不代替最终 G1。

## 8. Entry / Exit / Rollback

Entry：BAS-172 AgentRun Evidence 与 BAS-173 causal/temporal retrieval benchmark 已完成；BAS-177 机器租约持有 migration 0094，API/OpenAPI/shared plan 均不在写集。

Exit：Eval Set hash 冻结；全生命周期 Evidence/SoD/authority/append-only/rollback 合同通过；PostgreSQL 空库 replay 和有数据 downgrade fail-closed；独立红队 P0/P1=0；完整门禁通过。

Rollback：保留数据库数据时 0094 主动拒绝 downgrade；应先导出并验证 Evidence/lineage，再按治理流程清理。空库可 downgrade 到 0093。代码回退为移除 Team Agent evolution module、0094、两组测试、fixture 和本 Evidence 文档，并回退 loop/evidence registry 增量；没有外部系统写入需要补偿。

## 9. 保持 UNKNOWN

- 真实客户数据上的质量、成本与延迟分布；
- 生产 P95/P99、数据库容量和人工复核耗时；
- 正式晋级阈值及签署人；
- 某个 candidate 在真实经营环境中的因果 uplift；
- 跨租户模式的真实许可、不可逆性证明与撤销状态；
- runtime deployment、权限扩展和外部执行效果。

这些 UNKNOWN 不由 synthetic fixture、单次测试或模型叙述自动晋升。
