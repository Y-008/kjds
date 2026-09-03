# ADR-0102 — Harness Graph TeamAgent 编排韧性与只读控制快照

| 元数据 | 值 |
|---|---|
| status | Accepted for implementation (provider-neutral, no new runtime dependency) |
| date | 2026-08-19 |
| task | Harness Graph / AI-native 多 TeamAgent、多 Subagent、多线程持续迭代 |
| affects | TeamAgent 编排、只读控制快照、前沿采用边界、恢复投影 |
| decision owner | 项目总控 |
| implementation owner | Agent Platform + Control Plane |

## 背景

仓库里已经有可用的控制底座：`GlobalPortfolioOrchestrator` 负责全球专家编排投影，
`LoopEngineeringService` 负责 loop / evolution 合同校验，`TeamControlTower` 负责老板视角
的经营摘要，`AgentHarnessService` 负责 Harness Graph 的工作区快照与证据投影。

当前问题不是“缺少一个更大的平台”，而是缺少一个不会改变业务真源的隔离编排层：

- 需要支持多个 TeamAgent、多个 Subagent、多个线程并发迭代；
- 需要租约、心跳、退避、熔断、checkpoint / restore 和事件游标；
- 需要把跨会话同步、去重、断点续接和冲突归类收进同一控制面；
- 需要复用既有 Harness、TeamControlTower、OperatingTask/Event、Evidence 和 ExactScope 合同，
  本切片不修改 `runtime.py`、Agent Control Router、Alembic、PostgreSQL 业务真源或任何外部权限；
- 需要避免 Temporal、MCP Tasks、A2A、GraphRAG 直接成为运行时权威。

这意味着本切片应该落在“进程内组合层”，而不是新增第二个调度真源。

## 决策

1. 采用进程内、确定性、只读优先的 TeamAgent 编排内核。
2. 编排层只负责任务状态、租约、退避、熔断、事件游标、checkpoint / restore 和安全快照，
   不负责 Provider 调用，不负责 sleep，不负责数据库写入，不负责外部写。
3. 任务状态允许从 `queued` 进入 `running`，再进入 `completed / failed / retry_wait / blocked / paused / expired`。
4. 同一幂等键且请求完全一致时返回原任务；同一幂等键但请求内容变化时返回明确冲突。
5. 自依赖统一视为 dependency cycle；跨线程 barrier、scope 漂移、哈希冲突和合同版本漂移统一
   进入 `conflict`。
6. 429 / 5xx / timeout 按 retry contract 处理：最多三次尝试，指数退避，优先尊重合法
   `Retry-After`，同一 provider/session 连续失败三次后熔断，半开只允许一个探测。
7. 多会话、多线程同步通过按 `session_ref` 独立成链的 append-only 控制事件、游标和 checkpoint
   完成；任一会话的 sequence/hash/cursor 不得与另一会话串联。控制事件的可信边界仅限于校验
   进程内恢复投影的连续性、重复消费和冲突；完整状态恢复以通过校验的 checkpoint 为基线，事件流
   本身不承诺从空进程重建 session/thread/task，更不晋升为第二业务真相。
8. 资源治理以 session 并行度、单 Agent 活跃数、provider bucket、成本预算和时间预算为边界。
9. 需要 Evidence 的任务不得空 Evidence 完成；独立复核角色不得与作者相同；结果必须递归拒绝
   `permit / fact / finance_entry / approval / external_write` 及敏感字段。
10. 采用只读控制脚本编译当前执行队列，汇总 `GlobalPortfolioOrchestrator`、
    `LoopEngineeringService` 和 Harness 快照，但脚本本身不执行业务写。
11. 如果未来独立接入 Agent Control API，则每个 mutation/publish 必须重新读取 current scope
    authority 并与 session 冻结的 entity/authority hash 比对；请求中的 `worker_id` 必须等于
    authenticated actor，`monitor` 不得创建、领取、完成、失败、暂停、恢复或解除 Kill Switch。
    这些是后续接入门槛，不是本切片已交付的 API 能力。
12. complete/fail/heartbeat 必须复验 lease 仍存在且为 active，并同时匹配 task/session/thread/worker
    和有效期；checkpoint restore 必须验证 session/thread/task/dependency/lease/observation/handoff
    引用完整性。
13. 本切片不自建外部 exact-scope resolver 或 reviewer registry；production completion 通过
    版本化 `team-agent-reviewer-appointment@1` authority seam 接收 server-verified appointment
    attestation。默认 runtime 注入 unavailable authority，因此 caller-asserted、task-persisted
    或 reviewer-role-required `reviewer_id` 仍在 mutation 前返回稳定 409。只有注入的 attestation
    同时匹配 exact scope、session/task、reviewer role、authenticated actor separation、当前
    authority hash，并带不可变 appointment evidence ref 时才可完成；该 evidence ref 会并入
    completion evidence。进程内 Coordinator 的 reviewer 字段仍仅用于确定性 Pilot/replay 合同。

## 备选方案

### 方案 1：进程内组合层

采用现有控制对象的只读快照、状态机和事件投影，在应用层补齐租约、退避、熔断和恢复语义。

- 优点：不改 runtime、不新增外部依赖、不制造第二真源，最适合当前 BAS-223 写域仍被占用的阶段。
- 缺点：并发上限、恢复语义和事件一致性需要自己维护。

### 方案 2：PostgreSQL 持久化调度

把租约、心跳、事件游标和恢复状态都推到数据库。

- 优点：更适合跨进程恢复和强一致唯一性。
- 缺点：会牵涉迁移、锁语义、表设计和新的运维面；当前切片不需要先承担这个成本。

### 方案 3：Temporal、MCP Tasks、A2A、GraphRAG 作为运行时权威

直接把外部协议或平台升级为编排真源。

- 优点：表面上可获得成熟的长任务、任务协议或知识图能力。
- 缺点：会立即引入第二调度抽象、版本漂移、跨系统权威冲突和更高的集成成本。

当前不采用方案 2 和方案 3。它们可以继续作为观察、pilot 或 watch 的候选，但不能覆盖
KJDS 自己的任务、Evidence 和控制边界。

## 后果

### 正面

- 现有控制对象可以继续作为系统真源，不需要重建平台。
- 任务失败、限流、暂停、过期和重入可以被确定性地恢复和审计。
- 控制快照可以直接服务总控、回放和人工复核。
- 未来若需要 PostgreSQL 持久调度，可以把当前进程内合同作为最小兼容层。

### 负面

- 进程内恢复不是跨进程调度总线，不能假装等于平台级工作流引擎。
- 如果后续需要更强一致的跨进程唯一约束，仍要补数据库或调度后端。
- 只读快照不会自动解决 D10 的真实经营阻塞，也不会替代 BAS-223 的工程写域。

## 实施边界

- 本切片不修改 `runtime.py`，不装配常驻 worker，也不增加第二业务真源。
- 本切片不新增 API / OpenAPI 路由。未来若独立集成，Agent Control Router 必须先复验当前
  exact-scope authority，且只能把注册 verifier 的终态 Observation 投影到 Harness。
- 不新增 Alembic 迁移。
- 不引入 PostgreSQL 新表。
- 不引入 Temporal、MCP Tasks、A2A、GraphRAG 运行时依赖。
- 不授予任何外部写、Permit、Fact、Approval 或 FinanceEntry 权威。

### 并行工作树归属

同一工作树中可能并行出现 TeamAgent 相关的 `runtime.py` 接线、Agent Control Router、OpenAPI、
`MASTER_SPEC`、Alembic migration、PostgreSQL persistence/checkpoint store 或后续 ADR。它们不属于
ADR-0102 本切片的交付或验收证据，也不会因被本 ADR 引用而获得采用批准。保留这些并行资产不等于
本切片修改了写域；其合并、发布与数据库验收必须由独立任务、独立 ADR 和对应写域所有者另行批准。

## 预期落地接口

- `TeamAgentCoordinator.claim_task(...)`
- `TeamAgentCoordinator.heartbeat_task(...)`
- `TeamAgentCoordinator.release_task(...)`
- `TeamAgentCoordinator.tick(...)`
- `TeamAgentCoordinator.checkpoint(...)`
- `TeamAgentCoordinator.restore(...)`
- `ControlEvent` append-only 游标和 `merge_events(...)`
- `TeamAgentHarnessBridge.publish_completed(...)`（仅进程内适配器合同，不表示已装配到 runtime/API）
- 只读控制脚本 `scripts/compile_teamagent_control_snapshot.py`

上述接口仅指本切片实际交付的进程内 Python 合同；API、Web、迁移和 PostgreSQL 发布验收均不在范围内。

## 2026-08-19 合同加固补充

- 公共 dataclass 返回值统一经过 defensive-copy 边界；`result`、`acceptance_contract`、`provider_buckets`、handoff 映射不能反向修改 canonical projection。
- `fork_thread` 与 `submit_task` 的默认时间是实际 UTC 调用时刻；测试 fixture 必须显式传同一 T0，不能通过生产时间回退放宽事件链保护。
- 预领取时间预算耗尽必须追加可重放的 `task.time_budget_exhausted` 事件与 `task.blocked` Observation；租约/预算终态的 blocked Observation 必须进入 Harness Observation-only 发布集合。
- `merge_events` 的单 cursor 合同只接受一个 incoming `session_ref`；多 session checkpoint replay 按 session 串行分批，外部混合批次失败关闭且不返回 cursor。
- Harness publish 幂等域绑定 observation、project、exact tenant/entity/store/authority scope 与 principal identity，缓存命中只适用于同一授权域。

这些补充仍属于进程内控制合同，不改变 runtime/API 装配边界，也不关闭 0099/0100 reconcile、跨进程生产调度或多副本灾备 Gate。

## 当前能力与未完成边界

- 同一控制平面进程内可运行多个 session、每个 session 多个 thread、多个 TeamAgent/Subagent，
  并以 session 并行度、单 Agent 活跃数、provider bucket、依赖屏障和任务租约限流。
- checkpoint/restore 只能恢复通过完整性校验的进程内合同状态；事件流只校验 checkpoint 之后的
  进程内延续、重复与冲突，不是业务真相，也不是从空进程进行完整 hydration 的承诺。
- 本切片没有接入 PostgreSQL migration、唯一约束、抢占锁、runtime 或 API，因此不宣称跨进程、
  多副本或生产强一致调度已经完成。工作树中的 ADR-0103、0099/0100 migration 和 persistence
  文件属于并行候选工作，不是 ADR-0102 的交付证明。
- 真实 durable reviewer appointment registry 尚未实现；当前仅有 fail-closed 的版本化 authority
  seam 与可注入 attestation 校验。本地 scope/reviewer 字段不能单独证明当前权限或独立复核者
  注册状态。
- Harness 发布只能使用固定 `team-agent-terminal-observation@1` verifier；其 source type 必须是
  `team_agent_terminal_observation`、authority 必须是 `observation`，并且 exact tenant/entity/store、
  `observation_only=true`、`gate_eligible=false` 全部匹配，否则失败关闭。
- 编排测试、Harness Observation 或历史 checkpoint 不是 Ozon 当前事实、自然订单、平台回读、
  银行到账、realFBS 准入或客户交付 Evidence。

## 相关证据

- `docs/project/evidence/20260819_HARNESS_GRAPH_FRONTIER_REVIEW.md`
- `scripts/compile_teamagent_control_snapshot.py`
- `docs/project/registries/frontier_technology_adoption.json`
- `docs/adr/ADR-0103-teamagent-postgresql-persistence-cas.md`（并行候选，非本切片验收）

## 2026-08-19 当前共享树状态补充

本 ADR 的原始“仅进程内、不接 runtime”边界保留为历史决策记录。当前共享树已增加条件式
`PostgresTeamAgentRuntime` composition、0099/0100 exact-session reconcile、持久化 handoff/
control/task mutation 与 Harness scoped publication 合同；非 PostgreSQL composition 仍使用
进程内 Pilot。该补充不改变原有 observation-only、exact-scope、BAS-177 fail-closed 边界。

当前交互 shell 的 Docker API 仍权限拒绝且 5432 无监听；但共享树保留并已复核一份
run-owned PostgreSQL 17 disposable receipt：38 个 PostgreSQL contracts 全部通过（0 failure/
error/skip），并执行 spawned-worker process-loss recovery。194 个非 PostgreSQL/Harness-focused
contracts 也已通过，且 durable runtime 的 session/task/snapshot/observation 读取已禁止裸全局 ID、
强制 exact scope + authority。该证据只关闭 disposable local contract Gate；双进程部署级
failover、长时序列化/恢复、跨副本 publish 去重与生产 cross-process Gate 仍为 `NOT PASSED`，
不得把隔离 receipt 宣传为生产完成。

## 2026-08-20 independent hidden-boundary audit

- Harness bridge 的进程内 cache 不再作为授权结果：每次 terminal replay 都必须重新调用
  sink，复验当前 project/verifier/principal 权限；sink 的 canonical 回读若与首次结果漂移则
  失败关闭，权限撤销不得返回缓存假成功。
- TeamAgent Harness durable observation identity/result digest 同时绑定 project、完整 exact
  scope（tenant/entity/store/authority/session/task）和 principal identity。Graph project 的
  entity/store 必须非空并精确匹配，scope 字段集合与 authority SHA-256 必须闭合有效。
- 0100 内存 checkpoint record 与 `ControlEvent` 对象输入的可变嵌套映射均在公共边界深拷贝；
  caller 不能通过 frozen dataclass 内的 dict 反向修改 canonical checkpoint 或事件链。
- release/fail 与 complete/heartbeat 一样，在 lease deadline 和 time-budget deadline 重合时
  先形成 `time_budget_exhausted` BLOCKED 终态、事件与 Observation，再返回 mutation 错误。

这些修复强化本地安全与一致性合同，不改变 Observation-only 边界，也不代表部署级
multi-replica/failover 或生产 cross-process Gate 已完成；本轮
`frontier_review=not_required`。

## 2026-08-20 latest hidden-boundary verification correction

The pre-claim session/task time-budget path now records a replayable
`task.time_budget_exhausted` event and `task.blocked` Observation before raising
the caller error; checkpoint restore reproduces the BLOCKED projection. Event
merge batches spanning multiple sessions fail closed with no cursor, and all
public nested dataclass exports remain detached copies. The latest no-database
TeamAgent/Harness focused collection is `196 passed, 42 skipped`; the skips are
PostgreSQL-only. A current-head PostgreSQL 17.10 run separately returned `42
passed, 0 failures, 0 errors, 0 skipped` (see the 20260820 Evidence receipt).
These are local contracts only; durable appointment registry, terminal publish
liveness, multi-replica failover and production cross-process acceptance remain
open.
