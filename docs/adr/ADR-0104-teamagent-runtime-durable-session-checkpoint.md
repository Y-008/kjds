# ADR-0104 — TeamAgent runtime durable session checkpoint sidecar 与 0099 lease/CAS 接线

## 2026-08-20 current-head all-42 PostgreSQL rerun

The current 42 PostgreSQL contracts passed on the sole Alembic head
`20260820_0103` (`42/0/0/0`), including complete/fail response-loss replay:
identical requests return the committed terminal projection without a new
revision or event, while drift requests return `409 idempotency_conflict`.
Credential-free artifacts are retained under
`D:\KJDS\kjds\.runtime\team-agent-pg17-terminal-final2\`; JUnit SHA-256 is
`f9f8015e3be74f00dc25e413d657fa6eed87d8dfaec660408f08f59b9a4eb982` and the
required recovery manifest SHA-256 is
`eec27cf9677aa82cb02e79fa8a39c262e24c817d8ddcdb603bbb3e6433de71c9`.
Complete/fail terminal transitions now stage an observation-only transactional
outbox intent on the same PostgreSQL connection. A publisher can claim that
intent and replay `TeamAgentHarnessBridge.publish_completed`; sink authorization
and idempotency remain authoritative. Release/expiry-generated blocked terminals
and an always-on worker are still open, so this is not yet a full liveness SLO.
The production `RuntimeServices.agent_team_terminal_outbox_factory` exposes the
publisher only when the durable PostgreSQL facade is selected.

## 2026-08-20 current-head all-40 PostgreSQL rerun (historical)

After migration `20260820_0103` added a durable paused-retry schedule, a new
run-owned PostgreSQL 17 container migrated to the sole current head and completed
the current set with `40 passed, 0 failures, 0 errors, 0 skipped`; the exact
disposable container was removed after verification.
Credential-free artifacts are retained under
`D:\KJDS\kjds\.runtime\team-agent-pg17-gate-0103-final\` (JUnit SHA-256
`c6c65a385cc60167efa6e036c50bfc5975a322e278f3a6be3ba32e72b3516287`). This
closes only the local persistence/checkpoint contract Gate; deployment-level
multi-replica recovery, SLO/RPO/RTO, and production cross-process orchestration
remain `NOT PASSED`.

| 元数据 | 值 |
|---|---|
| status | Accepted; local disposable PostgreSQL Gate PASSED, deployment multi-instance Gate NOT PASSED |
| date | 2026-08-19 |
| requirement | BR-150 follow-up, BAS-177 guarded TeamAgent evolution contract |
| affects | TeamAgent runtime wiring、restart hydration、session checkpoint、0099 durable seam、authority replay |
| predecessor | ADR-0102, ADR-0103 |
| affected gate | BR-150 local durable contract Gate PASSED; deployed multi-replica recovery/SLO Gate remains NOT PASSED |
| authority boundary | exact-scope authority hash remains server-owned and fail-closed |
| frontier review | `durable_workflow_adapter=pilot`, `mcp_tasks_durable_protocol=watch`, `a2a_cross_agent_interoperability=watch`, `frontier_review=checked_no_change` |

## 背景

ADR-0102 交付了进程内 `TeamAgentCoordinator`，覆盖 session、thread、task、dependency、
handoff、circuit breaker、observation、control event、checkpoint / restore 等完整控制合同。
ADR-0103 交付了 `TeamAgentPersistence` 与 `20260819_0099` migration，覆盖 exact scope 下的
task 注册、claim、heartbeat、release、revision 与 transition event 的事务 CAS。

`MASTER_SPEC` 中的 BR-150 已明确：

- `TeamAgentCoordinator` 目前是单进程 Pilot；
- `0099` 已交付 task/lease/event 持久化、事务 CAS 和真实 PostgreSQL 双 Worker 唯一 claim；
- runtime 尚未接线，完整 `session/thread/handoff/circuit-breaker`、restart hydration 与多副本灾备演练仍未完成；
- 在完整 runtime 接线与多副本恢复演练完成前，不得宣称跨进程生产编排。

`MASTER_SPEC` 中的 BAS-177 进一步要求 TeamAgent 演化合同始终保持 observation-only、source-hashed、
fail-closed，且 runtime Agent 不能自修改 authority、Fact、Approval、Permit 或 external-write policy。
因此 runtime durable 接线必须把 authority replay 与恢复校验当作一等约束，而不是只把 lease 落库。

作出本决策时，两者仍是分离切片；这些条目保留为设计动因，当前实现状态见文末更新：

- `runtime.py` 仍直接装配进程内 `TeamAgentCoordinator()`，尚未装配 `PostgresTeamAgentPersistence`；
- `0099` durable seam 目前只持久化 task + lease/CAS + append-only transition event；
- 协调器 checkpoint/restore 需要 `sessions / threads / tasks / leases / observations / events / handoffs / idempotency / circuit_breakers / conflicts`；
- `0099` durable checkpoint 目前只投影 `scope / session_ref / tasks / events`，不能直接恢复完整 coordinator；
- 控制事件链中的 `cursor / previous_hash / event_hash` 与 session 级 `authority_sha256` 目前只在协调器内存合同中完整存在。

因此，下一步 runtime durable 接线不能把 `0099` 直接当作完整编排真相库；否则会丢失 restart hydration、
handoff / dependency / observation / circuit breaker、current authority 以及 fail-closed 校验能力。

## Gate 与 authority 边界

- 受影响 requirement：`BR-150`。
- 受影响 Gate：TeamAgent runtime wiring gate、restart hydration gate、多实例恢复 gate。
- 受影响 authority：`ExactScope + authority_sha256 + authenticated actor(worker_id)`。
- Gate 当前状态：仍为 `NOT PASSED`。仅有 `0099` 的 task/lease/event CAS 验收通过，不等于 runtime durable
  orchestration 验收通过。
- 失败关闭规则：authority hash 漂移、session checkpoint hash 漂移、control event hash/cursor 漂移、
  stale lease、cross-session 引用、坏 reconcile 全部阻断恢复与 mutation，不允许静默自修复。

## 决策

1. `20260819_0099` durable seam 继续作为 TeamAgent **task lease/CAS 真相源**。
   它负责 exact scope 下的 task 身份、idempotency、唯一 claim、lease 续期、lease 释放、
   revision 单调递增和 append-only transition event。
2. 新增 **session checkpoint sidecar** 作为 TeamAgent runtime 的 durable 恢复载体。
   Sidecar 持久化的是单个 `session_ref` 的完整 coordinator checkpoint，而不是把全部运行时语义压缩进
   `0099` task/event 行。
3. runtime durable 接线采用 **按 session 串行事务** 的顺序：
   先锁定 session checkpoint sidecar，再恢复 coordinator，再执行一次受控 mutation，
   同事务内调用 `0099` durable task mutation，最后回写新的 session checkpoint 与链式校验字段。
4. restart hydration 必须先从 session checkpoint sidecar 恢复，再用 `0099` durable task/event
   做 reconcile；任一 authority、cursor、event hash、revision 或 lease 状态不一致时失败关闭。
5. 在 session checkpoint sidecar 与完整 reconcile 落地前，不宣称 TeamAgent runtime 已具备
   多实例 durable orchestration、完整 restart safety 或生产级跨进程恢复能力。

## 设计边界

### `0099` durable seam 负责什么

- exact scope + session + task 复合身份；
- 同 scope/session 的 idempotency key 唯一；
- `claim / heartbeat / release` 的事务 CAS；
- lease 唯一性、attempt budget、revision 单调递增；
- append-only transition event；
- 双实例/双 worker 对同一 task 的唯一 claim winner。

### session checkpoint sidecar 负责什么

- 单个 `session_ref` 的完整 `TeamAgentCoordinator.checkpoint(...)` durable blob；
- `checkpoint_sha256`；
- `authority_sha256`；
- 最近控制事件的 `last_control_cursor` 与 `last_control_event_hash`；
- sidecar 自身的 revision / compare-and-swap；
- `updated_at`、恢复来源和 reconcile 结果。

### 当前明确不由 `0099` 单独承担的内容

- 完整 `session / thread / dependency / handoff / circuit breaker / observation` 图恢复；
- coordinator control event 链的 `cursor / previous_hash / event_hash` 真相；
- Harness Observation publish 去重状态；
- session 级 current authority 绑定；
- 跨 task 的一致性恢复与 fail-closed checkpoint 校验。

## 与 defer / no-action 的对比

### 方案 A：session checkpoint sidecar + `0099` lease/CAS

- 保留 `0099` 作为单任务并发真相；
- 保留 coordinator checkpoint 作为完整 session 恢复合同；
- 满足 BR-150 对 authority hash、restart hydration 和多实例恢复验收的前置结构。

### 方案 B：defer，仅保留 ADR-0102 + ADR-0103 现状

- 优点：当下零新增 runtime wiring 工作。
- 缺点：继续停留在“内存控制面 + 独立 durable seam 未接线”的分裂状态；
  `runtime.py` 仍不能在崩溃/重启后安全恢复 session 级控制状态；
  BR-150 的 runtime durable gate 继续无法关闭。

### 方案 C：no-action，只把 `0099` 当完整真相

- 表面上改动最小；
- 实际会丢失 `thread / dependency / handoff / circuit breaker / observation / authority replay`
  等 runtime 语义，并把 restart reconcile 变成不可验证的隐式行为；
- 与 BR-150、BAS-177 的 fail-closed 与 authority boundary 冲突，因此不采用。

## 接线顺序

1. 为单个 `session_ref` 读取并锁定 session checkpoint sidecar。
2. 校验 sidecar `checkpoint_sha256`、`authority_sha256`、`last_control_cursor`、
   `last_control_event_hash` 与请求上下文。
3. 从 sidecar blob 执行 `TeamAgentCoordinator.restore(...)`，恢复完整进程内控制状态。
4. 依据即将执行的 mutation 类型，对应调用 `TeamAgentPersistence`：
   `register / claim / heartbeat / release`，以及后续补齐的 terminal transition 能力。
5. 把 durable mutation 的结果投影回 coordinator，并刷新 session 内的 control event 链、
   observations、handoffs、breaker、idempotency 与 checkpoint。
6. 重新计算 sidecar `checkpoint_sha256`，写回新的 `last_control_cursor`、
   `last_control_event_hash`、`authority_sha256` 和 sidecar revision。
7. 事务提交后，runtime 才能对外宣布本次 mutation 成功。

这个顺序故意以 session 为串行边界，优先保证恢复正确性与 fail-closed 语义，而不是先追求更细粒度的
跨 task 并发写入。

## Restart reconcile 规则

restart 后恢复某个 session 时，必须执行以下 reconcile：

- sidecar checkpoint hash 必须匹配；
- sidecar `authority_sha256` 必须等于当前 runtime 允许装配的 authority；
- sidecar `last_control_cursor` / `last_control_event_hash` 必须与恢复出的控制事件链尾部一致；
- `0099` durable task 的 `task_ref / state / revision / lease_ref / claimed_by / lease_expires_at`
  必须与 sidecar checkpoint 中对应任务一致；
- 若 `0099` 中 lease 已过期而 sidecar 仍显示 `running`，恢复后必须立即执行 `tick()` 并将其转入
  `expired` 或 `blocked`，不能继续当作活动租约；
- 若 sidecar 含有 task / thread / handoff / dependency / breaker / observation，但 `0099`
  durable 任务集合已经无法支撑该引用关系，则恢复失败关闭；
- 若发现 event hash、cursor、authority 或 revision 漂移，拒绝自动修复，等待显式人工处理或
  受控补偿逻辑。

## 测试要求

以下测试在 runtime durable 接线完成前都属于必须门槛：

- 双实例端到端唯一 claim：两个 runtime 实例并发 claim 同一 task，只允许一个 durable winner。
- stale lease 竞争：旧 owner 在 lease 失效并被新 owner 回收后，heartbeat / release / complete
  必须 CAS 失败。
- restart hydration：覆盖 `queued`、`running(active lease)`、`running(expired lease)`、
  `retry_wait`、`blocked`、`completed`、`failed`、`paused`、`kill_switch_engaged`。
- authority 漂移：`authority_sha256` 变化时 restore 或 mutation 必须失败关闭。
- event chain 漂移：`last_control_cursor`、`last_control_event_hash`、checkpoint hash 任一不匹配时，
  restore 必须失败关闭。
- reconcile 完整性：dependency barrier、handoff lineage、circuit breaker half-open 状态、
  observation scope 与 idempotency slot 在恢复后必须保持一致。
- terminal round-trip：后续补齐 `complete / fail / retry / kill` durable transition 后，
  reviewer、evidence、failure metadata、retry_at、blocked_reason 必须可 durable round-trip。
- publish 去重：restart 前后重复执行 terminal observation publish 时，不得生成重复 Harness side effect。

## 后果

### 正面

- 复用 ADR-0103 的 `0099` CAS 真相，不把单任务唯一 claim 退化为整份大 JSON 竞争；
- 复用 ADR-0102 的 coordinator 合同，不丢失 session/thread/handoff/circuit/observation 的恢复能力；
- 为 runtime durable 接线建立单一、可审计、可 fail-closed 的事务顺序；
- 让“双实例唯一 claim”和“完整 session 恢复”各自落在最适合的持久化层。

### 代价与限制

- 会新增一个 session 级 durable sidecar，而不是只靠 `0099` 两张表结束问题；
- 以 session 串行为第一版边界，写入路径的吞吐优先级低于恢复正确性；
- 在 terminal transition、publish 去重和多实例恢复演练补齐前，仍不能对外宣称生产级 durable
  TeamAgent orchestration 已完成。

## 明确未完成边界

- `runtime.py` 已按数据库方言完成装配，但本 ADR 不代表真实 PostgreSQL 17 与多实例恢复 Gate 已通过；
- 本 ADR 不修改 ADR-0100 的平台解冻含义；
- 本 ADR 不把 `0099` 提升为完整 coordinator 图真相；
- 本 ADR 不直接授予 TeamAgent 事实晋升、审批、Permit、FinanceEntry 或任何外部写权限；
- 本 ADR 不要求引入 Temporal、Redis、Kafka、PostgreSQL 18、MCP Tasks、A2A 或第二调度平台。

## 2026-08-19 recovery-only reconcile 状态（历史）

`TeamAgentDurableRecovery` 已实现为一个显式调用的 fail-closed 校验器：它先由 0100 sidecar
恢复 coordinator，再比对 0099 checkpoint 的 task set、revision、request identity、任务投影和活跃
lease；completed 任务还比对 result、evidence refs 和 reviewer。任何漂移都会拒绝恢复。

本段记录第一次只读 reconcile 落地时的状态；随后 runtime wiring 已交付，以下更新为当前权威状态。

## 2026-08-19 runtime wiring 当前状态

- `PostgresTeamAgentRuntime` 已装配到 PostgreSQL runtime composition；非 PostgreSQL 本地/测试 composition 继续使用进程内 Coordinator。
- durable mutation 以 0100 exact-session checkpoint 行锁为 session 串行边界，在同一 caller-owned transaction 内执行 sidecar restore、0099 reconcile、task/event mutation、Coordinator 投影与 checkpoint save。
- `TeamAgentDurableRecovery` 对 PostgreSQL adapter fail-closed：checkpoint 与 task persistence 必须由同一个 caller-owned connection 提供；分离连接的 split snapshot/TOCTOU 不被当作合法恢复路径。
- 当前接口覆盖 create session、fork thread、durable handoff、submit/claim/heartbeat/release/complete/fail、pause/resume、kill-switch engage/release、exact-scope snapshot 与 restart hydration；active claim replay 与相同 handoff payload replay 均不增加对应 checkpoint revision。
- router 在 durable restore 之前解析 current scope authority，并将 exact scope/authority 贯穿读取、控制、task mutation 与 Harness publication。发布桥不再在 admission 后执行全局 session lookup。
- Harness observation 使用确定性 ID 与数据库 replay unique key；并发冲突 loser 通过 savepoint 回读 winner，避免重复 side effect 或把唯一冲突暴露为发布失败。
- PostgreSQL `40001` serialization failure 与 `40P01` deadlock 都证明当前事务已中止，因此映射为结构化 409：`transaction_outcome=rolled_back`、`retryable=true`、`retry_requires_fresh_restore=true`。runtime 不自动重放 mutation；caller 必须先按当前 authority 重新 restore/reconcile。其他 SQLSTATE 原样上抛，不能把连接故障误报为可安全重试。
- Earlier intermediate Harness-focused regression was `184 passed, 33 skipped`（包含精确 budget-capped heartbeat deadline、durable release、空 checkpoint history、shared-connection recovery、same-worker stale lease fence、session-scoped publish cache、budget/lease terminal separation、PERSONAL-value rejection、completed-result defensive-copy 与 PostgreSQL Gate runner 回归）。33 个 skipped 均为需要 `KJDS_TEAM_AGENT_DATABASE_URL` 的 PostgreSQL contracts，其中包含 shared-transaction rollback、active-claim replay、session-control/handoff restart reconcile、expired-lease recovery/exhaustion、dual-runtime terminal convergence、spawned-worker process-loss recovery、stale-replica kill-switch fencing、durable release、空 history、populated downgrade 拒绝与 concurrent publish convergence。
- `scripts/verify_team_agent_postgres_gate.py` 只从环境读取数据库 URL，要求 PostgreSQL 17、隔离 schema 与必要角色能力，执行完整 PostgreSQL 文件并解析 JUnit；任何 failure/error/skip 都不能产生 PASS，回执不包含连接 URL 或密码。

At that historical checkpoint the Gate was `NOT PASSED`：本机 Docker API 返回权限拒绝且 5432 无监听，新增 0099–0102 contracts 尚未在真实 PostgreSQL 17 执行；双进程 restart/failover 与 serialization retry/recovery 也未完成现场演练。source wiring delivered 不等于跨进程生产验证完成。

2026-08-20 follow-up receipt: the focused non-PostgreSQL collection is now
`194 passed`; in addition to rejecting unscoped durable Harness publication,
the durable runtime rejects bare global session/task/snapshot/observation reads
before database I/O and exact-scoped helpers restore the supplied authority.
The final retained PostgreSQL 17 receipt covers all 38 contracts with zero
failures/errors/skips and spawned-worker recovery executed.

2026-08-20 pre-Gate focused receipt (historical): the 14-file focused collection was
`184 passed, 33 skipped`; the PostgreSQL contract file was fully collected but
unexecuted. The Gate runner's five unit contracts included blocked preflight, JUnit
conservation, credential redaction, and PostgreSQL-aborted transaction semantics.

## 2026-08-20 PostgreSQL 17 Gate preflight receipt (historical)

The Gate runner was invoked in this shell with no `KJDS_TEAM_AGENT_DATABASE_URL` and
returned `BLOCKED` (exit code 2): `KJDS_TEAM_AGENT_DATABASE_URL is required`. A second
bounded preflight against an unreachable local endpoint also returned `BLOCKED` without
echoing the URL or password. The 33 PostgreSQL contracts therefore remain collected but
unexecuted; no disposable PostgreSQL 17 database, spawned-worker recovery, or production
cross-process Gate pass is claimed. `business_truth_proven=false` and
`external_write_allowed=false` remain hard boundaries.

## 2026-08-20 pre-PostgreSQL focused rerun (historical)

The explicitly enumerated BR-150 TeamAgent/Harness focused files returned
`199 passed, 38 skipped` before a database was supplied. The 38 skips are all PostgreSQL contracts, so this
does not alter the preflight result above: no PostgreSQL 17 migration,
spawned-worker process-loss recovery, or production cross-process Gate pass is
claimed. Earlier `191 passed`, `185 passed`, `184 passed`, `183 passed` and `182 passed` figures remain historical
receipts from different intermediate trees and are not the current count.

A previously written `PASSED` execution paragraph was not accompanied by a
raw command/JUnit/container receipt and conflicts with the current preflight
file, so it is deliberately not treated as evidence of a completed Gate.

## 2026-08-20 disposable PostgreSQL 17 Gate (historical 37-contract receipt)

A subsequent, reproducible run used a fresh, run-owned
`postgres:17-alpine` container and the authoritative
`scripts/verify_team_agent_postgres_gate.py` runner. It applied migrations
through `20260819_0102` in an isolated schema and returned `37 passed, 0
failures, 0 errors, 0 skipped`; spawned-worker process-loss recovery executed.
The final current-tree run superseded that intermediate capture: it returned
`38 passed, 0 failures, 0 errors, 0 skipped`, and the PostgreSQL-enabled
14-file focused set returned `237 passed, 0 skipped`.
Credential-scanned JSON/JUnit evidence and SHA-256 values are recorded in
`docs/project/evidence/20260820_BR_150_TEAMAGENT_POSTGRES_GATE.md`. The
temporary container was removed by exact ID after the run. This supersedes the
historical local preflight result above, but only for the disposable local
contract Gate.

Deployed multi-replica failover, long-running serialization/recovery and
SLO/RPO/RTO rehearsal, production business-source validation, and any external
write authority remain open. `business_truth_proven=false` and
`external_write_allowed=false` remain hard boundaries.

## 2026-08-20 final current-tree receipt verification

The final retained artifacts under
`D:\KJDS\kjds\.runtime\team-agent-pg17-gate-20260820-final` were re-read and their
documented SHA-256 values matched. The receipt reports PostgreSQL 17, `38
passed, 0 failures, 0 errors, 0 skipped`, and
`spawned_process_recovery_executed=true`; credential scanning found no DSN or
password. This closes the disposable local PostgreSQL 17 contract Gate only.
Deployed multi-replica failover, long-running serialization/recovery, and
production business-source validation remain open.

## 前沿采用边界

frontier registry 当前结论保持不变：

- `durable_workflow_adapter` 仍是 `pilot`：只有在证明现有持久状态机/恢复能力不足，且不会制造第二业务真相时，
  才允许隔离试验；
- `mcp_tasks_durable_protocol` 仍是 `watch`：不能把协议 task state 当作 KJDS canonical runtime state；
- `a2a_cross_agent_interoperability` 仍是 `watch`：不能把远端 agent delegation 当作本地 TeamAgent runtime
  恢复方案；
- 因此本 ADR 采用 sidecar + `0099` 接线，而不是引入新的 durable workflow 平台。

## 相关文件

- `docs/adr/ADR-0102-harness-graph-teamagent-orchestration-resilience.md`
- `docs/adr/ADR-0103-teamagent-postgresql-persistence-cas.md`
- `apps/control_plane/agent_team_orchestration.py`
- `apps/control_plane/team_agent_persistence.py`
- `migrations/versions/20260819_0099_team_agent_orchestration_persistence.py`
- `migrations/versions/20260820_0103_team_agent_paused_retry_schedule.py`
- `apps/control_plane/runtime.py`

## 2026-08-20 latest source receipt correction

The latest runtime/persistence source was rerun with the full 42-contract
PostgreSQL 17.10 Gate: `42 passed, 0 failures, 0 errors, 0 skipped`, head
`20260820_0103`. Artifacts are retained under
`D:\KJDS\kjds\.runtime\team-agent-pg17-root-final3-20260820\`; source hash
`510d414870dd870fb0cdd660fc8f89f814e273fa21ad745551006fb30d1bc662`, JUnit
hash `2f3c27e6cb1a13598ae4783977a14f363c8cec654de77a65aae252dde8d0430c`.
This remains local disposable evidence; cross-process production wiring,
replica failover and durable publication liveness are not passed.
