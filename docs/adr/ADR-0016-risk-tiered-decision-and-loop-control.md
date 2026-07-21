# ADR-0016：风险分级决策与 Loop Engineering 控制

| 元数据 | 值 |
|---|---|
| status | Accepted; L3 runtime, aggregate reservation and independent shadow comparison implemented |
| date | 2026-07-20 |
| owner | 控制面负责人（待经营负责人确认） |
| approver | 经营负责人待 G0 复核 |
| affects | BR-037 / BR-060 / BR-061 / BR-062 / G5 / G6 |

## 背景

KJDS 已具备 Evidence、Decision Lifecycle、Policy Shadow、Capability Economics、13 周现金预测、Limited Executor、回读、回滚和全局 Kill Switch。缺口不是继续增加组件，而是让所有正式事实晋升和外部副作用共享同一动作政策，且能证明决定来源、执行边界和自动化经济价值。

## 权威依据与 KJDS 推导

- NIST AI RMF 要求在全生命周期持续 Govern/Map/Measure/Manage，记录角色、指标、独立复核、上线/停用和持续改进。
- NIST SP 800-207 的零信任原则支持按资源和请求显式授权、最小权限及持续复验。
- OWASP AI Agent Security 要求按动作风险设置自治边界，高影响动作由执行组件独立验证，并把短期授权绑定到精确动作、操作者、目标、参数、时间和失效条件，防止重放。
- W3C PROV-O 的 Entity/Activity/Agent、生成、归属、修订和失效关系支持 DecisionPacket 的来源投影。
- SLSA Provenance 的制品证明思想可用于 ComfyUI workflow、模型、节点、运行镜像和输入输出哈希，但 KJDS 不宣称媒体制品已经达到某个 SLSA 等级。
- Google SRE Canary 与 FinOps Unit Economics 分别支持小流量对照/回退和技术成本—业务价值联动。

L0-L4 的精确分级、`DecisionPacket` 字段、`forecast/commitment/actual` 经营语义、组合风险预算及注册表名称是 KJDS 面向跨境经营的工程推导，不伪装成上述标准的原文要求。

## 决策

1. 只增加一个 `action_policy_registry`，同时保存风险等级、作用域、审批、执行许可、额度、幂等、回读和回滚要求；不创建多个 Gate 或多个风险注册表。
2. `DecisionPacket` 第一阶段是现有不可变对象的确定性投影，不新建数据库表；只有实测证明投影查询不可接受时才评审物化。
3. `ExecutionPermit` 第一阶段由既有 `LimitedExecutionCommand` 演进：保留唯一命令、幂等 token、租约、精确目标/patch、回执和回滚，并已补动作政策、决定摘要、额度、短期失效和授权摘要字段；不建设平行执行器。
4. Champion/Challenger 复用 Policy Shadow、Observation Window 和不可变 Evaluation；每个可晋升的影子 Evaluation 必须冻结不同身份提供的 `champion` 或 `human` 基线结果、基线 Evidence、双方摘要哈希和有界差异路径。无基线 Evaluation 只允许诊断，不得形成阶段结果或激活。Capability Economics 继续使用现有经济评估表，不新增第二套 Skill 损益账；影子一致率不等于增量利润。
5. 组合风险分阶段收口。第一步不新增风险注册表，而是在既有 `LimitedExecutionCommand` 事务中按“动作 + UTC 日”串行预留 `max_daily_runs`，并把同动作、同币种的保守累计风险和派生上限冻结到命令；失败、过期和不确定命令在当日都不自动释放预算，避免通过失败重试扩大暴露。PostgreSQL 使用事务级 advisory lock 关闭并发穿透，测试数据库保持单事务确定性检查。第二步在真实 Owner 提供店铺、法人、币种和最低现金限额后，才把既有 13 周现金预测接入硬约束；不得由工程代码虚构资本阈值。Base/Downside/Severe 继续复用现有成本场景和现金预测，没有真实先锋 SKU 样本前不建设 ML/RL 数字孪生。
6. ComfyUI 供应链治理先扩展现有固定 workflow 合同和 Evidence manifest；n8n 仍只负责外围触发和通知，二者都无 Gate、财务或平台写真源。
7. 动作政策和适配器映射进入 CI。L3 `listing_publish` 已在请求、排队、Worker claim 和外部写前复验，并绑定单次短期许可、决定哈希、额度和调用身份。L4 仍没有生产适配器；在 MFA 会话证据和组合风险预算接入前必须保持关闭。合同通过不等同于 G6 已放行。
8. 当前“双人复核”的机器语义是请求者与批准者两个不同身份、至少一个独立批准决定；Worker 还必须是第三个不同运行身份。若未来某动作确需两个独立批准决定，应通过动作政策显式提高 `minimum_approval_decisions`，不得靠文字暗示。

## 不建设

- 第二套业务后台、审批、事实库、工作流真源或执行器。
- 为 DecisionPacket、事实成熟度、灰度和 Kill Switch 预先创建通用表。
- 当前阶段引入 Temporal、Kafka、Kubernetes、Redis 队列模式或新的规则引擎。
- 任意 Agent 自主付款、采购、上架、广告、补货或正式入账。
- 未经先锋、第二和第三 SKU 复现的 Skill 全量晋升。

## 验收

1. 注册表包含唯一动作 ID 和 L0-L4 定义；L3/L4 缺双人复核、单次许可、请求/执行复验、额度、幂等或回读时 CI 失败。
2. 所有可执行适配器声明稳定动作 ID，且该动作存在于注册表；实时写适配器只能映射 L3/L4。
3. 研究动作不得声明经营外部副作用；正式事实晋升与平台写动作不得使用 `research` 作用域。
4. 未接入统一运行时授权的真实写入口保持关闭，不能因为注册表存在而宣称已安全执行。
5. `uv run ruff check .`、动作政策测试、完整回归和 `git diff --check` 通过。
6. 同一动作同一 UTC 日的排队必须在 PostgreSQL 中串行检查并预留每日次数；命令返回当时的累计风险、派生上限、覆盖范围和快照哈希，授权摘要必须绑定该快照。执行前重新计算当前动作日预算，超限失败关闭。

## 官方参考

- https://airc.nist.gov/airmf-resources/airmf/5-sec-core/
- https://csrc.nist.gov/pubs/sp/800/207/final
- https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html
- https://www.w3.org/TR/prov-o/
- https://slsa.dev/spec/v1.2/
- https://sre.google/workbook/canarying-releases/
- https://www.finops.org/framework/capabilities/unit-economics/
