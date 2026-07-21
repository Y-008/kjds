# 受限执行动作日风险预留证据（2026-07-21）

## 结论

BAS-081 已完成第一段可验证的组合风险控制：复用唯一 Action Policy 与 Limited Executor，在同一动作、同一 UTC 日内串行预留执行次数，并冻结同动作、同币种的累计风险快照。授权摘要绑定该快照；控制面在 Worker claim 前重新计算当日风险；Ozon Worker 在平台写入前再次验证授权摘要与风险快照哈希。

这不是完整的企业资本风控。当前明确未覆盖 SKU、类目、店铺、法人和 13 周现金底线，也没有工程代码自行虚构这些阈值。真实 Owner 提供机器可读额度和真实现金数据前，这些维度仍是阻塞项。

## 已实现合同

1. `action_policy_registry` 是唯一动作政策来源；所有 L3/L4 动作必须声明 `max_daily_runs`，缺失时注册表加载失败。
2. `LimitedExecutionCommand` 增加不可空 `portfolio_risk_json`，Alembic 迁移头升级为 `20260721_0040`。
3. execute 命令排队时，PostgreSQL 使用以 `action_id + UTC day` 派生的事务级 advisory lock，关闭并发请求同时穿透日额度的竞态窗口。
4. 同日所有 execute 命令保守占用每日次数；失败、过期、不确定或等待执行的命令均不会自动释放当日预算，避免通过重试扩大风险。
5. 同动作、同币种风险按命令累计；第一版日上限由单次上限乘以 `max_daily_runs` 派生，不声称跨币种可直接相加。
6. 快照记录累计值、派生上限、先前命令、稳定阻断码、覆盖范围、未建模轴和 SHA-256；外层 `authorization_hash` 同时绑定该快照。
7. Worker claim 时重新读取当前动作日命令并复验；若后续预留使预算超限，则失败关闭。
8. Ozon Worker 独立重算外层授权摘要和内部风险快照哈希；即使有人重算外层摘要，篡改内部累计风险仍会被拒绝。
9. rollback 使用独立、绑定父命令的补偿快照，不消耗新的 execute 日额度，也不能被当作新业务授权。

## 覆盖边界

| 维度 | 当前状态 |
|---|---|
| 动作 + UTC 日执行次数 | 已实现 |
| 同动作 + 同币种累计风险 | 已实现 |
| PostgreSQL 并发排队串行化 | 代码和迁移已实现；本机 daemon 不可用，尚无本轮真实 PostgreSQL 运行证据 |
| SKU / 类目 / 店铺 / 法人聚合 | 未实现，快照显式列为 `unmodeled_axes` |
| 多币种折算和 FX 风险 | 未实现，不进行伪精确汇总 |
| 13 周最低现金余额硬约束 | 既有预测能力尚未接入执行门；等待 Owner 阈值和真实数据 |
| 资本优化器、ML/RL 数字孪生 | 当前不建设 |

## 绕过验证

| 攻击或故障 | 预期与结果 |
|---|---|
| 已有一次预留后，再用每日一次的政策申请同动作 | 同时触发次数、预计损失和数量日上限，失败关闭 |
| 修改数据库中的冻结风险快照 | `authorization_hash` 不一致，claim 被拒绝 |
| 修改 Worker 收到的内部累计风险并重算外层授权摘要 | 内部 `snapshot_hash` 不一致，平台写入前被拒绝 |
| L3/L4 动作缺 `max_daily_runs` | 注册表校验失败 |
| 同计划重复排队 | 事务锁内再次查找并返回原幂等命令，不重复占用 |
| 当日失败或过期命令 | 仍保守占用，不因重试释放预算 |

## 验证证据

| 检查 | 结果 |
|---|---|
| 相关动作政策、控制面与 Worker 回归 | 46 passed |
| Python 全量回归 | 329 passed；1 条第三方 Starlette/httpx 弃用警告 |
| Python 静态检查 | `uv run ruff check .` 通过 |
| Alembic 静态迁移头 | `20260721_0040 (head)` |
| OpenAPI v1 快照 | 已从当前运行时契约重新导出 |
| Web 契约 | 19 passed |
| Next.js 生产构建 | 通过 |
| 差异空白检查 | `git diff --check` 通过；仅既有 LF/CRLF 提示 |
| Docker/PostgreSQL 真实迁移与健康检查 | 未通过环境前置条件：Docker daemon 未运行 |

## 官方依据与项目推导

- NIST AI RMF Core：持续 Govern、Measure、Manage 和角色/风险记录。<https://airc.nist.gov/airmf-resources/airmf/5-sec-core/>
- NIST SP 800-207：按请求显式授权、最小权限与持续复验。<https://csrc.nist.gov/pubs/sp/800/207/final>
- OWASP AI Agent Security：高影响工具调用需要最小权限、人工控制、审计和独立验证。<https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html>
- OWASP LLM06 Excessive Agency：限制权限、功能、自治和副作用范围。<https://genai.owasp.org/llmrisk/llm062025-excessive-agency/>

精确的 L0-L4、动作日预留、保守不释放、快照字段和稳定阻断码是 KJDS 的工程推导，不是上述标准的原文字段。

## 下一顺序

1. 先由经营 Owner 冻结店铺、法人、币种、库存和最低现金机器阈值；工程不得代填。
2. 将既有 `forecast / commitment / actual` 与 13 周现金预测接入同一个 `authorize_action()`，先做 Base/Downside/Severe 影子判断。
3. 为 Ozon、ComfyUI 和财务导入补脱敏 fixture 回放，覆盖 Schema 漂移、限流、超时、成功未生效、重复响应和 readback 不一致。
4. 以先锋、第二和第三 SKU 的真实结果校准预测偏差、人工修改率、能力总成本和增量利润，再决定是否扩大自动化。
