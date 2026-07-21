# 2026-07-17 Ozon 导入与财务数值完整性验证

- 结果：PASS
- 验证时间：2026-07-17T14:03:11Z–2026-07-17T14:04:09Z
- Git 基线：`1f1d1e6ca75445756570ab14385a5a9a8da8ca14`（工作区另有未提交增量）
- 数据库控制模式：`existing-postgres`，仅操作固定一次性数据库 `kjds_g1_smoke`
- Alembic head：`20260717_0031`
- 完整回归：123 passed
- G-1 报告：`.runtime/G1_VERIFICATION.json`

## 验证内容

1. Ozon `ozon-v1` 合同拒绝 `NaN`/无穷金额与数量，以及非 ASCII 三字母币种，带时区时间继续规范化为 UTC。
2. 财务服务在持久化前拒绝非有限 FX、财务分录金额、对账容差、现金计划金额/概率和现金预测期初余额。
3. `20260717_0031` 为 `fx_rates`、`finance_entries`、`reconciliation_runs` 和 `cash_plan_items` 增加 5 条 CHECK 约束。
4. PostgreSQL 验证脚本绕过服务层写入 `NaN` FX、`NaN` 财务分录、`NaN` 对账容差和大于 1 的现金计划概率，四次均被拒绝。
5. 0031 升级、回滚到 0024、再升级，以及 Ruff、123 项测试、Web/API smoke、事务 Outbox、供应商约束和清理全部通过。

## 证据输出

```text
database: kjds_g1_smoke
rejected: nan_fx_rate, nan_finance_amount, nan_reconciliation_tolerance, cash_probability_above_one
constraint_count: 5
finance_numeric_integrity: true
migration_replay: true
cleanup_processes/database/files: true
```

## 未覆盖边界

- 工程约束不能替代 Ozon 真实费用字典、银行格式、FX 来源与会计舍入口径审批。
- 允许正负财务分录，因为方向由分录类型和费用映射解释；本批只拒绝非有限值和非法概率/容差。
- 0031 的备份恢复复演仍受当前环境缺少 `pg_dump`/`pg_restore` 与 Docker 控制权限阻塞；现有恢复证据停留在 0029。
