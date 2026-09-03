# KJDS Ultimate Product Blueprint

Status: Start-Gate source of truth  
Baseline: `b34a3a7`, `feature/batch-opportunity-mining-059`  
Observed at: 2026-07-27 Asia/Shanghai  
Scope: Ozon Global 中国卖家；不把 RU 本土规则当作默认  

## 1. 产品承诺与不可交易边界

KJDS 是 Seller Operating System：把市场观察、精确商品身份、供应证据、
十五项 CM3、内容、审批、执行、订单与结算组织成可回放经营闭环。成功不是
“自动上品数量”，而是有 Evidence 的学习速度、结算后正 Actual Cash CM3、
现金周期、履约质量和受控扩量。

“规则优势/超越规则”只表示：

1. 更早发现规则变化并模拟 SKU、利润、库存、内容和履约影响；
2. 使用比平台最低阈值更严的内部预警、冻结和止损；
3. 更快完成合规内容、价格、库存和执行准备。

它绝不表示绕过条款、验证码、限流、平台风控、知识产权或数据访问控制。
受限来源立即 `no_data`。数据优先来自 Seller API、官方导出、授权连接器及
允许访问的公开页，并保留 ToS/robots、频率、地域、个人数据最小化和撤销记录。

未完成 Billing、Usage Ledger、Entitlement、退款/发票、AI/媒体单位经济和 SLA
验收前，¥299/999/3999、¥120,000/年、¥250,000/年均为
`pricing_hypothesis/internal_preview/not_for_sale`。

Ozon 条款/店铺授权、KJDS 商业订阅、某次独立 Approval + one-time Permit 是
三个独立 Gate。任何一个不能代替另一个。

## 2. 目标客户与共享 JTBD

七类渐进体验共用同一事实、利润、Evidence 与治理内核：

| 客群 | 首要 JTBD | 默认计划假设 | 可升级计划假设 |
|---|---|---|---|
| 新手 | 知道什么能研究、什么不能发布 | Starter sandbox | Growth |
| 个人 | 用有限资金找可验证的小流量机会 | Starter | Growth |
| 小微 | 批量观察、内容与补货协作 | Growth | Scale |
| 中小企业 | 类目小组和利润中心经营 | Scale | Enterprise |
| 中型企业 | 规则仿真、区域库存、财务对账 | Enterprise | Private |
| 大卖 | 多品牌、多类目实验与现金优化 | Private | Private + connectors/SLA |
| 集团 | 多主体审计、灾备与私有化 | Private | Private + deployment/DR |

共享 JTBD：发现需求 → 精确匹配 → 算清 downside CM3 → 生成有权利内容 →
独立批准 → 受控发布 → Readback → 订单/退货 → 结算/到账 → 扩量或停止。

### 2.1 市场验证基础能力基线

毛子 ERP、荔枝 Ozon 助手、芒果店长、店小秘、妙手、无忧易售、Seerfar
和 LinkFox 是能力基准，不是可有可无的灵感库。其公开、用户提供或本地只读
样本中已经出现的安全经营能力，必须进入 KJDS 原生交付清单；不允许因为
“AI 化”而省略采集、PIM、刊登、订单、采购、仓储、物流、客服、财务、广告、
促销、分析或媒体等基础功能。

验收采用两条独立曲线：

1. `native_baseline_coverage`：逐项证明代码、迁移、API、Web、权限、真实回放和
   Evidence；“已映射”不等于“已实现”，空壳页面不计覆盖。
2. `ai_operating_advantage`：只有基础项已覆盖后，才评 Agent 产物、验证器质量、
   决策时延、利润/现金改善和失败恢复；不能用模型输出数量冒充业务优势。

Cookie 复用、宽域注入、绕过验证码、无权利复制素材、无利润门禁批量上品等
不安全旧做法不照搬，但每项必须提供更安全且完成同一 JTBD 的原生替代。
第三方产品不成为运行依赖、事实权威或跨店凭据来源。

## 3. 多轴诊断与六种经营模式

诊断必须拆成四轴，不能用“填表完成率”冒充成熟度：

- `scale_segment`：店铺、SKU、用户、仓库、资本的客观规模；
- `operational_maturity`：guided/manual/standardized/API/ERP-WMS；
- `brand_stage`：未核验/经销/授权/自有/组合；
- `risk_posture`：保守/适中/进取。

每轴返回 provenance、observed_at、input completeness、Evidence coverage 和
classification confidence。用户自报只是推荐输入，不自动升级为事实或套餐。
Archetype 和四个成熟度轴只产生 plan fit/recommendation；它们不创建商业
entitlement。订阅、升级、降级仍由独立 Billing/Entitlement 合同决定。

六种模式及晋级条件：

| 模式 | 进入 | 退出/升级 |
|---|---|---|
| controlled_distribution | 预上市、低风险、小预算 | 24h/72h/7d 与一次结算后进入 refined |
| refined_operation | 稳定正 downside、内容/履约已验证 | 两结算周期后进入 hero；恶化则退回 |
| hero_sku | 两周期正 Actual Cash CM3、低退货 | 可扩变体；CM3/履约越线即停止 |
| brand_building | 品牌权利、质量与一致内容 | 权利/质量失效立即冻结 |
| store_cluster | 多主体/店铺作用域与重复防护 | 无跨店隔离或重复污染即停止复制 |
| hybrid | 多类目组合且治理能力已验证 | 按每个 SKU 回落到更保守模式 |

变体只从真实父体胜品和真实属性派生；24h/72h/7d 及结算前不裂变。

## 4. 端到端状态与动作语义

Canonical journey：

`observe → match → evaluate → content_ready → eligible_for_approval →`
`approval_allocation_selected/waitlist → independently_approved →`
`permit_ready → published/readback → ordered/returned → settled/cash → scale/stop`

`approval_allocation_selected` 只是预算槽位，不是 Approval、Permit 或已启动 Pilot。
首批全局安全门为每 SKU 1–3 件，套餐不能放大。套餐中的库存上限只适用于
24h/72h/7d、结算和独立审批后的 scale envelope。

每个动作展示 status、why、missing Evidence、Owner、SLA、下一工作区；
缺结算只阻止 actual/proven/scale，不能阻止合法观察或草稿。

利润统一为四种贡献视图：Scenario CM3（估算）以及三本实际账
Actual accrual、Settled contribution、Actual Cash CM3；四者绝不互换。

## 5. 信息架构

每页必须有 JTBD、canonical object、服务端状态、主要动作、drilldown，以及
loading/empty/error/forbidden/stale 和桌面/390px 验收。一个条件分支壳不算完成。

1. 登录、租户与授权店铺接入
2. 新手引导与多轴诊断
3. 经营总览
4. 市场/类目/竞品情报
5. 批量机会漏斗
6. 候选详情与 Product/Quality/Compliance Passport
7. 全国供应、1688 与物流比价
8. 十五项利润与定价实验室
9. 俄语内容、图片与视频 Studio
10. Approval、Permit、发布与 Readback
11. 广告与促销
12. 库存、FBP/realFBS 与补货
13. 订单、退货与客服
14. 结算、银行、争议截止与 Actual Cash CM3
15. Portfolio cockpit
16. 店群/品牌/类目/区域/主体矩阵
17. Rule Advantage
18. 异常、任务、Owner 与 SLA
19. Evidence 与审计
20. 连接器与 API
21. 团队、RBAC 与 SoD
22. Usage/套餐/账单（当前不可交易）

## 6. 内容工厂

正式内容输入只能是 Product/Quality/Compliance Passport 与已核权供应事实。
竞品只用于结构和差距观察，不复制标题、图片或视频。流水线：

`事实冻结 → 类目属性 schema → 俄语术语表/禁词 → 版本化 draft/brief →`
`事实一致性 → 俄语语言 QA → IP/权利/相似度 → 3:4 主图与媒体 QA → 独立审批`

当前简单标题拼接只能标 `draft_capability/blocked`，不得称为“AI 俄语详情优化”。
上线后内容/主图 A/B 有预算、流量和停止上限，指标是转化与结算后 CM3；
禁止虚假销量、夸张词和无权利媒体。

## 7. 商业包络

套餐只改变配额、协作、SLA、连接器频率和“可申请”的执行包络；不能降低
事实、利润、Evidence、审批或安全。未订阅仍可提供 sandbox/read-only/export/draft。
生产定时同步与外部写申请可由 entitlement 限制。

取消/到期：`active → grace → read_only`。保留导出与审计，不静默删数据；
在途命令必须停止或按冻结 Permit 完成 Readback/Compensation。

## 8. 指标

North Star：在证据完整和治理通过的 SKU 中，按时完成结算并保持正
Actual Cash CM3 的数量、金额与现金周期。

Guardrails：

- downside CM3 覆盖率、未分摊金额、Evidence 新鲜度；
- 首次 Pilot 1–3 件遵守率、Approval/Permit/Readback 完整率；
- 退货、取消、按时交付、广告边际利润、库存现金占用；
- 内容权利/质量失败率、规则变更响应时间；
- 重复商品、跨店污染、数据越权、外部副作用必须为零。

漏斗严格区分 observed listings、unique exact identities、own listings、
competitor cohort、supplier cohort、fully costed、eligible for approval、
approval allocation、approved、published、ordered、settled/proven。

## 9. 阶段交付与 Gate

- M0 Truth/Governance：Identity、Evidence、tenant/store、Rule Compiler、三本账、
  Approval/Permit/Readback。Release 条件：迁移/API/权限/守恒/匿名与越权测试通过。
- M1 Intelligence/Candidate：市场/竞品 cohort、供应 Pareto、十五项 downside、
  漏斗与候选详情。Release 条件：真实 Observation 回放且统计不把 listing 当 SKU。
- M2 Content/Approval/Pilot：Passport、俄语/媒体 Studio、Approval allocation、
  frozen plan 与小流量 Pilot。Release 条件：权利/QA、1–3 件上限、独立审批和
  one-time Permit/readback 沙箱通过；真实写仍需单独 Pilot Gate。
- M3 Order/Settlement/Portfolio：订单、退货、应计、结算、到账、Portfolio。
  Release 条件：三本账守恒、争议期限语义、unclassified/no_data 和真实回放通过。
- M4 Enterprise/Commercial：多主体、SSO、连接器、SLA、Usage/Billing/Entitlement。
  Release 条件：隔离/灾备/用量/毛利/升级降级/grace/退款发票沙箱通过，才可交易。

- Start Gate：方案、合同和架构无 P0 歧义即可 APPROVED；不要求真实订单。
- 0.59 Release Gate：实现、迁移、API、页面、全测试、真实数据回放通过。
- Pilot Gate：需求/竞品/精确规格/采购边界/完整 downside/Passport/媒体 QA/
  独立批准/Permit/Readback/止损齐全。
- Final Release Gate：真实订单、退货、结算、到账与 Actual Cash CM3；不降标准。

APPROVED Start Gate 不表示功能、商业套餐或真实盈利已经完成。

## 10. AI Agent / Assistant 产品矩阵

| 阶段 | Agent 输入事实 | 输出 artifact | 可自动动作 | 人审 Gate | Eval / 失败 |
|---|---|---|---|---|---|
| Research | scoped Observation、规则、freshness | source-bound market brief | 只读抓取/摘要 | 受限源无绕过 | 引用覆盖、错配率；失败=no_data |
| Match | exact identity/variant/schema | Match Report/cohort | 稳定指纹去重 | 模糊/冲突人工核对 | precision/recall；冲突=blocked |
| Economics | fee/FX/logistics/Evidence | 15项 CM3/erosion | 服务端确定性重算 | 未分摊/跨币种复核 | 守恒/重放；缺证据=no_data |
| Content | Passport/权利/术语/模板 | versioned draft/brief/manifest | 草稿与 QA | 独立内容/权利审批 | 事实一致/俄语/IP；失败=blocked |
| Approval | frozen plan/预算/替代方案 | review packet | 仅路由给独立 approver | proposer≠approver | SoD/哈希；不可自批 |
| Execution | approved frozen plan/Permit | command/readback receipt | 在 Permit 精确范围执行 | Permit 由独立权威签发 | 幂等/readback；不可自发 Permit |
| Growth | 24h/72h/7d、订单/退货 | scale/stop recommendation | 内部任务/预警 | 扩量重新批准 | 止损/边际利润；失败=stop |
| Settlement | order/accrual/statement/cash | reconciliation/dispute pack | 对账建议 | finance review | 金额/截止/到账；缺失=no_data |

任何 Agent 都不能把 Observation 升格为 Offer/actual、批准自身建议、签发 Permit、
绕过平台限制或在 readback 失败后继续扩量。

### 10.1 AI 原生 ERP 责任 Agent

AI 化的单位是“可验证经营产物”，不是聊天轮次。全部 Agent 读取同一 scoped
PIM/OMS/Inventory/Finance/Evidence/Rule 内核；Harness 观察数据库、API、队列、
页面、平台 Readback 与结算后状态，再把不可由模型臆测的新事实写回 Graph。

| Agent | 原生 ERP 责任 | 版本化 artifact | 独立 verifier | 明确禁止 |
|---|---|---|---|---|
| 经营总控 | 组合目标、Owner、依赖、预算与 stop | Portfolio Decision Packet | 组合守恒/依赖/预算 verifier | 自批、用 GMV 代替利润 |
| 市场雷达 | 选品、关键词、类目、竞品、趋势 | source-bound Market Cohort | 来源/freshness/exact cohort verifier | 评论冒充销量、绕过受限源 |
| 商品身份 | PIM、Exact Product/Variant、去重 | Identity Diff + Passport seed | 属性 schema/重复/跨店 verifier | 虚假变体、类目污染 |
| 供应链 | 全国供应、1688、RFQ、Pareto | Supplier/Landed-cost Packet | MOQ/数量/税运费/报价 verifier | 最低展示价即最优、自动下单 |
| 利润定价 | 15 项 CM3、价格带、促销/广告底线 | Scenario/Accrual/Settled/Cash Bridge | Decimal/FX/守恒/分摊 verifier | 客户端重算、估算冒充实际 |
| 商品库 | ERP Item、SKU、店铺映射、同步差异 | PIM/ERP Item Draft Diff | 自然键/版本/Readback verifier | 复制第三方 ERP 真源 |
| 内容媒体 | 俄语文案、主图、详情图、视频 | Draft/QA/Lineage/Manifest | 事实/俄语/IP/权利/画幅 verifier | 复制同行素材、虚假卖点 |
| Listing | 批量编辑、刊登、修复、状态 | Frozen Listing Plan/Readback | Passport/QA/利润/Permit verifier | 自发 Permit、无回读继续 |
| 订单履约 | OMS、取消、退货、客服与 SLA | Immutable Order Timeline/Exception | 事件重放/状态机/SLA verifier | 猜订单、自动承诺或骚扰消息 |
| 库存物流 | 多仓、FBP/realFBS、补货、路由 | Inventory Coverage/Route Plan | 快照/需求/短缺/时效 verifier | 猜库存、自动调库存或采购 |
| 风险合规 | 规则、Passport、RBAC、SoD | Rule Impact/Execution Gate | effective rule/Evidence/scope verifier | 绕过条款、验证码、风控/IP |
| 实验学习 | 广告/促销、24h/72h/7d、扩量/停止 | Learning Report + Scale/Stop Proposal | 边际利润/止损/Readback verifier | 自扩量、失败后持续烧预算 |

Agent 状态栏只显示外部仪器实测值：输入快照哈希、当前 artifact、验证结果、
blocker、Owner、SLA、下一工作区和最后观察时间。TODO/Graph 必须持续回显原始
目标与后续依赖，避免长轨迹只优化当前局部。模型自述“完成”不改变节点状态。

## 11. 最小分析与仪表盘合同

所有查询必须显式 tenant/entity/store、time range/timezone、display currency、
FX date、data freshness 和 source grade。核心页最低合同：

| 页面 | KPI / chart | drilldown |
|---|---|---|
| Market Radar | unique identities、competitor count、p25/p50/p75、官方 demand fields | source Observation/Evidence |
| Opportunity Funnel | observed→fully-costed→approval allocation→published→settled | candidate/identity/supplier cohorts |
| Profit Lab | baseline/downside CM3、15项 erosion、cash occupation、unallocated | component/Evidence/FX/fee row |
| Content Studio | Passport/rights/QA pass rate、cost/latency/partial failure | draft/asset/lineage/manifest |
| Growth Command | action readiness、Owner/SLA、24h/72h/7d、stop-loss | task/event/readback |
| Settlement | accrual/settled/cash CM3、remittance、dispute deadline | order/return/statement/bank Evidence |
| Portfolio | proven/growth/experiment/exit + unclassified、capital/cash cycle | SKU actual cash history |
| Rule Advantage | current/scheduled changes、affected bound SKUs、deadline | registry/source binding/Passport diff |

Source grades: A=Seller API/settlement/bank authoritative；B=official export or
authorized connector；C=allowed public observation；D=market baseline only。
Source grade never alone upgrades semantic authority。`no_data` 显示缺字段/Owner/next；
`stale` 显示 observed_at 与阈值。禁止跨店混合、评论冒充销量、客户端利润重算、
无来源趋势、绕过 ToS/robots/限流、复制竞品素材或用随机图填空。
