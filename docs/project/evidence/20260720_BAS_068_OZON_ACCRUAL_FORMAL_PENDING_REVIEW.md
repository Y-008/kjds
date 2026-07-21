# BAS-068：Ozon 计提原件正式待复核存证

| 元数据 | 值 |
|---|---|
| task_id | BAS-068 |
| requirements | BR-041、BR-052、BR-053 |
| status | DONE_PENDING_REVIEW |
| verified_at | 2026-07-20 |
| database migration | `20260719_0037` |
| import_id | `imp_76eab9701e954896a6f67ccdbb845cb6` |
| evidence_id | `evd_902fe12a454e4703b88b6ad7314ed652` |

## 1. 写入前恢复点

本机 PostgreSQL 写入前实际处于 `20260718_0036`。先生成自定义格式备份及 SHA-256 清单，再升级到 `20260719_0037`。有效恢复点：

- archive：`.runtime/pre-accrual-import-backup/kjds-hermes-20260720T015342Z.dump`
- manifest：同名 `.manifest.json`
- SHA-256：`f66856f67106aa94ae59761466419f1249a8fd6de590adac4d3cc56370ac0827`
- source head：`20260718_0036`

备份保留在 Git 忽略运行目录，不提交数据库内容。

写入后的 Windows PowerShell 兼容性复验又生成 `20260719_0037` 备份，使用原先失败的 `powershell.exe` 入口成功计算 SHA-256；随后恢复到隔离数据库 `kjds_restore_accrual_check`，版本为 `20260719_0037`，上述 import 与 Evidence 各恢复 1 行，最终清理隔离库。备份/恢复脚本在 `Get-FileHash` 不可用时改用 .NET SHA-256，不新增外部依赖。

## 2. 正式导入结果

- 原件：`Отчет по начислениям_01.10.2025-31.10.2025.xlsx`
- 报告期间：`2025-10-01` 至 `2025-10-31`
- SHA-256：`489d4518e8e8c1f00c135cd1380ed636ff5e3ee1768182a9146b3cc4b1dcae68`
- 字节数：4,459
- 类型：`ozon_accrual`
- 行数：15；接收 15；拒绝 0
- Evidence Blob 完整性：通过
- 血缘：Evidence 以 `source_for` 指向上述 import

重复上传相同字节和相同报告期间返回同一 import，不重复写入。

## 3. 失败关闭状态

- 来源复核：`pending`
- 独立复核次数：0
- `review_ready=false`
- `ozon_accrual` 正式事实：0
- Finance Entry：0
- 应计分类读取：HTTP 422，原因是尚未取得独立接受的来源复核

因此本次动作只把原件从磁盘样本推进为正式待复核 Evidence/import，没有批准来源、分类、事实晋升或利润入账。

## 4. 下一人工动作

由与 `codex-accrual-importer` 不同的真实 Reviewer、Compliance 或 Admin 在经营界面核对：真实账户导出、期间一致、非公开样例、导出完整。接受后仍须对 9 个真实计提类型逐项批准会计分类，随后才能晋升为控制事实；控制事实仍不自动生成财务分录。
