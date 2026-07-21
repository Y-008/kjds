# 2026-07-18 PostgreSQL 恢复演练

| 项目 | 结果 |
|---|---|
| 状态 | PASS |
| 来源数据库 | `kjds_g1_smoke`（一次性） |
| 隔离目标 | `kjds_g1_restore` |
| 备份格式 | PostgreSQL custom dump |
| SHA-256 | `655fe16eb5d174e93f9c57df55d4b97594956ebeb4882e81192e846994b2185c` |
| 恢复后 Alembic head | `20260717_0035` |
| 恢复耗时 | 4.307 秒 |
| G-1 字段 | `backup_restore=true` |

## 关键数据对账

| 表 | 源库 | 恢复库 | 结果 |
|---|---:|---:|---|
| `products` | 4 | 4 | 一致 |
| `orders` | 0 | 0 | 一致 |
| `evidence_records` | 19 | 19 | 一致 |
| `read_only_pilot_runs` | 1 | 1 | 一致 |

## 验证范围

1. G-1 在真实 PostgreSQL 临时源库完成迁移回放和全业务 smoke。
2. `backup-postgres.ps1` 使用 `pg_dump --format=custom` 生成备份和 SHA-256 清单。
3. `restore-postgres.ps1` 复验哈希后恢复到独立目标库，并校验迁移 head。
4. 源库与恢复库的 `products`、`orders`、`evidence_records`、`read_only_pilot_runs` 精确行数一致。
5. API/Web/138 项测试继续通过。
6. 源库、恢复库、临时备份、API/Web 进程全部清理；G-1 三项 cleanup 均为 `true`。

## 机器证据

- `.runtime/G1_VERIFICATION.json`
- `.runtime/RESTORE_VERIFICATION.json`

## 保留边界

本演练证明本地当前结构和关键样本数据可恢复，不代表已经具备自动备份、异地加密副本、法定保留周期、生产 RPO/RTO 或全表业务对账。首次托管生产部署前仍须补齐这些能力。
