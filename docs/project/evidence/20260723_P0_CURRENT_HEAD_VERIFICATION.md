# P0 当前提交验证记录

| 字段 | 值 |
|---|---|
| 日期 | 2026-07-23 |
| Commit | `b1422d955a150795d7befe1cfbdcf3273febfaaa` |
| Gate | G-1–G1 |
| G-1 | PASS |
| BAS-026 | PARTIAL_BLOCKED |
| RU-HYP-001 | BLOCKED / research only |
| 外部写入 | 否 |

本记录只证明上述提交对应的本次运行结果。当前机器状态仍以本地生成且不提交的 `.runtime/G1_VERIFICATION.json` 为准；后续代码、依赖或环境变化必须重新验证。

## G-1 工程基线

- `.runtime/G1_VERIFICATION.json` 的 `git_commit` 与上述 Commit 精确一致，状态为 `PASS`。
- 唯一 Alembic head 为 `20260721_0040`；迁移回放、Transactional Outbox、数值完整性和领域合同通过。
- Python、Web、生产镜像、API、Worker、Evidence、完整性健康环、备份与隔离恢复通过。
- `cleanup_processes=true`、`cleanup_database=true`、`cleanup_files=true`，且清理错误为空。
- 本轮修复并回归覆盖 Windows 下 pytest 临时 Git 对象只读属性导致的清理失败；清理异常不会阻止 FAIL 报告落盘，报告写入失败会返回非零。

## BAS-026 真实双用户验收

工程边界已完成本地验证，但不能替代真实经营验收。状态继续为 `PARTIAL_BLOCKED`，尚需：

- 两个不同的真实 Supabase 用户、KJDS actor 和服务端 credential；
- approver 真实 TOTP/AAL2 与独立浏览器或设备；
- operator 禁批、AAL1 禁批、自提自批和重放拒绝；
- 会话撤销、密码恢复、TOTP 撤销与重绑、全局登出；
- 脱敏 Evidence Package 与经营负责人签署。

本次没有创建或撤销真实账号、凭证或 MFA 因素，也没有触发 Ozon 写入。

## RU-HYP-001 私密启动包

对 Git 忽略的本地 `real-sku-startup` 工作区仅运行现有离线校验，并只保留聚合结论：

- `contract=kjds-startup-package-v4`；
- `status=structurally_valid`；
- 严格预检退出码为 3；
- 候选研究、治理、Ozon 访问、API 身份、Passport、供应商报价、财务对账和商品媒体八个资料区均为 `awaiting_inputs`；
- `formal_fact_promoted=false`。

未在本记录中复制私密 CSV 行、供应商内容、账号信息或证据原件。结构通过不证明内容真实、Evidence 有效、候选通过或 Gate 放行。RU-HYP-001 继续保持候选/研究状态，等待 28 天官方原件、五指标独立复核、A 级合规书面结论、三份同 BOM 正式报价、样品实测、三类 Passport、完整成本/CM3 和人工 Gate Review。

## 安全与文档边界

- 未登录 Ozon、未接受外部条款、未发送 RFQ、未付款、未采购、未发布、未投放广告、未补货。
- 未更新 `BAS-026`、`SKU-000/001/002/003` 为完成或通过。
- `STRATEGY_AND_ARCHITECTURE_2026.md` 保持未跟踪的 `Draft / Non-normative / C-grade research`，不作为项目状态、预算、KPI 或架构决策真源。
- 本记录是版本化 Evidence，不替代 `03_REMAINING_WORK_AND_PARALLEL_PLAN.md` 的动态任务状态，也不替代机器运行报告。
