# COM-002 客户退出 / 数据返还 / 删除契约 Evidence

## 1. 结论

COM-002 在现有 `commercial_lifecycle.py`（active/grace/read_only/closed 商业生命周期）之外，
新增了一个只读、prep-only、exact-scope 的客户退出深模块 `GovernedCustomerExit`，冻结 C0 的
"退出导出与删除演练"为确定性状态机：`requested → export_prepared → export_verified →
deletion_planned → deletion_verified → closed`。该内核是契约与分类器，不执行任何真实数据
导出、删除、客户写、Fact、FinanceEntry、Approval、Permit、Pilot、Invoice、Payment、Receivable
或 Outbox；缺失的导出内容以 `UNKNOWN` 报告，绝不伪造。

- 唯一外部模块接口：`apps/control_plane/customer_exit_export.py`。
- 输出类型：`ExitRequest`、`ExportManifest`、`DeletionPlan`、`ExitReceipt`。
- 无迁移、无公共 API、无 OpenAPI 变化、无 runtime 聚合、无新依赖、无 outbox。
- 真源仅复用 C0 缺口清单与 `20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md`
  5.5（退出/数据返还流程、数据保留/删除）与 6. Gate（C0 退出导出与删除演练）。

本结果只证明契约确定性，不代表真实客户退出、导出或删除已执行。

## 2. 冻结契约

| 字段 | 冻结值 |
|---|---|
| 模块 | `GovernedCustomerExit` |
| 退出契约 | `kjds-customer-exit-export-v1` |
| 状态机 | `requested / export_prepared / export_verified / deletion_planned / deletion_verified / closed` |
| 导出数据类 | `operating_products / finance_orders / profit_projections / evidence_objects / customer_pii` |
| 保留数据类 | `deidentified_governance_audit_trail` |
| 真实执行器 admitted | `false` |
| external_write_allowed | `false` |

## 3. 状态机与验收证明

1. **退出请求**：`open_exit_request` 校验 customer_id（幂等 token）、exact scope、
   authority、带时区时间与 retention policy；缺省 retention 为仅保留去标识治理审计轨迹，
   并记 `retention_policy` 为 UNKNOWN 以显式提示未显式签署保留策略。
2. **导出清单**：`prepare_export` 冻结五类数据类，逐类输出 `EXPORTED/UNKNOWN`、
   `record_count` 与 `content_sha256`；未知内容哈希与缺类进入 `unknowns`，绝不默认已导出。
3. **导出核验**：`readback(manifest, observed=...)` 输出 `PENDING/VERIFIED/INVALIDATED`，
   以 manifest 内容哈希为唯一完整性质证。
4. **删除计划**：`plan_deletion` 以 manifest 全部数据类为删除目标，保留策略只允许
   去标识治理审计轨迹；`external_write_allowed` 恒 `false`。
5. **关闭回执**：`close_exit` 绑定 manifest 与 plan 的客户与内容哈希，输出 `closed`
   回执；跨客户 `customer_mismatch` fail-closed。

## 4. 控制边界

`zero_authority()` 全部 `false`，含常规十项、C0 商业三项与退出/删除两项：

`formal_fact` / `finance_entry` / `approval` / `permit` / `pilot` / `outbox` /
`canonical_graph_write` / `dependency_install` / `network` / `external_write` /
`invoice` / `payment` / `receivable` / `external_data_export` / `external_data_deletion`。

## 5. UNKNOWN / 外部阻断

- 真实客户退出、数据全量导出、删除与备份恢复演练尚未在任何真实托管环境执行。
- 托管目标与 RPO/RTO 决策、支付/开票/税务合同输入、Contract/DPA/SLA 复核权威仍未提供。
- C0 `not_for_sale` 未解除；本内核不形成任何客户可写、发票、收款或应收。

## 6. 验证

- `tests/test_customer_exit_export.py` 20 passed。
- Ruff check（E/F/I/UP/B/SIM，忽略 E501）PASS。
- Secret scan PASS（1509 非忽略工作树文件、1649 历史路径）。
- 回归：`test_active_workstream_assignments.py` 24 passed；`test_commercial_lifecycle.py`
  32 passed/1 skipped。
