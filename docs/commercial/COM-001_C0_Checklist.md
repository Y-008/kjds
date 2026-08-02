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
| Billing/Usage/Entitlement | 客户订阅、用量、配额、权益和 `active/grace/read_only/closed` 由服务端执行 | 产品蓝图只有边界，没有生产实现 | MISS |
| Invoice/Payment/Refund | 客户应收、发票、收款、退款和争议状态可审计 | 现有 Accounts Payable 是供应商应付，只能借鉴治理模式，不能证明 SaaS 客户计费 | MISS |
| 客户单位经济 | 每客户 AI、媒体、存储、基础设施和人工支持成本可计量 | 现有卖家利润账本不等于 SaaS 服务单位经济 | MISS |
| Contract/DPA | 服务协议、DPA、隐私、保留/删除、事故通知、退出和数据返还可评审 | 当前只有战略边界，没有可用合同/DPA | MISS |
| 客户支持 SLA | 支持时间、首响、升级、状态页、事故沟通和赔偿边界明确 | 经营应付/结算 SLA 不能证明软件客户支持 SLA | MISS |

结论：`PASS=0`、`PARTIAL=3`、`MISS=5`、`UNKNOWN=0`，C0 为 `NO-GO`。

## 证据与限制

- [Ultimate Product Blueprint](../project/ULTIMATE_PRODUCT_BLUEPRINT.md)
- [双轮商业化与俄罗斯 GTM 合同](../project/20260802_DUAL_ENGINE_COMMERCIALIZATION_AND_RUSSIA_GTM.md)
- [M0 Truth/Governance Evidence](../project/evidence/20260727_M0_TRUTH_GOVERNANCE.md)
- [Ozon Pilot Offline Preflight](../project/evidence/20260719_BAS_033_OZON_PILOT_OFFLINE_PREFLIGHT.md)
- [PostgreSQL Restore Drill](../project/evidence/2026-07-17-postgres-restore-drill.md)
- [Channel-account Governance](../project/evidence/20260801_BAS_160_CHANNEL_ACCOUNT_GOVERNANCE.md)

现有 Evidence 只能支持相关模式和边界，不能自动把 `PARTIAL/MISS` 晋升为 `PASS`。
