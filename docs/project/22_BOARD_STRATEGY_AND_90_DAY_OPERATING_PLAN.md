# KJDS 董事会战略与 90 天经营计划

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-BOARD-90D-001 |
| status | Active |
| version | 1.0 |
| effective_on | 2026-08-14 |
| board_owner | 经营负责人（待真人签署） |
| independent_reviewer | 独立控制席（待真人签署） |
| engineering_contract | [MASTER_SPEC.md](MASTER_SPEC.md) |
| live_engineering_status | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) |
| detailed_board_checklist | `C:\Users\Lunar\Desktop\1\方案\KJDS_90天董事会执行与Truth_SKU清单_20260814.md` |
| solution_index | `C:\Users\Lunar\Desktop\1\方案\00_KJDS_方案权威索引_20260814.md` |

> 本文件定义董事会经营顺序、资本放行和停止条件；不新建第二套工程 Requirement、API 合同、数据真源、任务表、身份或审批权威。发生冲突时，一手经营 Evidence 决定经营事实，`MASTER_SPEC` 决定工程合同，动态任务表决定实时工程状态，本文件决定当前经营优先级。

## 1. 冻结定位与董事会判断

KJDS 当前定位为：

> 面向跨境电商经营者的、证据优先、真实现金导向、受控自动化的经营控制面。

当前价值楔子为：

> 用一个真实 SKU，把 Product、Supplier、Order、Settlement、Bank 与 Actual Cash CM3 对清，输出可审计差异、风险和唯一下一动作。

目标定位保留为“多主体、多市场、可审计、可回滚的企业 AI ERP 协调与经营控制平台”，但在以下条件全部满足前保持 `BLOCKED_EVIDENCE`：

1. 至少一个 Truth SKU 达到 `CASH_VERIFIED`。
2. 商业 C0 通过。
3. 四个真人责任席完成绑定，且至少有两个不同真人身份。
4. 当前对象与窗口的职责冲突清零。
5. 当前集成 HEAD 在隔离 PostgreSQL 上完成 G-1 PASS。

商业演进顺序冻结为：

`KJDS 自营验证 → 固定范围现金诊断服务 → 设计伙伴 → SaaS/实施 → 企业控制平台`

工程能力、文档完整或测试通过不能单独晋升 `REAL_WORLD_VERIFIED`、`CASH_VERIFIED` 或商业 C0。

## 2. 文档与投资治理

### 2.1 方案材料治理

方案目录中的材料必须按 `CURRENT_AUTHORITY`、`VISION_REFERENCE`、`SUPERSEDED`、`HISTORICAL_RESEARCH` 登记。旧版本不删除，但只有 `CURRENT_AUTHORITY` 可直接形成当前经营决议；其他状态必须重新通过当前 Gate、`best_solution`、预算、Owner、Evidence 和失效条件。

当前层级：

1. `KJDS_首席战略官总控执行方案_20260814.md`：当前经营执行真源。
2. `KJDS_90天董事会执行与Truth_SKU清单_20260814.md`：90 天 Gate、签署、Evidence manifest 和预算控制表。
3. `KJDS_当前系统搭建建议与实施优先级白皮书_v4.1.docx`：3–6 个月 `VISION_REFERENCE`，不直接立项。
4. v2/v3 成套基线为 `SUPERSEDED`；Russia v1、方案/方案2/方案3为 `HISTORICAL_RESEARCH`。
5. Autonomous Venture Federation、World Model 与 Synthetic Economy 只保留为长期架构期权。

### 2.2 80/20 与 WIP

| 资源线 | 默认容量 | WIP | 允许范围 |
|---|---:|---:|---|
| Truth/Cash | 80% | 1 条 | Truth SKU、原件、现金对账、异常场景、1→3 SKU、商业 C0 |
| 角色系统工程 | 20% | 1 条 | 画像驱动角色 v2、只读 API 和现有老板页区域；零身份/任务/权限/外写 |

90 天内冻结 World Model、Venture Federation、Synthetic Economy、新国家、新平台、多租户 SaaS、长期 Agent 扩编、第二任务/审批/事实系统，以及不能在两周内提高当前 Gate 通过率的产品能力。

### 2.3 分阶段小额预算

资本只能依次放行：

1. Evidence/Data：原件整理、只读数据和必要校验工具。
2. Sample/Verification：身份、三报价、规格、样品和合规证据通过后。
3. Controlled Order：downside CM3、最大损失、Owner、Approval/Permit 和停止线完整后。
4. Ads/Scale：首单平台结算、银行 Readback、Actual Cash CM3 和 C0 通过后。

每一阶段的金额、币种、最大损失、有效期和停止线必须由经营负责人本人填写，并由申请人和独立批准人签署。空白一律代表 `NOT_AUTHORIZED`；系统不得生成金额或把预算签署解释为外部动作授权。

## 3. 当前真实性基线与责任边界

2026-08-14 的私密启动资料预检结果：合同 `kjds-startup-package-v4`、结构 `structurally_valid`，但严格预检退出码为 `3`；候选研究、财务对账、G0 治理、Ozon 访问、Ozon API 身份、SKU 媒体、SKU Passport 和供应商报价八区全部 `awaiting_inputs`，`ready_sections=[]`、`automatic_import=false`、`formal_fact_promoted=false`。

因此当前不可宣称：

- 真实 SKU 已签署或已接入。
- Ozon 订单、结算或银行到账已核验。
- 任一供应商报价、规格、合规或素材已晋升正式事实。
- Actual Cash CM3 已建立真实基线。
- 任何 SKU 已 `CASH_VERIFIED`。

用户表示“已有原件”只改变资料协调优先级，不改变系统状态。只有私密 Evidence 引用、原件 SHA-256、来源/时间、Owner、独立复核和对应 Gate 完成后才能晋级。

### 3.1 四席组织与 SoD

当前真人组织压缩为四个责任席：经营席、运营席、财务席和独立控制席，可由 2–4 人承担。独立控制席不得复核或批准自己的产物；作者/验证人、财务制单/付款批准、外部动作批准/执行、Migration 作者/发布批准、Agent Owner/晋级批准、监管研究/正式法律签署必须分离。

35 个岗位只能作为 `role_template_ref` 能力目录；不得表述为已创建员工、账号或 Agent 身份。角色系统可推荐 `required_now`、`supporting_ai`、`on_demand`、`standby` 和 `unsupported_gap`，不得任命真人、创建身份、启动任务、持久化模拟画像或授予生产权限。

### 3.2 Evidence manifest 安全边界

董事会清单只登记不透明 `evidence_ref`、SHA-256、Owner、独立复核和状态。密码、Token、API Key、完整银行资料、客户 PII、供应商联系人 PII 和原始经营数据不得进入 Git、方案文档、对话或 API 响应；原件只保存在批准的私密 Evidence 工作区。

## 4. 90 天执行 Gate

### Day 0–3：冻结一个 Truth SKU

- 签署唯一稳定的 Truth SKU 和 Product/SKU/Ozon offer 映射 Evidence。
- 绑定四席真人，完成 SoD 检查和最大损失签署。
- 建立私密 Evidence manifest，给八区每个缺口分配 Owner、截止和失败路径。
- 发布一个唯一下一动作；其他 SKU 保持 `STANDBY/UNKNOWN`。

Gate：一个 SKU、一个责任组、一套 manifest、一个下一动作。未满足则保持 `BLOCKED_EVIDENCE`。

### Day 4–14：首条真实现金闭环

- 收齐同一 SKU 三家真实报价及有效期、规格、包装、MOQ 和交期。
- 对齐 Ozon 订单/退货、费用/结算、银行到账、FX 和实际成本。
- 在同一 exact scope 下复算 Actual Cash CM3，未知项保持显式隔离。

`CASH_VERIFIED` 仅在 canonical 映射唯一、关键原件有哈希/时间/Owner/独立复核、订单→结算→银行守恒、未匹配数为 0、CM3 可复算且当前 G-1 PASS 时成立。

### Day 15–30：异常场景与角色系统 v2

- GS-01 正常订单；GS-02 供应商涨价/换源；GS-03 退款/退货/履约失败。
- 20% 工程线完成八项画像真实生效、2–4 人兼岗、SoD、认证只读角色 API、现有 `/team-control` 区域、OpenAPI 与验证。

Day 30 Stop：没有一个 `CASH_VERIFIED` SKU 时暂停所有新增产品能力；只修数据、责任和 Evidence 流程。

### Day 31–60：1→3 SKU 与商业 C0

- 用同一合同依次复制第二、第三 SKU。
- 向 3 家匹配 Ozon 卖家交付固定范围的“Truth SKU 现金利润诊断”。
- 验证数据交付意愿、人工耗时、错误成本、行动改变、价格和复购理由。

C0：3 家有效访谈、1 家交付脱敏真实数据、1 个付费或等价强承诺、客户可一句话复述价值、结果改变一个真实决策。

Day 60 Stop：未通过 C0 时不建设多租户 SaaS，也不对外销售收费诊断；仅允许无收费、无生产授权的设计伙伴问题验证，以验证信任、交付和定价假设。

### Day 61–90：复制与有限自动化

仅在 Truth Cash 与 C0 同时通过后，形成标准 Evidence intake/reconciliation 模板、完成 3 SKU 同口径复算、建立 Prediction→Outcome→Error 基线，并开放低风险、可逆、幂等、有 Permit/Receipt/Readback/补偿/Kill Switch 的 Fast Lane。

Day 90 Stop：合同不可复制或 Readback 不可靠时退回人工受控流程；多国家与长期自治继续冻结。

## 5. 董事会验收指标

董事会仅看：

- `CASH_VERIFIED SKU count`
- `Reconciliation unmatched count`
- Critical Fact completeness/freshness
- Actual Cash CM3
- Expected vs Actual CM3 error
- Human hours per reconciled SKU
- Required Readback success
- Idempotency violations
- Evidence-to-decision cycle time
- Design partner data-share rate
- Paid pilot count
- AI/engineering cost per verified cash loop

Agent 数、页面数、模块数、代码行数和 Story 完成数不作为经营成功指标。

每周五执行 Stop/Continue/Double-down：停止连续两轮无 Gate 增益、超 WIP 或无 Owner 的工作；继续减少真实阻塞的工作；只对被 Evidence 证明的瓶颈增加资源。

## 6. 决策记录

| 决策 | 选择 | 拒绝/延期项 | 失效条件 | 复审 |
|---|---|---|---|---|
| 当前价值楔子 | 单 Truth SKU 现金闭环 | 完整 ERP、通用 Agent、多市场同时建设 | 真实客户证据证明另一楔子能以更低风险更快形成现金验证 | 每周五 |
| 商业顺序 | 自营→诊断服务→设计伙伴→SaaS/实施 | 直接销售完整自治平台 | C0 与 3 SKU 复制均通过 | Day 60/90 |
| 组织 | 四席、2–4 真人、35 能力模板 | 将模板冒充虚拟员工 | 真人容量或风险等级有经批准的变化 | 每阶段 Gate |
| 画像存储 | 当前配置 + 非持久化模拟 | 现金闭环前建设画像数据库/审批流 | 已证明存在重复、审计和授权需求 | Day 30 |

本战略不授权真实采购、付款、合同签署、上架、广告或平台写入；所有外部动作继续服从既有 Approval、Permit、Readback、补偿、审计与 Kill Switch。
