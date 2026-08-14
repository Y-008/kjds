# COM-002 C0 商业 Pilot Gate 契约 Evidence

## 1. 结论

COM-002 以 `GovernedCommercialGate` 作为软件轮 capstone，把 GTM 合同中"软件轮唯一放行
目标 `C0 Commercial Pilot Gate`"冻结为确定性九维聚合：稳定 Release、隔离生产部署、最小
Billing/Usage/Entitlement、发票退款生命周期、单位经济、合同/DPA/隐私、SLA/事故、备份恢复
演练、退出导出/删除。每一维引用唯一的既有子模块（不重复实现），仅以提供的 Evidence 内容
哈希判定 `IMPLEMENTED/CONTRACT_ONLY/UNKNOWN`。该内核永远只报告 `not_for_sale=True` 与
`ready_to_sell=False`，不授予任何销售权威，不接入 Fact、FinanceEntry、Approval、Permit、
Pilot、Invoice、Payment、Receivable、Outbox 或外部写。

- 唯一外部模块接口：`apps/control_plane/commercial_gate.py`。
- 输出类型：`GateAssessment`。
- 无迁移、无公共 API、无 OpenAPI 变化、无 runtime 聚合、无新依赖、无 outbox。
- 真源复用：`20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md` 5.5 P0 与 6. Gate
  （C0 验收标准），并引用 `release_provenance` / `commercial_pilot_deployment` /
  `commercial_lifecycle` / `capability_economics` / `commercial_discovery` /
  `customer_exit_export`。

本结果只证明契约确定性；即使九维全部 `IMPLEMENTED`，也不代表 C0 已由经营负责人放行或可销售。

## 2. 冻结契约

| 字段 | 冻结值 |
|---|---|
| 模块 | `GovernedCommercialGate` |
| Gate 契约 | `kjds-c0-commercial-pilot-gate-v1` |
| 维度状态 | `IMPLEMENTED / CONTRACT_ONLY / UNKNOWN` |
| not_for_sale | `True`（恒） |
| ready_to_sell | `False`（恒） |
| external_write_allowed | `False` |

## 3. 九维聚合与模块引用

| 维度 | 引用模块 |
|---|---|
| `stable_release` | `release_provenance` |
| `isolated_production_deployment` | `commercial_pilot_deployment` |
| `minimal_billing_usage_entitlement` | `commercial_lifecycle` |
| `invoice_refund_lifecycle` | `commercial_lifecycle` |
| `unit_economics` | `capability_economics` |
| `contract_dpa_privacy` | `commercial_discovery` |
| `sla_and_incident` | `commercial_discovery` |
| `backup_restore_drill` | `commercial_pilot_deployment` |
| `exit_export_deletion` | `customer_exit_export` |

九维全部 `IMPLEMENTED` 才 `gate_pass=True`/`status=PASS`；否则 `BLOCKED`。缺 Evidence 的维度
进入 `unknowns`，绝不伪造为已验收。

## 4. 控制边界

`zero_authority()` 全部 `false`：常规十项 + `invoice`/`payment`/`receivable` + `sales_authority`。

## 5. UNKNOWN / 外部阻断

- 稳定 Release、隔离部署、Billing/Entitlement、发票退款、单位经济、Contract/DPA/SLA、
  备份恢复与退出导出/删除的真实 Evidence 尚未齐备。
- 托管目标与 RPO/RTO、支付/开票/税务、Contract/DPA/SLA 复核权威等外部输入仍未提供。
- C0 `not_for_sale` 未解除；本内核不形成任何销售权威、发票、收款或应收。

## 6. 验证

- `tests/test_commercial_gate.py` 11 passed。
- Ruff check（E/F/I/UP/B/SIM，忽略 E501）PASS。
- Secret scan PASS（1521 非忽略工作树文件、1661 历史路径）。
- 商业 lane 聚焦回归 154 passed/1 skipped（active_workstream + commercial_discovery +
  commercial_lifecycle + customer_exit_export + commercial_pilot_deployment +
  commercial_gate + requirements_traceability）。
