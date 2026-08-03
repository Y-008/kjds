# COM-001 C0 商业放行清单

目标：证明最小商业 Pilot 已具备可发布、可隔离、可计费、可支持和可退出条件。
全部项目达到 `PASS` 前保持 `not_for_sale`。

## 状态

- `PASS`: 证据完整且满足商业条件。
- `PARTIAL`: 有相关工程证据，但生产商业边界未完成。
- `MISS`: 已确认不存在所需商业能力。
- `UNKNOWN`: 尚未完成足够审计，不能判断。

## 当前检查

| 区域 | 必须成立 | 当前事实 | 状态 |
|---|---|---|---|
| Release | 版本、镜像、变更日志、迁移清单、SBOM、验收报告、回滚标签一致 | 有工程验证与当前提交，但大量工作树尚未形成稳定 Release | PARTIAL |
| 单客户生产隔离 | 一客户一应用/数据库/密钥域，零跨客户泄漏，作用域回收可验证 | exact-scope 与渠道治理可复用；尚未证明生产单客户拓扑 | PARTIAL |
| TLS/Secrets/Backup/Restore | TLS、秘密管理、自动备份、生产恢复、RPO/RTO 和恢复哈希可复验 | 当前 Compose/本地恢复演练不等于生产部署和生产灾备 | PARTIAL |
| Billing/Usage/Entitlement | 客户订阅、用量、配额、权益和 `active/grace/read_only/closed` 由服务端执行 | 已有 exact-scope 内核、持久事件账本和内部 API；尚无生产持久权益执行、公开路由和真实客户验收 | PARTIAL |
| Invoice/Payment/Refund | 客户应收、发票、收款、退款和争议状态可审计 | 已有 invoice/payment-attempt/refund/tax 追加式事件与退款上限校验；尚无真实 PSP/银行、开票、退款、拒付和税务闭环 | PARTIAL |
| 客户单位经济 | 每客户 AI、媒体、存储、基础设施和人工支持成本可计量 | 现有卖家利润账本不等于 SaaS 服务单位经济 | MISS |
| Contract/DPA | 服务协议、DPA、隐私、保留/删除、事故通知、退出和数据返还可评审 | 当前只有战略边界，没有可用合同/DPA | MISS |
| 客户支持 SLA | 支持时间、首响、升级、状态页、事故沟通和赔偿边界明确 | 经营应付/结算 SLA 不能证明软件客户支持 SLA | MISS |
| 退出导出与删除 | 客户可导出约定数据和审计引用，完成返还、保留、删除与关闭复验 | Pilot 范围已有文字边界；尚无可执行导出包、删除/保留记录和退出演练 Evidence | MISS |

结论：`PASS=0`、`PARTIAL=5`、`MISS=4`、`UNKNOWN=0`，C0 为 `NO-GO`。

## 总控执行包

| 顺序 | 执行包 | 唯一目标 | 退出证据 | 当前约束 |
|---|---|---|---|---|
| 1 | `BAS-175 Release provenance` | 固定一个 API/Web 发布物的 commit、migration head、镜像摘要、SBOM/AI-BOM 与回滚标识 | 可重复验证的 provenance 和无 secret SBOM | 不把供应链证明冒充稳定 Release 或商业放行 |
| 2 | `COM-002 Hosted isolation and recovery` | 在选定托管目标完成两客户负向隔离、真实 TLS/Secrets、连续备份、异地保留和 RPO/RTO 恢复 | 托管拓扑、隔离测试、备份告警、计时恢复与清理报告 | 需要经营负责人确认托管目标和 RPO/RTO；确认前只做无凭证准备 |
| 3 | `COM-002 Commercial lifecycle` | 把现有内部账本接入选定支付/开票/退款/税务合同并完成沙箱到人工复核闭环 | invoice→payment→refund/close 的追加式 Evidence、幂等回读与财务签字 | 需要收款主体、支付渠道、开票与税务口径；不得由工程猜测 |
| 4 | `COM-001/002 Legal, support and exit` | 冻结服务协议、DPA、SLA、数据返还/导出/保留/删除与事故通知 | 独立法务/经营评审记录、退出导出和删除演练 | 模板不等于法律意见，不得先成交后补合同 |
| 5 | `COM-002 Unit economics` | 从托管演练计量每客户基础设施、模型、存储、实施和支持成本 | 单客户成本账、容量假设、毛利敏感性与负责人签字 | 未有真实演练和工时时保持 `MISS` |

以上按 Gate 提升率排序。任一执行包只能提升自己覆盖的检查项，不得一次 Evidence
批量晋升多个未实测区域。

## 证据与限制

- [Ultimate Product Blueprint](../project/ULTIMATE_PRODUCT_BLUEPRINT.md)
- [双轮商业化与俄罗斯 GTM 合同](../project/20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md)
- [M0 Truth/Governance Evidence](../project/evidence/20260727_M0_TRUTH_GOVERNANCE.md)
- [Ozon Pilot Offline Preflight](../project/evidence/20260719_BAS_033_OZON_PILOT_OFFLINE_PREFLIGHT.md)
- [PostgreSQL Restore Drill](../project/evidence/2026-07-17-postgres-restore-drill.md)
- [Channel-account Governance](../project/evidence/20260801_BAS_160_CHANNEL_ACCOUNT_GOVERNANCE.md)
- [C0-001 Commercial Pilot Deployment Preflight](../project/evidence/20260802_C0_001_COMMERCIAL_PILOT_DEPLOYMENT_PREFLIGHT.md)
- [C0-002 Billing / Usage / Entitlement Kernel](../project/evidence/20260802_C0_002_BILLING_USAGE_ENTITLEMENT_KERNEL.md)
- [C0-003 Commercial Lifecycle Ledger](../project/evidence/20260802_C0_003_COMMERCIAL_LIFECYCLE_LEDGER.md)

现有 Evidence 只能支持相关模式和边界，不能自动把 `PARTIAL/MISS` 晋升为 `PASS`。
