# BAS-067：Ozon 计提分类与防重复确认合同

| 元数据 | 值 |
|---|---|
| task_id | BAS-067 |
| requirement | BR-053 |
| status | DONE_ENGINEERING / NEEDS_REAL_APPROVAL |
| verified_at | 2026-07-20 |
| posting policy | `control_only_no_finance_entry` |

## 1. 结果

系统现在会从已独立接受的 `ozon_accrual` 原件中只列出真实出现的“服务组 + 计提类型”。Reviewer、Compliance 或 Admin 可为每一对提交会计类别、预期符号、生效区间和理由；批准证明不可变、带版本，并同时链接原报告和 import。

分类全部覆盖后，报告行只可晋升为 `ozon_accrual` 正式控制事实。该动作不会生成 Finance Entry，不会替代 `ozon_order` 的订单收入，也不会把整份计提报告当成平台费用。`FinanceService.ingest_fact` 对计提事实继续失败关闭。

## 2. 防绕过边界

- 来源复核未接受时不能分类。
- 上传者不能批准自己的报告分类。
- 只能批准原件实际出现的服务组与计提类型组合。
- 生效区间必须至少覆盖一条该组合的真实行。
- 任何未分类行都会阻断整份报告晋升。
- 分类 Evidence 缺失、损坏或与报告/import 血缘不一致时不计为有效。
- 分类状态固定返回 `automatic_finance_posting=false` 和 `order_revenue_replacement=false`。

## 3. API

- `GET /v1/imports/{import_id}/accrual-classifications`：返回观察组合、行数、控制总额、币种、期间、覆盖状态及批准 ID。
- `POST /v1/imports/{import_id}/accrual-classifications`：批准一个观察组合；重复相同请求返回原批准，不重复造证据。

## 4. 验证

定向财务回归覆盖来源门、观察组合限制、上传者隔离、生效区间、幂等、全覆盖晋升、零财务分录和计提事实直接入账失败。OpenAPI 快照与接口合同测试同步覆盖新端点。

- Python 全量回归：`291 passed`（1 条上游 Starlette 弃用告警）。
- Ruff：全库通过。
- Web 合同回归：`14 passed`。
- Next.js 生产构建：通过。
- `git diff --check`：通过；仅报告工作区既有 LF/CRLF 提示。

## 5. 尚未完成

真实 Ozon 原件已正式存证为 `evd_902fe12a454e4703b88b6ad7314ed652` / `imp_76eab9701e954896a6f67ccdbb845cb6`，但仍需不同身份完成来源复核；9 个真实计提类型仍需财务负责人逐项批准。分类只解决语义和重复确认边界，不等于订单—计提—结算—银行—FX 对账完成，也不解除利润未知项。
