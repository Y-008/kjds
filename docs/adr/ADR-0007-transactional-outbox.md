# ADR-0007：PostgreSQL 事务 Outbox 与至少一次发布

- 状态：Accepted
- 日期：2026-07-17
- 对应规格：`MASTER_SPEC.md` 17.1 Outbox/事件发布

## 问题

现有核心 Service 先提交业务表，再调用 `append_event` 开第二个事务。两次提交之间若进程退出，业务事实存在但事件缺失；仅增加发布 worker 无法修复这个缺口。

## 决策

1. Repository 提供显式事务上下文；事务内所有 Repository 读写复用同一 SQLAlchemy Session。
2. 核心 Service 在同一上下文中写业务对象与 Outbox 事件；任一步失败时两者一起回滚。
3. Outbox 事件包含稳定 `event_id`、`event_type`、`aggregate_id`、规范化 `payload_hash`、发生/记录时间、actor、证据引用和 schema version。
4. 发布器通过 PostgreSQL 行锁和 `SKIP LOCKED` 有界领取事件，使用租约避免 worker 崩溃后永久占用。
5. 发布语义为至少一次。外部 sink 必须以 `event_id` 幂等；worker 在“sink 已接收、数据库尚未标记”时崩溃会安全重投。
6. 失败记录次数、下次可用时间和脱敏错误；达到重试时间后可自动领取，过期租约可由新 worker 接管。

## 边界

- 本 ADR 不引入 Kafka、Redis、Temporal 或常驻消息基础设施。
- 第一批迁移现有 Repository 驱动的商品、Passport、订单、费用、审批、Agent task、市场、内容和实验服务。
- 第二批优先覆盖会改变 Gate 放行结论的 Gate Review 创建、提交和决定；事件只携带 gate、状态、决定和证据数量等最小脱敏字段。
- 其他直接使用 SQLAlchemy Session 的领域服务按 `docs/project/registries/outbox_coverage.json` 逐项分类；只有出现真实跨边界消费者或对应 Gate 启用条件时才迁移，不为“覆盖率”制造无消费者事件。
- 代码中的直接事务模块集合必须与覆盖清单精确一致；新增、删除或改名未同步分类时由测试拒绝。在外部 sink 和清单中待迁移边界全部收口前，不宣称“全系统 Outbox 完成”。
- 手工重放只允许未发布事件；已发布事件需要新业务补偿事件，不能清空 `published_at` 制造隐式重复。

## 验收

- 强制事件写失败时业务写也不存在。
- 同一批事件不会被两个并发 worker 同时领取。
- 发布失败后保留事件并可重试；租约过期后新 worker 可接管。
- 发布成功后保留不可变事件与发布时间；payload hash 可复算。
- PostgreSQL 迁移升级、回滚、再升级通过。

## 验证结果

2026-07-17 的 G-1 在一次性 PostgreSQL 数据库上通过全部验收：迁移 head `20260717_0029`，原子回滚、双 worker 独占领取、租约过期接管、失败重试和稳定 `event_id` 均为 PASS；完整回归为 119 passed。证据见 `docs/project/evidence/2026-07-17-transactional-outbox-verification.md`。

当前实现包含 `GET /v1/outbox/status` 运行状态接口，但尚未绑定生产外部 sink。该限制不影响 ADR 的原子性与发布语义决策，影响的是具体生产投递范围。

2026-07-18 的第二批只覆盖 Gate Review：创建、提交、决定分别原子写入最小脱敏事件；决定事件写入失败时业务状态回滚到 `submitted`。完整 G-1 为 138 passed，真实 PostgreSQL Gate API 链、通用 Outbox 竞态/恢复和 Web/API smoke 全部 PASS。证据见 `docs/project/evidence/2026-07-18-gate-review-outbox-verification.md`。

2026-07-18 的覆盖清单批次没有新增事件：机器清单逐项登记 25 个直接事务模块，并由源码发现测试防止新增、删除或改名后静默漂移。当前分类为 2 个已覆盖、2 个轮询合同、4 个 Gate 前延期、15 个仅内部状态和 2 个基础设施模块，且显式保持 `full_system_outbox=false`。完整 G-1 为 139 passed、234 文件密钥扫描，证据见 `docs/project/evidence/2026-07-18-outbox-coverage-registry-verification.md`。
