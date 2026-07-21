# PostgreSQL 备份与恢复运行手册

- 状态：本地开发基线已验证
- 最后演练：2026-07-18
- 决策：`docs/adr/ADR-0005-postgres-backup-recovery.md`

## 备份

```powershell
./scripts/backup-postgres.ps1
```

默认写入被 Git 忽略的 `backups/`，同时生成 `.dump` 与 `.manifest.json`。清单包含 SHA-256、大小、数据库名、UTC 时间和 Alembic head。备份目录不得放 API 密钥、数据库密码或客户导出明文说明。

## 隔离恢复演练

```powershell
./scripts/restore-postgres.ps1 `
  -BackupPath ./backups/kjds-hermes-YYYYMMDDTHHMMSSZ.dump `
  -TargetDatabase kjds_restore_drill
```

脚本先校验清单哈希，再重建目标数据库、执行 `pg_restore`，最后核对 Alembic head；机器报告写入 `.runtime/RESTORE_VERIFICATION.json`。默认拒绝覆盖 `hermes`，避免把演练误当生产恢复。

演练完成并保存报告后，人工删除隔离数据库：

```powershell
docker compose exec -T postgres dropdb -U hermes --if-exists kjds_restore_drill
```

## 放行检查

- `.dump` 与清单同时存在，哈希相符。
- `status=PASS`，恢复版本等于清单中的 `alembic_head`。
- 恢复目标与当前业务数据库隔离。
- 恢复耗时已记录；数据抽查与 API smoke 由对应 Gate 另行执行。

默认 G-1 会自动执行当前迁移 head 的隔离恢复，并比较 `products`、`orders`、`evidence_records`、`read_only_pilot_runs` 行数：

```powershell
pwsh -NoProfile -File ./scripts/verify-g1.ps1
```

机器结果中的 `backup_restore=true`、`backup_restore_counts` 和三项 cleanup 均为真，才算本地恢复门通过。

## 尚未完成

- 自动备份计划、失败告警、异地加密副本。
- 按数据等级制定的保留与销毁周期。
- 托管环境正式 RPO/RTO、密钥恢复和季度演练。
- 恢复后全业务抽样对账；当前只验证数据库可恢复性和迁移版本一致性。
