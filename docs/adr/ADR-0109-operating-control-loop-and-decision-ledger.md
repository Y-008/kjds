# ADR-0109：经营控制回路与决策账本

状态：Proposed
日期：2026-09-07
范围：KJDS 控制平面内的目标、指标编译、决策记录和控制塔投影

## 决策摘要

KJDS 将经营自动化统一建模为：

```text
Objective → KPI → Constraint → Observation → Hypothesis → Decision
→ Action → Readback → Outcome → Learning → Policy Update
```

该回路只复用现有 `ScopeRef`、`OperatingSnapshot`、Temporal Fact、Evidence、
Action Contract 和经济护栏。新增模块只负责校验、编译和不可变投影，不建立第二套
事实库、利润库、权限库、队列或 Ozon 执行权威。

## 选择与边界

### 选定：纯领域服务 + 受控 API 投影

- `ObjectiveControlLoop` 对目标、节奏、冷却、滞后、停止规则和作用域做确定性校验。
- `MetricRecipeCompiler` 在指标读取前检查来源事实、时间语义、质量状态、币种和公式版本。
- `DecisionLedger` 只追加带快照、证据和幂等键的决策事件；重复键必须返回原事件，内容漂移必须失败。
- API 只返回 `DataEnvelope` 风格的只读投影；任何平台写入仍必须走既有 Approval → Permit → Execution → Readback → Rollback 链。

### 拒绝：在新模块中复制事实或直接驱动连接器

复制订单/库存/利润事实会造成口径分叉；直接从 Agent 或控制塔调用 Ozon 会绕过作用域、租约、Permit、回读和 Kill Switch。该方案不符合现有主规格和 `best_solution` 约束。

### 暂缓：引入新的队列、工作流引擎或模型运行时

当前规模和现有 PostgreSQL、Outbox、Project Graph、Agent Runtime 足以承载首个回路切片。若吞吐或恢复证据证明不足，另行提交 ADR 和迁移方案。

## 控制回路合同

每个节奏（`fast`、`medium`、`slow`）必须声明 `cadence`、`cooldown`、`max_change`、
`hysteresis`、`stop_rule`、`owner` 和 `rollback_rule`。在冷却窗口内，只有经济护栏突破或
安全事件才能重新评估；未知外部回读永远保持 `UNKNOWN_OUTCOME`，不能被当作成功或失败。

目标树沿 `集团 → 主体 → 店铺 → 类目 → SKU → 任务` 继承，但每次计算绑定一个
`OperatingSnapshot`。快照、证据、数据质量、运行和经济状态任一变化都会使下游决策变旧。

## 数据与安全

- 目标和决策使用现有 `ScopeRef`，禁止跨租户或跨店铺查询。
- 指标缺失保留 `NO_DATA/PARTIAL/STALE/BLOCKED/UNKNOWN_OUTCOME`，绝不转成零。
- 账本事件不得包含凭证、Token、Cookie、银行账号或原始商品正文。
- 决策只产生内部建议和审计事件，不授予 Permit、预算或外部写权限。
- 运行时默认 `external_write_allowed=false`，并在 API 响应中显式返回。

## 验收

1. 相同目标、快照和观察输入产生相同哈希。
2. 冷却、滞后、最大变化和停止规则在正例、反例、乱序和重复输入下保持确定性。
3. 指标编译拒绝缺来源、缺时间语义、非法质量状态、币种混加和同名不同版本。
4. 决策账本幂等重放返回原事件，内容漂移返回冲突，任何事件可追到快照和证据引用。
5. API 与控制塔不发起 Ozon 或其他外部写请求，并保留现有作用域、Kill Switch 和回滚边界。

## 失效与回滚

若共享 Scope、Metric、Snapshot 或 Action Contract 变化，相关控制回路和账本投影标记
`STALE/INVALIDATED`，保留旧事件并生成修复任务。删除新模块或禁用路由即可回退，既有
事实和执行链不受影响。

