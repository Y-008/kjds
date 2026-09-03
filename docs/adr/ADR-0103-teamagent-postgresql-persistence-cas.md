# ADR-0103 — TeamAgent PostgreSQL 持久化 seam 与事务 CAS

## 2026-08-20 current-tree all-38 rerun

The current contract file collects 38 tests. A fresh disposable PostgreSQL
17.10 run returned `38 passed, 0 failures, 0 errors, 0 skipped`, including
spawned-worker recovery, the conflicting-lease CAS fence, and caller-owned
checkpoint snapshot-isolation contracts. Credential-free artifacts are under
`D:\KJDS\kjds\.runtime\team-agent-pg17-gate-20260820-final\`; JUnit SHA-256:
`072c7e9877f6d6009ef87732771b3ed27565f17c5b1681807889ed2bd6700a75`. This is
a local disposable contract receipt only; deployed multi-replica failover and
cross-process production acceptance remain open.

## 2026-08-20 latest all-42 source correction

After a subsequent persistence/runtime source update, the current 42-contract
suite was rerun in a fresh PostgreSQL 17.10 container: `42 passed, 0 failures,
0 errors, 0 skipped`, Alembic head `20260820_0103`. Credential-free artifacts
are under
`D:\KJDS\kjds\.runtime\team-agent-pg17-root-final3-20260820\`; contract source
SHA-256 is
`510d414870dd870fb0cdd660fc8f89f814e273fa21ad745551006fb30d1bc662` and JUnit
SHA-256 is
`2f3c27e6cb1a13598ae4783977a14f363c8cec654de77a65aae252dde8d0430c`.
This supersedes earlier all-42 evidence only for source currency; deployed
multi-replica failover, publication deduplication, and production cross-process
acceptance remain open.

| 元数据 | 值 |
|---|---|
| status | Accepted for minimal persistence slice |
| date | 2026-08-19 |
| requirement | BR-150 |
| affects | TeamAgent task state、lease、transition event、checkpoint projection |
| predecessor | ADR-0102 |

## 背景

ADR-0102 交付的是单进程内存编排内核，并明确在 PostgreSQL migration、事务 CAS、唯一
lease/claim 与多副本恢复演练完成前，不宣称跨进程生产编排。当前切片只解决其中可独立验证的
任务持久化与唯一 claim，不改现有 Coordinator、Router 或 runtime WIP。

## 决策

1. 在 `TeamAgentPersistence` seam 后提供内存与 PostgreSQL 两个 Adapter。Caller 只使用
   `register/read/claim/heartbeat/release/checkpoint`，不传 revision、不管理事务，也不单独追加事件。
2. PostgreSQL 使用 exact scope + session + task 复合身份；同 scope/session 的 idempotency key 唯一。
   同键同请求为幂等重放，同键不同请求失败关闭。
3. claim 先读取当前 revision，再用一条带 exact scope、revision、claimable state、lease expiry 和
   attempt budget 条件的 `UPDATE ... RETURNING` 完成 CAS。并发 Worker 只有一个更新成功；同 Worker
   的未过期 lease 为幂等重入；过期 lease 只能通过新的 CAS 回收并递增 attempt/revision。
4. heartbeat 与 release 同样要求 revision + worker + lease + 未过期条件。每次成功变更在同一事务
   追加一个不可变 transition event；延迟约束保证每个 task revision 恰有对应事件。
5. checkpoint 是按 exact scope/session 从 durable task + event 计算的确定性只读投影，不另建第二
   状态真源。迁移 downgrade 在存在 durable state 时失败关闭，避免静默丢数。

## 2026-08-19 一致性核验补充

- PostgreSQL checkpoint 在同一 `REPEATABLE READ` 事务快照中读取 tasks 与 events，避免 READ COMMITTED 下两次查询撕裂；自建连接自动使用该隔离级别，caller-owned 事务通过 transaction-local `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ` 提升，若事务已进入不可变更阶段则失败关闭；更强的 `SERIALIZABLE` 保持不降级，不返回撕裂投影。
- 同 worker 并发 claim 的 CAS 输家在同一事务内重读 winner；若 winner 仍是该 worker 的未过期 lease，则幂等返回相同 lease/revision，不追加重复事件。
- 这些修复只增强 0099 persistence seam 的 task/lease/event 合同；不等于 runtime 已把 0099 与 0100 sidecar 在同一 session 事务中接线。

## 备选与边界

- 不采用整份 Coordinator checkpoint JSON 作为唯一可变行：它会把单任务 claim 退化为大对象竞争，
  并使并发、索引和 lease 约束不可验证。
- 不采用仅进程内锁或 PostgreSQL advisory lock 作为 claim 真相：它们不能替代可检查的行级状态、
  revision 和 lease 条件。
- 不引入 Temporal、MCP Tasks、A2A、Redis 或 PostgreSQL 18。前沿注册表中的
  `durable_workflow_adapter` 继续保持 pilot，`postgresql_18_rehearsal` 继续保持 pilot；本次
  `frontier_review=checked_no_change`，沿用 PostgreSQL 17 基线。
- 本切片不接 runtime，不持久化完整 session/thread/handoff/circuit-breaker，不完成 Coordinator
  restart hydration，也不构成多副本生产验收。后续接线必须复用本 seam，并补齐完整状态恢复与
  多进程故障演练。

## 验收

- Alembic 唯一 head 从 `20260809_0098` 线性升级为 `20260819_0099`，空表可降级并重放。
- PostgreSQL 双线程竞争同一 task 时恰好一个 claim 成功。
- 未过期 lease、错 Worker/lease、跨 exact scope 和 idempotency payload drift 全部失败关闭。
- 过期 lease 可由另一 Worker 回收，attempt/revision 单调递增，checkpoint 事件链与最终 task 一致。

## 2026-08-19 runtime 接线与精确 lease 补充

`PostgresTeamAgentRuntime` 已在 PostgreSQL runtime composition 中作为条件 facade 装配；本 ADR
原有“本切片不接 runtime”的边界保留为历史决策记录，不代表当前共享树的 runtime 状态。当前
durable mutation 会在 exact-scope 的 0100 sidecar 行锁下，将 0099 task/event、Coordinator
投影和 checkpoint save 放入同一 caller-owned transaction；读路径的 `restore_session` 不执行
恢复写入，只有显式写授权的 `recover_session` 或 mutation admission 才能提交过期 lease recovery。

claim 与 heartbeat 均把 Coordinator 计算出的绝对 `lease_expires_at` 传入 0099，并在请求 lease
窗口内校验，避免时间预算截断时以整数秒重算造成 0099/0100 lease 漂移。当前 shell 未提供
PostgreSQL，相关集成合同仍为 collected/skipped；跨进程生产 Gate 仍为 `NOT PASSED`。

## 2026-08-20 current-tree PostgreSQL contract receipt

在本地 run-owned PostgreSQL 17.10 disposable container 中，当前 0099/0100
contract file 实跑 `37 passed, 0 skipped`，包含 spawned-process claim/restart
recovery、同 worker conflicting lease fence，以及 caller-owned 默认事务提升到
`REPEATABLE READ` 与保留 `SERIALIZABLE` 的 checkpoint snapshot 合同。该回执只证明
一次性本地合同 Gate；部署多副本故障转移、长时序列化恢复、SLO/RPO/RTO 与生产
cross-process Gate 仍保持 `NOT PASSED`。
