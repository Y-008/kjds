# 2026-07-17 时间、金额与度量完整性验证

- 结果：PASS
- 验证时间：2026-07-17T13:37:50Z–2026-07-17T13:38:54Z
- Git 基线：`1f1d1e6ca75445756570ab14385a5a9a8da8ca14`（工作区另有未提交增量）
- 数据库控制模式：`existing-postgres`，仅操作固定一次性数据库 `kjds_g1_smoke`
- Alembic head：`20260717_0030`
- 完整回归：121 passed
- G-1 报告：`.runtime/G1_VERIFICATION.json`

## 验证内容

1. `SupplierOffer` 拒绝无时区 `captured_at`、`NaN`/无穷数值、非正价格/汇率/重量/MOQ 和负尺寸/物流成本，并把币种和时间规范化。
2. `ProfitInputs` 拒绝非有限金额、负成本、越界费率和使盈亏平衡分母小于等于零的组合费率。
3. Alembic 0030 完成升级、回滚、再升级；`source_offers` 与 `profit_scenarios` 共存在 11 条新增 CHECK 约束。
4. PostgreSQL 验证脚本直接绕过服务层，尝试写入负价格、`NaN` 价格和负国内物流成本，三次均收到完整性错误。
5. Ruff、121 项测试、Next.js build、API health/auth、Web smoke、事务 Outbox 和运行目录/临时数据库清理全部通过。

## 证据输出

```text
database: kjds_g1_smoke
rejected: negative_unit_price, nan_unit_price, negative_logistics
constraint_count: 11
sourcing_numeric_integrity: true
migration_replay: true
cleanup_processes/database/files: true
```

## 未覆盖边界

- 本证据只覆盖供应商报价与利润场景第一批，不代表所有历史金额表均已完成同级审计。
- 尚未取得 Ozon 真实费用、结算、银行和财务批准的 FX/舍入口径；不能把工程约束当作真实经营利润证明。
- PostgreSQL 恢复演练现有证据仍停留在 0029；0030 恢复复演需要可用的 `pg_dump`/`pg_restore` 或 Docker 控制能力后补做。
