# 因果策略与能力经济账数值完整性验证

- 日期：2026-07-17
- Gate：G-1
- 数据库：一次性 PostgreSQL `kjds_g1_smoke`
- Alembic head：`20260717_0033`
- 完整回归：125 passed
- G-1 结果：PASS
- 报告：`.runtime/G1_VERIFICATION.json`

## 实现范围

1. 策略阶段增量值、护栏阈值、暴露比例和最小增量值统一拒绝 `NaN`/无穷值。
2. 数值型策略条件遇到非有限实际值或期望值时不匹配，不产生推荐执行资格。
3. 能力经济账只接受三个 ASCII 大写字母的币种代码。
4. `20260717_0033` 增加 5 条 PostgreSQL CHECK：策略阶段值有限、能力账全部数值有限、非收益项非负、净价值算式守恒、币种格式合法。
5. 验证器复用 G-1 API 生成的真实策略—执行—观测—能力评估链，在回滚事务内隔离不可变账本触发器后直接攻击数据库约束，不另造一套平行业务模型。

## PostgreSQL 非法直写验证

以下 5 类写入全部被 PostgreSQL 类型或 CHECK 约束拒绝：

- 策略阶段增量值为 `NaN`；
- 已实现增量价值为 `Infinity`；
- 模型与计算成本为负数；
- `net_value` 与收入、避免损失及成本算式不一致；
- 币种使用非 ASCII 的 `РУБ`。

验证器输出：

```text
rejected_count: 5
constraints: 5
policy_capability_numeric_integrity: true
```

## 完整 G-1 结果

- 0033 从空库升级、回退到 0024、再升级：PASS。
- Ruff：PASS。
- Pytest：125 passed；仅保留现有 Starlette/httpx 弃用警告。
- Next.js 生产构建：PASS。
- API health/auth、因果实验、策略发布、受控执行、执行后观测、能力经济账、事故恢复、Web 代理：PASS。
- 临时进程、数据库和文件清理：PASS。

## 边界

- 本批证明数值结构完整性，不证明真实 Ozon、银行、税务或会计口径正确；这些仍依赖一手文件与财务负责人批准。
- `execution_plans` 没有 NUMERIC 持久化列；`post_execution` 的指标值当前以字符串保存，但服务入口已经拒绝非有限 Decimal。若未来改为 NUMERIC 或进入结算事实，必须补迁移级约束。
- 0033 的备份恢复复演仍受当前环境缺少 `pg_dump`/`pg_restore` 与 Docker 控制权限阻塞；已验证恢复证据仍停留在 0029，不能用本次迁移回放替代恢复演练。
