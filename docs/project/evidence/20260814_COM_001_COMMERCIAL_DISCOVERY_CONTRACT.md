# COM-001 商业发现契约内核 Evidence

## 1. 结论

COM-001 建立了一个只读、prep-only、exact-scope 的商业发现深模块
`GovernedCommercialDiscovery`，从 `20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md`
冻结了首个 ICP 客户资格、只读利润真相诊断交付物、C0 合同/DPA/SLA 清单、定价假设与
受控销售话术规则。该内核是只读分类器与合同 fixture：不接入任何客户写、发票、收款、
应收、Fact、FinanceEntry、Approval、Permit、Pilot 或 Outbox 权威；所有价格保持
`not_for_sale`，不制造"已批准"或"可成交"。

- 唯一外部模块接口：`apps/control_plane/commercial_discovery.py`。
- 输出类型：`QualificationResult`、`DiagnosticDeliverable`、`PricingItem`、
  `ChecklistResult`、`SalesCopyResult`。
- 无迁移、无公共 API、无 OpenAPI 变化、无 runtime 聚合、无新依赖、无 outbox。
- 真源仅复用既有只读输入：`docs/project/20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md`
  （5.1 首个 ICP、5.2 价值主张、5.3 产品阶梯、5.5 C0 缺口清单、6. Gate 路线）。

本结果只证明契约确定性，不代表任何真实客户资格、可售性或收款能力。

## 2. 冻结契约

| 字段 | 冻结值 |
|---|---|
| 模块 | `GovernedCommercialDiscovery` |
| 发现契约 | `kjds-commercial-discovery-v1` |
| 客户资格契约 | `kjds-customer-qualification-v1` |
| 利润真相诊断交付契约 | `kjds-profit-diagnostic-deliverable-v1` |
| 合同/DPA/SLA 清单契约 | `kjds-contract-dpa-sla-checklist-v1` |
| 销售话术契约 | `kjds-sales-copy-v1` |
| ICP 国家 | `cn` |
| ICP Ozon 店铺数 | `1..3` |
| ICP 活跃 SKU | `50..500` |
| ICP 团队规模 | `3..20` |

## 3. 资格判定

状态优先级：`rejected > deferred > needs_evidence > qualified`；任何未知字段进入
`unknowns` 并落到 `needs_evidence`，绝不默认成"是"或零。

| 拒绝条件（任一命中即 rejected） | 触发输入 |
|---|---|
| `no_real_account` | `has_real_account == False` |
| `refuses_evidence` | `provides_evidence == False` |
| `sells_prohibited_or_infringing` | `sells_prohibited_or_infringing == True` |
| `requests_blackhat` | `requests_blackhat == True` |
| `requests_unapproved_direct_write` | `requests_unapproved_direct_write == True` |
| `demands_profit_guarantee` | `demands_profit_guarantee == True` |

| 延期条件（无拒绝且命中即 deferred） | 触发输入 |
|---|---|
| `novice_insufficient_data_or_payment` | `is_novice_insufficient_data_or_payment == True` |
| `large_enterprise_requirements` | `has_large_enterprise_requirements == True` |

- 拒绝条件优先级高于延期与未知：即使同时命中延期或缺失字段，拒绝仍居首。
- 布尔拒绝/延期输入类型错误（如字符串代替布尔）fail-closed；数字 ICP 字段类型错误
  （字符串代替整数）fail-closed；敏感值（token/密码等）fail-closed。
- `qualified` 要求 country=`cn`、三个数字 ICP 字段全落在冻结区间、六个拒绝输入全部
  干净、两个延期标志均未命中。

## 4. 只读诊断交付物

| 字段 | 冻结值 |
|---|---|
| scope | `("single_store", "read_only")` |
| outputs | `("data_quality_report", "sku_profit_gap")` |
| delivery_format | `one_delivery_meeting` |
| success_condition | `customer_accepted_problem_and_next_action_within_5_working_days` |
| not_for_sale | `True` |
| external_write_allowed | `False` |

## 5. 定价假设（全部 not_for_sale）

| 产品 | 范围 | 价格假设 | 单位 | 说明 |
|---|---:|---|---|---|
| `profit_truth_diagnostic` | 单店只读 | 4,800 CNY | per_run | 一次交付会 |
| `design_partner_pilot` | 单客户隔离单店 | 19,800 CNY | per_store | 90 天托管验证 |
| `team_edition` | 多角色工作台 | 39,900 CNY | per_store_per_year | 实施/连接器另计 |
| `enterprise` | — | None | None | G7 后单独报价 |

C0 通过前不得报价成交、收款或形成应收；`not_for_sale` 恒真。

## 6. 合同/DPA/SLA 清单

8 项 `CONTRACT_CHECKLIST_ITEMS` 全部初始 `UNKNOWN`，不制造"已批准"：

`contract`、`dpa`、`privacy`、`data_processing`、`data_retention_deletion`、
`security_disclosure`、`incident_notification`、`support_sla`。

## 7. 受控销售话术

- 禁止 claims：`guaranteed_profit`、`fully_automated_store_takeover`、
  `ai_guaranteed_growth`、`market_leader`。
- 允许 framing：`traceable_sku_cash_profit`、`controlled_actions`、
  `evidence_first`、`loss_and_gap_discovery`。
- 未识别短语进入 `unknowns`；`external_write_allowed` 恒 `false`。

## 8. 控制边界

`zero_authority()` 全部 `false`，含常规十项与 C0 相关三项：

`formal_fact` / `finance_entry` / `approval` / `permit` / `pilot` / `outbox` /
`canonical_graph_write` / `dependency_install` / `network` / `external_write` /
`invoice` / `payment` / `receivable`。

## 9. UNKNOWN / 外部阻断

- 首批十个合格客户访谈（痛点强度、付费意愿、采购流程、价格敏感度）尚未取得。
- 实际经营主体、进口主体、税务方案、Ozon 合同与可持续收款路径仍 UNKNOWN。
- C0 的 Release、隔离生产部署、最小 Billing/Usage/Entitlement、发票退款、单位经济、
  合同/DPA、SLA、备份恢复与退出导出全部未验收，故本内核不形成应收。

## 10. 验证

- `tests/test_commercial_discovery.py` 24 passed。
- Ruff check（E/F/I/UP/B/SIM，忽略 E501）PASS。
- Secret scan PASS（1506 非忽略工作树文件、1646 历史路径）。
- 回归：`test_active_workstream_assignments.py` 24 passed；社会电商 lane 59 passed；
  `test_requirements_traceability.py` 25 passed（隔离 basetemp）。
