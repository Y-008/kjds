# 旧核心账数值完整性验证

- 日期：2026-07-17
- Gate：G-1
- 数据库：一次性 PostgreSQL `kjds_g1_smoke`
- Alembic head：`20260717_0034`
- 完整回归：127 passed
- G-1：PASS
- 报告：`.runtime/G1_VERIFICATION.json`

## 覆盖范围

`20260717_0034` 为以下旧核心账增加 7 条 CHECK：

1. `orders`：数量为正、收入非负、FX 为正、数值有限、币种为 ASCII 三字母；
2. `charges`：金额非负、FX 为正、数值有限、币种为 ASCII 三字母；
3. `market_observations`：观测值有限、置信度在 0–1；
4. `opportunities`：机会分在 0–100；
5. `growth_experiments`：预算和止损为正，且止损不超过预算；
6. `decision_recommendations`：可选 CM3 预期增量必须有限；
7. `sample_purchase_orders`：数量和单价为正、币种为 ASCII 三字母。

服务入口使用仅依赖标准库的 `finite_decimal`/`ascii_currency` 收口订单、费用、市场情报、旧增长实验和自动化建议，不引入通用 Money 框架。

## 绕过服务层验证

PostgreSQL 拒绝了 7 类非法直写：

- 订单收入为 `NaN`；
- 费用金额为负；
- 市场置信度为 `NaN`；
- 机会分超过 100；
- 止损超过预算；
- 建议预期值为 `NaN`；
- 样品采购单价为负。

验证器只在一次性数据库创建最小合法核心记录，攻击在回滚事务内进行，最后删除种子记录；不会污染后续 API 或经营校准结果。

## 完整 G-1

- 0034 从空库升级、回退到 0024、再升级：PASS。
- Ruff：PASS。
- Pytest：127 passed；仅有既存 Starlette/httpx 弃用警告。
- Next.js production build：PASS。
- API、治理、因果实验、执行/回滚、采购、财务、Web 代理：PASS。
- 进程、数据库、文件清理：PASS。

## 结论与边界

当前 ORM 显式 NUMERIC 列已完成一轮结构完整性审计。该结论只表示非法数值、范围和局部算式能在入口/数据库被阻止，不表示真实 Ozon 费用字典、银行入账、税务、币种换算、结算日或舍入政策已经正确。下一阶段必须用真实业务文件冻结口径。

0034 尚未取得新的备份恢复复演：当前环境缺少 `pg_dump`/`pg_restore` 且无 Docker 控制权限，恢复证据仍停留在 0029。
