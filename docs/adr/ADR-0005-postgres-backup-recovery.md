# ADR-0005：PostgreSQL 备份与恢复基线

- 状态：Accepted
- 日期：2026-07-17
- 范围：本地/单机 PostgreSQL；不等同于托管生产灾备

## 决策

G0/G1 阶段使用 PostgreSQL 官方 `pg_dump` 自定义格式与 `pg_restore`，由 `scripts/backup-postgres.ps1` 和 `scripts/restore-postgres.ps1` 包装。每份备份必须同时生成清单，记录 SHA-256、字节数、数据库名、时间和 Alembic head；恢复前强制校验哈希，恢复后强制校验迁移版本。

恢复脚本默认拒绝覆盖默认数据库，只允许显式指定隔离目标；确需覆盖时必须传入 `-AllowDefaultDatabase`。演练报告写入 `.runtime/RESTORE_VERIFICATION.json`，不写入业务事实账。

默认 G-1 在业务 smoke 完成后备份临时源库，恢复到独立数据库，校验 Alembic head，并比较商品、订单、证据和只读运行四张关键表的精确行数。源库、恢复库和临时备份均须在报告落盘前清理。

## 当前目标

- 开发基线 RPO：最近一次成功备份；当前未配置自动计划，不能承诺固定时间窗口。
- 开发基线 RTO：人工发起后完成哈希校验、恢复和 Alembic head 校验；以每次演练实测时间为准。
- 进入托管环境前：再确定加密、异地副本、自动调度、保留周期、密钥恢复、告警和正式 RPO/RTO。

## 不采用

- 不在 G0/G1 引入独立备份平台或 Kubernetes operator。
- 不把 Docker volume 复制称为一致性数据库备份。
- 不允许没有清单或哈希不一致的文件进入恢复流程。

## 回滚

删除两个脚本和本 ADR 即可；数据库结构与运行时服务不受影响。
