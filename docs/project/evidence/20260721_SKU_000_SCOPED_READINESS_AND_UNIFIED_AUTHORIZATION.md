# SKU-000 作用域化 Readiness 与统一动作授权证据（2026-07-21）

## 结论

KJDS 保留唯一任务 `SKU-000`、一个服务端 Gate 引擎和一个动作政策注册表，没有新增 Ozon Data 专用后台、第二套审批或平行动作授权器。当前工程已经把“可继续研究”和“允许真实经营副作用”分开计算，并把真实执行 readiness 绑定到计划创建、许可排队和 Worker claim 的同一运行时 `authorize_action()`。

该结论是工程完成，不是经营放行。当前仍没有用真实 Ozon 账户原件完成 `real_execution`，外部执行默认开关仍关闭。

## 机器合同

### 单任务双作用域

- `research`：接受窗口不少于 28 天、原件可复验且经非上传者接受的 Ozon 官方分析、脱敏历史样本或固定测试数据。
- `real_execution`：只接受已独立复核的 Ozon Data 正式报告，或至少两个不同 Ozon 官方分析入口的组合证据。
- 固定测试数据、脱敏历史和单一免费研究入口不得放行付款、采购、发布、广告、补货或正式事实晋升。
- `status.ready` 暂时保留为 `real_execution_ready` 的兼容别名；新调用方读取明确的 `research_ready` 和 `real_execution_ready`。

### 一个 phase-aware 授权入口

`authorize_action(action, subject_id, actor, occurred_at, phase, readiness)` 在以下阶段复用同一政策：

1. `request`：创建或读取执行计划时复验动作、风险层、审批、MFA 和 readiness。
2. `permit`：进入短期单次许可队列前复验。
3. `execute`：Worker claim 后、外部副作用前再次复验。

动作注册表 `policy_version=2026-07-21.1` 声明每个高风险动作的 `required_readiness_keys`。例如 `listing_publish`、`sample_pay`、`purchase_commit`、`advertising_start` 与 `replenishment_commit` 缺少 `demand.real_execution` 时失败关闭；`actual_cost_promote` 和 `ledger_post` 分别依赖实际成本权威与财务复核 readiness。

### 现有界面

G0–G1 页面现在直接展示：

- 研究闭环 `READY/BLOCKED`；
- 真实经营 `READY/BLOCKED`；
- 每个作用域的稳定阻塞原因；
- 原件来源类型、来源定位、窗口和待独立复核状态。

界面只展示服务端结论，不能自行把按钮隐藏或显示当成授权。

## 验证结果

| 检查 | 结果 |
|---|---|
| Python 静态检查 | `uv run ruff check .` 通过 |
| Python 全量回归 | 329 passed；另有 1 条第三方 Starlette/httpx 弃用警告 |
| Web 契约测试 | 19 passed |
| Web 生产构建 | Next.js build 通过 |
| OpenAPI v1 快照 | 已从运行时重新导出，全量契约测试通过 |
| 关键行为 | 固定测试数据可放行研究但不放行真实经营；两个独立官方来源可满足真实经营；缺 readiness 的真实动作被统一授权器拒绝；L4 缺 MFA 被拒绝 |

首次全量回归使用仓库内 `.pytest-tmp` 时，有隔离测试清理父目录导致后续 7 个用例无法建立临时目录；这不是业务断言失败。改用仓库外独立临时目录后，329 项全部通过，故未修改生产代码掩盖测试环境问题。

## 标准依据与 KJDS 自有设计

- 最小权限、持续验证与按请求授权来自 [NIST SP 800-207 Zero Trust Architecture](https://csrc.nist.gov/pubs/sp/800/207/final)。
- AI 行动范围、最小工具权限和高影响动作人工批准参考 [OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html) 与 [OWASP LLM06: Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)。
- Evidence、Activity、Agent 的可追溯表达参考 [W3C PROV-O](https://www.w3.org/TR/prov-o/)。
- 治理、测量和持续风险管理参考 [NIST AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)。

`research/real_execution`、L0–L4 具体映射、`DecisionPacket` 字段和动作注册表键名是 KJDS 针对跨境经营的工程综合，不是上述标准的原文规范。

## 仍未完成

1. 真实 Ozon Data 或两个独立官方原件尚未进入当前数据库并由另一身份接受，`real_execution` 继续阻塞。
2. L4 MFA 绑定、组合级现金/库存风险预算、分层 Kill Switch 和外部调用回放实验室仍未完成。
3. 本机 Docker daemon 不可用，本批没有新增真实 PostgreSQL `upgrade head` 与运行健康证据；不得用离线或单元测试替代上线验证。

## 下一执行顺序

1. 在共享副作用入口增加 SKU、店铺和全局风险预算预留，防止多笔小动作累积越界。
2. 为 Ozon、ComfyUI 和财务导入增加脱敏请求/响应 fixture 回放，覆盖超时、限流、重复成功、Schema 漂移和“返回成功但未生效”。
3. 用一个固定测试 SKU 跑通研究候选 → 模拟利润 → ComfyUI → Listing 草稿 → 审批演练，并证明真实发布被服务端阻断。

Readiness 证据冻结已由 `BAS-080` 完成，专项证据见 `20260721_READINESS_EVIDENCE_DECISION_PACKET.md`。
