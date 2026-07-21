# KJDS 项目文档中心

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-DOC-INDEX |
| owner | 项目负责人（待确认） |
| approver | 经营负责人 |
| status | Active |
| version | 4.6 |
| last_reviewed | 2026-07-21 |
| next_review | 2026-07-23 |
| gate | G-1–G8 |

本目录是 KJDS 的项目唯一真源入口。《方案001》保留为研究母稿，不能直接生成开发承诺；任务工作簿保留全部候选任务，但只有本文档中心明确进入阶段门的任务才属于当前执行范围。

## 工程主规格

所有需求、产品边界、三层架构、前后端模式、API 合同、核心流程、权限、Gate、运行和下一执行队列集中在 [MASTER_SPEC.md](MASTER_SPEC.md)。专题文件继续保留细节和证据索引，但新增工作必须先在主规格中找到对应的需求、Gate 和验收标准。

阅读入口：[`KJDS_项目总纲与实时方法论.docx`](../planning/KJDS_项目总纲与实时方法论.docx) 汇总了章程、方法论、阶段门、当前 P0、运行手册和模板，适合评审与打印；日常更新仍应回到下列 Active 文档。

## 真实业务启动入口

Web 控制台首屏的“真实业务启动路径”是当前 G0/G1 的操作入口。它直接读取后端 readiness，不在前端猜测完成状态，并在唯一 `SKU-000` 中同时展示“研究闭环”和“真实经营”。至少 28 天且经独立复核的合格研究原件可以继续候选、模拟利润、ComfyUI、Listing 草稿和审批演练；付款、采购、发布、广告、补货与正式事实晋升另需 Ozon Data，或至少两个独立 Ozon 官方分析入口。历史 Product 不满足新候选 readiness；公开示例、固定测试和第三方信号都不能放行真实经营。

资料准备模板位于 [`web/public/startup/`](../../web/public/startup/)：

- [`g0-governance.csv`](../../web/public/startup/g0-governance.csv)：经营 Owner、独立审批、风险预算和回滚责任；
- [`g0-ozon-access.csv`](../../web/public/startup/g0-ozon-access.csv)：账户范围、只读能力、禁止写操作和收款路径（禁止填写密钥）；
- [`g0-ozon-api-identities.csv`](../../web/public/startup/g0-ozon-api-identities.csv)：现有 API 身份的脱敏引用、调用系统、角色数量、最后使用时间和保留/轮换/撤销决定（禁止填写密钥值）；
- [`candidate-research.csv`](../../web/public/startup/candidate-research.csv)：三个新上新候选各五类固定指标、测量窗口、样本量、原件引用和来源族；
- [`sku-passports.csv`](../../web/public/startup/sku-passports.csv)：三个真实 SKU 的商品、俄罗斯合规和样品质量事实；
- [`sku-media.csv`](../../web/public/startup/sku-media.csv)：每个 SKU 的主图、背面、侧面、细节、配件、包装和比例参照素材，以及来源、授权、时间和哈希引用；
- [`supplier-quotes.csv`](../../web/public/startup/supplier-quotes.csv)：每个 SKU 三家真实报价与实测条件；
- [`finance-reconciliation.csv`](../../web/public/startup/finance-reconciliation.csv)：订单、费用、结算、银行与 FX 最小对账样本。

`web/public/startup/` 是公开空模板，不要直接写入真实经营资料。先创建一个已被 Git 忽略、不会被 Web 发布的本地工作副本：

```powershell
.\scripts\prepare-startup-package.ps1
```

默认目录是 `.runtime/startup-intake`。如果目录已经存在，命令只补充缺失的新模板，任何已有文件都不会覆盖；它不会读取或输出已填写内容。CSV 中禁止保存密码、API Key、Token、完整银行账号和身份文件。

填写后再校验私密副本：

```powershell
uv run python scripts/validate_startup_package.py .runtime/startup-intake
uv run python scripts/validate_startup_package.py .runtime/startup-intake --require-review-ready
```

CSV 是收集清单，不是事实证明。`status=structurally_valid` 只表示文件名、列、关键行、3 候选×5 指标、3 SKU×3 家报价和每 SKU 七类基础素材覆盖正确；`submission_readiness.status=ready_for_human_intake` 只表示最低必填值、证据引用和候选双来源族已提供。严格模式在任一资料区仍缺输入时返回退出码 3。素材只有在来源、授权、时间、SHA-256 与负责人齐全时才允许标记 `verified`。系统仍要求原文件、不可变证据、人工复核和阶段门决定；预检不会读取引用内容、自动导入、晋升事实或放行 Gate。经营看板下方卡片只反映系统 Evidence、Passport、事实账和审批 readiness，不读取私密 CSV，也不把本地预检结果伪装成系统证据完成。

## 运维基线

> 2026-07-21 当前增量：Alembic 静态头为 `20260721_0040`；329 项 Python、19 项 Web 与 Next.js 生产构建通过。由于本机 Docker daemon 不可用，本次没有重新取得真实 PostgreSQL `upgrade head`、`/health/ready`、advisory lock 并发行为与降级证据；下段的完整 G-1 PASS 是此前运行基线，不能替代本次迁移的上线验证。作用域化 Readiness 与统一授权证据见 [BAS-078/079](evidence/20260721_SKU_000_SCOPED_READINESS_AND_UNIFIED_AUTHORIZATION.md)；Readiness 原件、独立接受证明与当时阻断快照进入现有 DecisionPacket 的证据见 [BAS-080](evidence/20260721_READINESS_EVIDENCE_DECISION_PACKET.md)；同动作/UTC 日串行预留、风险快照绑定和 Worker 双重防篡改见 [BAS-081](evidence/20260721_LIMITED_EXECUTION_AGGREGATE_RISK_RESERVATION.md)。BAS-081 仅覆盖同动作、同币种的保守日预算，店铺、法人、多币种和 13 周现金硬约束仍待真实 Owner 阈值，不能被描述为完整资本风控。

当前验证基线：Alembic `20260720_0038`、317 项 Python 测试、19 项 Web 契约/身份安全测试和完整 G-1 PASS；G-1 已真实通过 PostgreSQL 迁移往返、API/Web 容器健康、研究信号入箱、候选交接和备份恢复。最佳方案已从自由文本升级为结构化决策结果：所有候选逐项比较硬约束、长期风险调整价值、总拥有成本、最大损失、可逆性、见效时间和经营适配度，并记录淘汰理由、敏感性、失效条件、复审时间及反方意见；它仍不自动获得执行权。第三方研究信号收件箱复用现有 Evidence/Blob/Lineage，不增加外部依赖。它可以安全保存萌啦、Seerfar、妙手、51Selling 等来源的手工导出，但固定为辅助资料，不自动创建商品、采购或 Listing；Open API 仍待正式准入。Ozon 工程链已覆盖真实需求报告双人不可变复核、候选录入/复评/三报价交接的同报告绑定、候选资格门、候选证据独立权威复核、候选测量/报价筛选、单 SKU 目标绑定、默认离线预检、显式执行意图、run 一次性执行授权、成功响应检查点/无平台恢复，以及完成前实际 Blob 哈希与 Evidence 合同复验；主动巡检进一步覆盖缺 Blob、哈希和大小不符并幂等升级运维事件。2026-07-20 已取得首份真实 [Ozon 官方计提报表](evidence/20260720_BAS_066_OZON_OFFICIAL_ACCRUAL_EXPORT.md)，15/15 行隔离暂存并精确复算 `−9,943.02 RUB`；系统将其独立识别为 `ozon_accrual`，避免把收入、折扣和补偿误作平台费用。原件已正式存证为待复核导入并具备只读聚合核验包，但尚未由不同身份接受；结算、银行和 FX 链仍不完整。工程对账现已要求复核人独立于原件、分录、费用映射和 FX 的创建/批准者，并按 Blob 哈希隔离平台与银行原件。真实候选的第一阻塞仍是 [Ozon 需求数据访问门](evidence/20260719_SKU_000_OZON_DEMAND_DATA_ACCESS_GATE.md)：公开页只含示例；2026-07-20 实测 Seller 搜索分析虽可读，但报告导出触发 Premium/Premium Lite 且没有取得 28 天原件。进一步核验确认官方 `product-queries` API 只分析我方已有 SKU，不能作为新候选类目需求源，详见 [导出门复验](evidence/20260720_SKU_000_OZON_SELLER_ANALYTICS_EXPORT_GATE.md)。在类目级原件、哈希和独立复核完成前，不得用页面读数、已有 SKU 查询或第三方工具数据填候选。实际成本还必须逐项获得独立权威证明并在所有执行出口复验，估算依据不得冒充 `actual`。非技术复核工作台从服务端读取 15 项唯一权威目录，Operator 只读，Reviewer/Compliance/Admin 提交不可变结论，且不自动触发场景、账务、采购、定价或 Listing 变更。最新工程证据见 [BAS-077](evidence/20260720_BAS_077_ACTUAL_COST_AUTHORITY_WORKBENCH.md)、[BAS-076](evidence/20260720_BAS_076_ACTUAL_COST_AUTHORITY_GATE.md)、[BAS-075](evidence/20260720_BAS_075_RECONCILIATION_DUAL_CONTROL.md)、[BAS-074](evidence/20260720_BAS_074_ACCRUAL_CURRENCY_SIGN_INVARIANTS.md)、[BAS-073](evidence/20260720_BAS_073_OZON_FINANCE_REVIEW_PACKET.md)、[BAS-072](evidence/20260720_BAS_072_ERPNEXT_SIDECAR_CONTRACT.md)、[BAS-071](evidence/20260720_BAS_071_OPEN_SOURCE_ERP_KERNEL_RESEARCH.md)、[BAS-070](evidence/20260720_BAS_070_BEST_SOLUTION_RESULT_LIFECYCLE.md)、[BAS-066](evidence/20260720_BAS_066_OZON_OFFICIAL_ACCRUAL_EXPORT.md)、[BAS-065](evidence/20260720_BAS_065_EVIDENCE_BACKED_EXCEPTION_WORKSPACE.md) 与 [BAS-062](evidence/20260720_BAS_062_RESEARCH_SIGNAL_INBOX.md)；真实 Ozon Pilot、G0、SKU-000 和 OZN-003 仍未放行。

- PostgreSQL 备份与恢复：[07_BACKUP_RECOVERY_RUNBOOK.md](07_BACKUP_RECOVERY_RUNBOOK.md)
- API v1 兼容决策：[ADR-0004](../adr/ADR-0004-api-v1-compatibility.md)
- PostgreSQL 恢复决策：[ADR-0005](../adr/ADR-0005-postgres-backup-recovery.md)
- 证据保留决策：[ADR-0006](../adr/ADR-0006-evidence-retention.md)
- 事务 Outbox 决策：[ADR-0007](../adr/ADR-0007-transactional-outbox.md)
- Outbox 覆盖清单：[registries/outbox_coverage.json](registries/outbox_coverage.json)
- 时间、金额与度量决策：[ADR-0008](../adr/ADR-0008-time-money-domain-semantics.md)
- 端到端关联决策：[ADR-0009](../adr/ADR-0009-end-to-end-correlation.md)
- Ozon 连接器可靠性决策：[ADR-0010](../adr/ADR-0010-ozon-connector-reliability.md)
- Ozon API 身份盘点合同：[BAS-031 验证](evidence/20260718_BAS_031_OZON_API_IDENTITY_INVENTORY.md)
- Ozon 单 SKU 只读目标绑定：[BAS-032 验证](evidence/20260719_BAS_032_OZON_SINGLE_SKU_TARGET_BINDING.md)
- Ozon Pilot 默认离线预检：[BAS-033 验证](evidence/20260719_BAS_033_OZON_PILOT_OFFLINE_PREFLIGHT.md)
- Ozon Worker 显式执行意图：[BAS-034 验证](evidence/20260719_BAS_034_OZON_WORKER_EXECUTION_INTENT.md)
- Ozon run 一次性执行授权：[BAS-035 验证](evidence/20260719_BAS_035_OZON_RUN_REPLAY_GUARD.md)
- Ozon 成功响应检查点与恢复：[BAS-036 验证](evidence/20260719_BAS_036_OZON_RESPONSE_CHECKPOINT_RECOVERY.md)
- Evidence 持续完整性巡检与事件升级：[BAS-038 验证](evidence/20260719_BAS_038_EVIDENCE_INTEGRITY_MONITOR.md)
- Ozon 响应 Evidence 完整性恢复：[BAS-037 验证](evidence/20260719_BAS_037_OZON_RESPONSE_EVIDENCE_INTEGRITY.md)
- 运行身份与密钥扫描决策：[ADR-0011](../adr/ADR-0011-runtime-identity-and-secret-scan.md)

## 唯一真源

| 主题 | 权威文档 | 使用规则 |
|---|---|---|
| 目标、边界、成功定义 | [00_PROJECT_CHARTER.md](00_PROJECT_CHARTER.md) | 其它文档只链接，不复制改写 |
| 经营与工程方法 | [01_LIVE_METHODOLOGY.md](01_LIVE_METHODOLOGY.md) | 每周复审，变更必须留证据和原因 |
| 阶段门与放行标准 | [02_ROADMAP_AND_GATES.md](02_ROADMAP_AND_GATES.md) | Gate 未通过不得用“基本完成”代替 |
| 当前剩余任务与并行调度 | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) | 当前 P0 只来自这里 |
| 项目交接与全部任务状态 | [13_PROJECT_HANDOVER_AND_TASK_STATUS.md](13_PROJECT_HANDOVER_AND_TASK_STATUS.md) | 交接快照；状态变更仍回写任务真源 |
| 决策、来源和未知项 | [04_SOURCE_DECISION_UNKNOWN_REGISTER.md](04_SOURCE_DECISION_UNKNOWN_REGISTER.md) | 事实、假设、决策、未知分开登记 |
| Build / Buy / Reuse | [05_BUILD_BUY_REUSE.md](05_BUILD_BUY_REUSE.md) | 新技术先判断必要性和阶段适配 |
| OpenClaw–Hermes 运维 | [06_OPENCLAW_HERMES_RUNBOOK.md](06_OPENCLAW_HERMES_RUNBOOK.md) | 不记录任何明文密钥 |
| PostgreSQL 备份与恢复 | [07_BACKUP_RECOVERY_RUNBOOK.md](07_BACKUP_RECOVERY_RUNBOOK.md) | 备份清单、哈希校验、隔离恢复和未完成生产条件 |
| 24×7 情报与 Agent OS | [07_CONTINUOUS_INTELLIGENCE_AND_AGENT_OS.md](07_CONTINUOUS_INTELLIGENCE_AND_AGENT_OS.md) | 权威采集、认知晋级、审批边界与里程碑 |
| Grok Build 隔离试点 | [08_GROK_BUILD_PILOT.md](08_GROK_BUILD_PILOT.md) | 安装证据、使用边界、基准与超越标准 |
| 跨境 SaaS 竞品能力借鉴 | [11_COMPETITOR_CAPABILITY_BENCHMARK.md](11_COMPETITOR_CAPABILITY_BENCHMARK.md) | 借鉴工作流与交互，不复制未知算法或事实所有权 |
| 开源 ERP 与电商内核决策 | [12_OPEN_SOURCE_ERP_AND_COMMERCE_KERNEL_DECISION.md](12_OPEN_SOURCE_ERP_AND_COMMERCE_KERNEL_DECISION.md) | ERPNext 仅进入隔离 PoC；同一业务对象只能有一个可写事实所有者 |
| 可复用模板 | [templates/README.md](templates/README.md) | 先用真实 SKU/账单试填再冻结 |

## 受控来源

- `方案001.docx`：研究母稿，只读引用；包含 Ozon 三 SKU 经营系统、Harness 工程、全球经营系统与成熟度研究。
- [sources/方案001_全文顺序提取.md](sources/方案001_全文顺序提取.md)：按原 Word 顺序保存的完整机械提取稿，仅用于全文检索和追溯。
- `Ozon_90天执行总纲.md`：既有经营计划，需按当前阶段门解释。
- `docs/planning/KJDS_可执行任务总库_Backlog.xlsx`：108 项候选任务库存，不等同于当前 P0。
- `docs/planning/KJDS_可执行任务总库.docx`：任务库阅读版。
- `docs/architecture.md`、`docs/adr/`：当前工程边界与已批准架构决策。

## 状态规则

- `Draft`：正在形成，不能用于放行。
- `Active`：当前唯一有效版本。
- `Frozen`：保留历史，不再派生当前任务。
- `Superseded`：已被新文档取代，必须指向替代版本。
- 工作项状态只允许：`NOT_STARTED`、`IN_PROGRESS`、`BLOCKED`、`NEEDS_REVIEW`、`DONE`。
- 任何 `DONE` 必须同时具备负责人、验收结果和证据链接。

## 当前项目判断

当前 KJDS 是可演示、可扩展的工程骨架，不是已打通的经营闭环。工程骨架约 35%–40%，90 天真实经营闭环约 10%。当前瓶颈是三个真实 SKU、Ozon 账户与权限、合规/样品证据、物流、结算和银行到账，而不是继续扩展平台模块。
