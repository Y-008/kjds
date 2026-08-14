# COM-002 商业 Pilot 部署契约 Evidence

## 1. 结论

COM-002 在 `commercial_lifecycle.py`（商业生命周期/收退款）与 `customer_exit_export.py`
（退出/返还/删除）之外，新增了只读、prep-only、exact-scope 的单客户交付底座契约内核
`GovernedCommercialDeployment`，冻结 C0 的"托管双客户负向隔离、真实 TLS/Secrets/备份恢复、
升级回滚、全量导出、健康与 RPO/RTO"为确定性就绪清单与双租户负向隔离不变量。该内核是
契约与分类器：不执行任何真实部署、秘密写入、Fact、FinanceEntry、Approval、Permit、Pilot、
Invoice、Payment、Receivable 或 Outbox；未提供 Evidence 的控制项以 `UNKNOWN` 报告，
绝不伪造为 ready。

- 唯一外部模块接口：`apps/control_plane/commercial_pilot_deployment.py`。
- 输出类型：`DeploymentAssessment`、`IsolationCheck`。
- 无迁移、无公共 API、无 OpenAPI 变化、无 runtime 聚合、无新依赖、无 outbox。
- 真源仅复用 C0 缺口清单与 `20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md`
  5.5 P0（一客户一套应用、一数据库、一密钥域；TLS/秘密/备份恢复/升级回滚/全量导出；
  隔离与恢复验收）与 6.2 安全可靠通过线（0 跨客户/跨店泄漏、0 未授权外部写、恢复演练）。

本结果只证明契约确定性，不代表任何真实托管部署、隔离或恢复演练已执行。

## 2. 冻结契约

| 字段 | 冻结值 |
|---|---|
| 模块 | `GovernedCommercialDeployment` |
| 部署契约 | `kjds-commercial-pilot-deployment-v1` |
| 隔离契约 | `kjds-commercial-isolation-v1` |
| 真实部署 admitted | `false` |
| external_write_allowed | `false` |

## 3. 就绪清单（12 项 DEPLOYMENT_CONTROLS）

每项状态只能为 `IMPLEMENTED`（有 Evidence 内容哈希）/ `CONTRACT_ONLY`（已声明未举证）/
`UNKNOWN`（未声明）。全部 `IMPLEMENTED` 才 `ADMITTED`/`ready=True`。

1. `single_customer_app_instance`
2. `single_customer_database`
3. `single_customer_key_domain`
4. `single_customer_storage_namespace`
5. `tls_termination`
6. `secrets_management`
7. `backup_configured`
8. `restore_verified`
9. `upgrade_rollback_verified`
10. `full_data_export_verified`
11. `health_monitoring`
12. `rpo_rto_declared`

## 4. 双客户负向隔离

`check_isolation` 对两个租户做确定性不变量校验：`customer_id`、`database_name`、
`key_domain`、`storage_namespace` 任一碰撞即 `isolation_ok=False` 并记录具体违规；
`external_write_allowed` 恒 `false`。这冻结"0 跨客户/跨店泄漏"的机器可验证子集。

## 5. 控制边界

`zero_authority()` 全部 `false`：常规十项 + `invoice`/`payment`/`receivable` +
`external_deployment_execution`。

## 6. UNKNOWN / 外部阻断

- 托管目标与 RPO/RTO 决策未定；真实双客户隔离部署、TLS/Secrets、备份恢复与升级回滚演练
  尚未在真实环境执行。
- 支付/开票/税务合同输入、Contract/DPA/SLA 复核权威仍未提供。
- C0 `not_for_sale` 未解除；本内核不形成任何真实部署、秘密写入、发票、收款或应收。

## 7. 验证

- `tests/test_commercial_pilot_deployment.py` 18 passed。
- Ruff check（E/F/I/UP/B/SIM，忽略 E501）PASS。
- Secret scan PASS（1512 非忽略工作树文件、1652 历史路径）。
- 商业 lane 聚焦回归 118 passed/1 skipped（active_workstream + commercial_lifecycle +
  commercial_discovery + customer_exit_export + commercial_pilot_deployment）。
