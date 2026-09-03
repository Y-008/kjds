# ADR-0101 — Enterprise control kernel for scope, recovery, settlement and delivery

状态：Accepted for implementation (provider-neutral, no new runtime dependency)

日期：2026-08-19

## Context

KJDS 已经有 exact-scope authority、Customer Exit、Commercial Lifecycle、Ozon
execution worker、Outbox 和 Kill Switch。新增企业级交付需求还需要统一的数据分类、
生命周期、备份恢复、履约状态、五段现金匹配、用量计费和模型降级契约。若为每个模块
各自定义一套 scope、冻结、导出或结算语义，会产生第二套业务真相并削弱回滚能力。

## Decision

增加纯领域 `apps/control_plane/enterprise_control.py` 作为端口和不可变值对象层：

- 所有对象使用 `ExactScope(tenant_ref, entity_ref, store_ref)`，跨作用域访问失败关闭；
- Provider、数据库、Secret Manager、备份介质和 Ozon Worker 只能作为外层 adapter；
- 数据分类、导出、删除、Retention、Backup Manifest、Restore Receipt、DR Report、
  Kill Switch 和 Provider Failover 都使用哈希绑定的结果；
- 结算必须覆盖 `order → posting → accrual → payout → bank` 五段，缺银行证据保持
  `CASH_UNKNOWN/CASH_PARTIAL`；
- FBS/FBO/realFBS、库存预留、退货、供应商报价、全成本和对账异常使用显式状态机；
- 用量计费和模型路由按 exact scope 计算，Provider 健康只决定候选路由，不能晋升业务事实；
- 初始实现提供内存 adapter 供单元测试和 dry-run 使用，生产持久化继续复用既有
  PostgreSQL、Evidence、Outbox、Commercial Lifecycle 和 Kill Switch，不引入第二个真相库。
- `TeamAgentCoordinator` 只负责多会话、多线程、依赖和并行度调度；
  `TeamAgentHarnessBridge` 只能把任务终态投影为既有 Harness Graph Observation，
  且会话必须携带当前 `authority_sha256`。TeamAgent 结果不能生成 Fact、FinanceEntry、
  Approval、Permit 或外部写权限。
- `/v1/agent-control/team/*` 只开放受控编排和 Observation 发布；跨租户/跨店铺请求返回
  404/403，发布前由既有 Scope Grant 与 Harness verifier 再次校验。

## Alternatives considered

1. 在每个 Ozon/CRM/财务模块中各自添加字段和状态：拒绝，会重复 scope、恢复和结算语义。
2. 直接引入 Temporal、Redis、Kafka、ClickHouse 或向量数据库：延期，当前 registry
   将这些候选置于 pilot/watch/reject，尚无足够的真实负载和独立恢复证据。
3. 只补文档和 Runbook：拒绝，无法通过单元测试验证跨租户、冻结、现金和恢复不变量。

## Consequences

正面：领域用例可在无网络、无数据库的情况下测试；现有外部适配器可以逐步实现端口；
Kill Switch、数据删除和现金状态能被统一审计。

限制：当前内存 adapter 不是生产证据；需要后续把端口接入 PostgreSQL migration、
真实 Ozon readback、银行原件、备份 sidecar 和运行时健康 Gate。该 ADR 不授予任何
Ozon、银行或模型 Provider 的新增权限。

编排 API 当前使用进程内 coordinator，重启恢复和多实例一致性尚未宣称完成；正式产品 Gate
要求在字段冻结后新增单一 Alembic migration，并将任务/线程/Observation 接入既有
PostgreSQL 与 Outbox。`scripts/check_real_ozon_gates.ps1` 只输出脱敏 Gate 状态，不会
把 Key、Cookie、CAPTCHA 或银行资料写入日志。

## Acceptance evidence

- `tests/test_enterprise_control.py` 覆盖 scope、敏感数据、删除、备份恢复、冻结、
  五段现金、履约/退货、供应商报价、计费和 Provider failover；
- 外部写入仍由既有 `LimitedExecutorService`、Permit、Evidence 和 Kill Switch 控制；
- 生产 Gate 仍要求官方 Key、9225 会话、realFBS 官方确认、历史回读和银行凭证。
