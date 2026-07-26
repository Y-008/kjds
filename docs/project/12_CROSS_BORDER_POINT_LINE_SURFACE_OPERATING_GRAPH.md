# KJDS 跨境 AI 点—线—面全链路运行图谱

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-OPERATING-GRAPH-001 |
| release | 0.55.0 |
| owner | Product Architecture / Control Plane |
| status | Active |
| primary market | Russia |
| primary platform | Ozon |
| machine contract | `kjds-cross-border-operating-graph-v1` |
| source of truth | `registries/cross_border_capability_atlas.json` |

## 1. 结论

KJDS 不把“功能多”当作“经营已打通”。本版把 LinkFox 公开页面和价格矩阵可见的创作、
会话、插件、POD、视频、修图、批量与企业能力继续拆成原子点，再补齐俄罗斯/Ozon 的
市场、供应商、成本、Listing、订单、库存、退货、广告、结算和治理原子点。所有点进入
同一服务端运行图谱：

```text
143 个原子点
  ├─ 工具点：会话、图片、服装、设计、POD、修图、视频、批处理
  ├─ 经营点：趋势、选品、供应商、CM3、Passport、Listing、广告、库存、订单、售后、财务
  └─ 控制点：Evidence、Lineage、审批、Permit、回读、回滚、Kill Switch、评测、适配器
        ↓ 依业务对象状态变化排序
14 条端到端价值流
        ↓ 按经营决策、维度与真源重新聚合
8 个经营控制面
```

图谱是只读产品/工程合同，不是外部执行权限。LinkFox 公开观察保持 C 级；Ozon 只使用
仓库中已有固定合同与测试，不把本次未能读取的公开文档页面内容提升为新事实。

## 2. “点”：逐功能可审查合同

每个原子点必须回答 16 个问题：

1. 属于哪个能力域和宏观能力？
2. 处理哪个业务对象？
3. 是 query、transform、recommendation、decision、projection、command 还是 control？
4. 来源是 LinkFox C 级观察、KJDS 仓库合同，还是产品架构设计？
5. 当前是 `implemented`、`ready`、`gated` 还是 `research_only`？
6. 输入合同是什么？
7. 输出合同是什么？
8. 使用什么可替换技术 profile？
9. Evidence 晋级门是什么？
10. 主要失败模式是什么？
11. 失败进入哪个队列？
12. 如何独立回读或重放？
13. KPI 和 SLA 是什么？
14. Owner 与 Reviewer 是谁？
15. 市场、平台和不可越权控制是什么？
16. 属于哪些价值流，并回到哪个真实 KJDS 工作区？

### 2.1 原子点成熟度

| 能力域 | 原子点 | Implemented | Ready | Gated | Research only |
|---|---:|---:|---:|---:|---:|
| 灵感、商品与资产中枢 | 14 | 9 | 5 | 0 | 0 |
| AI 服装视觉 | 9 | 0 | 9 | 0 | 0 |
| AI 商品视觉 | 9 | 0 | 9 | 0 | 0 |
| AI 修图与质量提升 | 14 | 0 | 14 | 0 | 0 |
| AI 视频、POD 与设计 | 19 | 0 | 19 | 0 | 0 |
| 批量生产与企业治理 | 11 | 0 | 10 | 1 | 0 |
| Agent、Skills 与 24×7 协作 | 15 | 3 | 7 | 3 | 2 |
| 选品、市场与 Listing | 8 | 5 | 3 | 0 | 0 |
| 供应链、利润与增长闭环 | 25 | 20 | 5 | 0 | 0 |
| Evidence、受控执行与全球扩展 | 19 | 13 | 5 | 1 | 0 |
| **合计** | **143** | **50** | **86** | **5** | **2** |

这里的 `implemented` 只表示仓库存在已验证合同、测试或受控工作区，不表示已经取得新的
第三方权限或产生经营结果。73 个 LinkFox 公开观察点中没有一个被标为 `implemented`。

### 2.2 原子能力完整覆盖

公开价格矩阵中易被一级菜单合并的能力已经单独建点：

- 会话与插件：自由会话、公开型号入口、个人模板、模板会话、敏感词预检、页面上下文、
  运营模板、Evidence 分析、商品画像、术语库、Skill 计划、定时任务和外部 Worker 准入。
- 商品图：套图、替换、场景、手持、图片翻译、白底、细节、卖点、规格/尺寸和批量变体。
- 服装图：套图、换模特、换场景、试衣、姿势、穿戴、UGC、尺码和服装保真 QA。
- 设计/POD：设计画布、平台/个人/团队模板、场景素材、相似裂变、自由绘图、素材贴合、
  印花提取和 design preflight。
- 修图：智能修图、长图重建、局部重绘、消除、换色、材质感知换色、裁剪、放大、扩图、
  精修、色差、印花、手部、精细抠图和批量抠图。
- 视频：图转视频、口播、俄语脚本/语音、复刻、拼接、字幕/节奏、商品真值 QA、平台编码
  和视频交付 Manifest。
- 企业：算力、并发、存储、保留、优先级、账号/团队作用域、批量会话、批量图片和 API
  准入。
- 经营与控制：36 个 Russia/Ozon 经营点和 16 个跨域控制/全球适配点。

## 3. “线”：14 条端到端价值流

| 价值流 | 入口门 | 出口门 | 关键异常 | 核心 KPI |
|---|---|---|---|---|
| 趋势 → 可验证机会 | 来源、时间、许可、市场完整 | 机会卡含事实/推断/未知与否决条件 | 过期、许可未知、冲突、不可证伪 | 证据完整率、信号到机会率、提前淘汰量 |
| 机会 → 供应商事实 | 规格、数量、目的地、期限可冻结 | 三份独立、当前、已接受报价 | 身份不明、规格冲突、发送证明不足、过期 | 有效回复率、报价完整率、三报价周期 |
| 供应商事实 → CM3 | 报价/物流/币种/有效期一致 | CM3 标明权威层、缺口与敏感性 | FX 过期、费用漏项、规格冲突、低 CM3 | 成本完整率、预测/实际偏差、CM3 门通过率 |
| 商品身份 → Passport | Evidence、店铺/offer、人工绑定完整 | Passport 来源、未知、权利、有效期可审查 | 重复身份、映射冲突、原件/权利缺失 | Passport 完整率、身份冲突、权利覆盖 |
| Passport → 多模态内容 | Passport、权利、品牌、平台 profile 有效 | 逐资产保真/OCR/合规/权利/批准/Manifest 通过 | 商品漂移、俄语错误、权利未知、成本超限 | 一次验收率、保真率、单资产成本 |
| 内容交付 → Listing | Manifest、Passport、规则、术语当前 | 精确草稿哈希获独立批准 | 必填/枚举、引用断裂、媒体过期、敏感表达 | 规则一次通过率、返工率、引用完整率 |
| Listing → 发布与回读 | Approval、Permit、幂等、预算、Kill Switch 有效 | 独立回读与期望一致 | 拒绝、部分成功、回读不一致、Permit 过期 | 写入成功率、回读一致率、补偿成功率 |
| 发布 → 增长实验 | 基线、指标、样本、预算、停止条件完整 | 因果边界和下一决定明确 | 无基线、样本不足、预算/库存风险 | 有效实验率、增量 CM3、停止规则命中率 |
| 需求/库存 → 补货 | 库存/在途/销量、报价、CM3、现金可审查 | 精确供应商/SKU/数量/价格获批准 | 历史不足、报价过期、现金/CM3/库存风险 | 缺货风险、周转、预测偏差 |
| 订单 → 履约交付 | 订单来源、店铺、SKU、金额、状态有效 | 交付/异常有平台或物流 Evidence | 状态漂移、超时、丢件、库存不一致 | 按时交付、异常率、状态新鲜度 |
| 交付 → 退货售后 | 订单、商品、原因和证据完整 | 处理、沟通、库存、费用和关闭证据完整 | 原因不明、证据不足、高值争议 | 退货率、首次解决率、关闭周期 |
| 交易/结算 → 对账 | 交易、结算、币种、时间和权威可识别 | 每笔 matched/exception，差异有 Owner | 缺交易、重复费用、金额/FX 差异 | 对账覆盖、未对账金额、队列年龄 |
| 经营信号 → 学习实验 | 来源、基线、可控变量、指标存在 | 采用/拒绝/继续研究及范围明确 | 不可证伪、数据泄漏、样本/成本问题 | 信号到实验率、有效学习周期、增量 CM3 |
| 异常 → 人工控制恢复 | 分类、对象、严重度、Owner、轨迹完整 | 恢复/冻结/回滚有回读和关闭 Evidence | Owner 缺失、轨迹不全、补偿失败、重复故障 | 队列年龄、MTTR、重复故障率 |

## 4. “面”：8 个经营控制面

| 经营面 | 核心维度 | 必须回答的决策 | 真源 | 主要预警 |
|---|---|---|---|---|
| 店铺经营矩阵 | 店铺、市场、平台、类目、商品、时间 | 哪个店/商品需接管；增长是否增加真实 CM3 | Product + Platform Read + Reconciliation | 状态漂移、缺货、履约超时、未对账金额 |
| 商品真源与 Passport | Product、SKU Episode、店铺、市场、Passport、版本 | 事实是否足够；字段/权利是否过期；身份是否冲突 | Product + Evidence + Passport | 下游 stale、权利过期、原件缺失、映射冲突 |
| 多模态内容工厂 | 商品、资产类型、locale、平台、模型/Skill、批次 | 哪个候选可交付；返工根因；模型是否晋级 | Passport + Asset Rights + Manifest | 商品漂移、权利/OCR/敏感词、模型回归、成本超限 |
| 受控执行与异常 | 店铺、endpoint、actor、Permit、对象、风险、时间 | 是否执行；何时冻结/回滚；谁接管；回读是否完成 | Approval + Execution + Readback + Audit | 无 Permit、回读不一致、Kill Switch、重复故障 |
| 供应、库存与利润 | 商品、供应商、线路、币种、权威、库存、结算 | 供应/路线/价格/采购量是否满足 CM3 和现金门 | Supplier Evidence + Cost + Inventory + Reconciliation | 报价/FX 过期、低 CM3、库存风险、对账差异 |
| 订单、履约与售后 | 订单、商品、案例、物流、退货原因、地区、时间 | 哪一单需接管；如何沟通/申诉/赔付；如何更新库存财务 | Order/Delivery/Return Evidence | 物流超时、高值争议、重复退货、退款/库存不一致 |
| Agent、Skill 与模型治理 | 目标、Agent、Skill、模型、工具、评测集、店铺、风险 | 哪个模型可晋级；质量/成本/延迟；何时撤销/接管 | Agent Plan + Eval + Telemetry + Approval | 未评测 Skill、工具越权、成本超限、轨迹缺失 |
| 全球市场扩展 | 国家、平台、locale、币种、税制、类目、适配器版本 | 新市场缺什么；内核复用什么；哪里必须失败关闭 | Canonical Kernel + Versioned Adapters | 合同变化、许可/凭证过期、规则冲突、币税缺失 |

所有经营面保持只读。外部动作必须跳转原工作区，重新验证身份、职责分离、Approval、
Execution Permit、预算、Kill Switch、幂等、回读和回滚。

## 5. 一件商品的完整对象状态迁移

```text
Public/Platform Raw Evidence
  → ResearchSignal
  → DemandCluster
  → OpportunityCandidate
  → SupplierCandidate
  → SupplierRfqPackage
  → SupplierRfqDispatch Evidence
  → AcceptedSupplierQuote × 3
  → SupplierOfferComparison
  → LogisticsQuoteSnapshot
  → FullLandedCost
  → ContributionMarginSnapshot / PriceCorridor
  → CanonicalProduct
  → ExternalIdentityMap
  → ProductPassport
  → StructuredBrief
  → ContentCandidate
  → ContentDeliveryManifest
  → ListingDraft
  → ListingPolicyReport
  → ListingApproval
  → ExecutionPermit
  → OzonListingCommand
  → PlatformReceipt
  → Independent ReadbackReceipt
  → AdvertisingDiagnostic / ExperimentHypothesis / CausalReadout
  → InventoryDemandSignal / PurchaseApproval
  → MarketplaceOrder / DeliveryEpisode / ReturnCase
  → FinanceTransaction / FeeAccrual / SettlementMatch
  → ReconciliationException or Reconciled Result
  → LearningDecision / AuditBundle
```

任何箭头失败都不静默跳过：进入具名失败队列，记录严重度、Owner、期限、输入哈希、控制
结论和恢复/关闭 Evidence。

## 6. 最新技术如何落地，而不是堆组件

| 技术方向 | KJDS 采用方式 | 不采用的捷径 |
|---|---|---|
| 多模态生成 | Provider-neutral router；商品/服装保真、OCR、属性、关键帧 QA；结果只作 candidate | 让视觉模型写商品事实或自动发布 |
| Structured Output | 版本化 JSON Schema、枚举、单位、币种、对象哈希；解析失败关闭 | 从自由文本猜关键规格、金额或权限 |
| Grounded Agent | 先 Evidence/Passport 检索，再输出事实/推断/未知；计划、工具、批准、执行、回读分离 | “超级 Agent”持有平台凭证和无限工具 |
| Agent/Skill 评测 | 金标、轨迹、工具调用、质量、成本、延迟、人工结论；champion/challenger 影子 | 以模型名、榜单或营销案例直接晋级 |
| 图谱 | 版本化稳定 ID + 服务端交叉引用验证 + 原生 HTML/SVG 投影 | 143 点规模立即引入图数据库 |
| 工作流 | PostgreSQL Outbox、租约、幂等、可恢复任务、补偿和人工接管 | 在无长事务实证前引入 Temporal |
| 检索 | PostgreSQL 精确/全文、来源过滤和可重放排序 | 无基准就引入向量库并弱化来源 |
| 批处理 | 有界并发、配额、逐项门、部分失败账本、暂停/恢复 | 用“批次成功”掩盖逐项失败 |
| 外部写 | 最小权限 Worker、短时 Permit、Kill Switch、独立回读、补偿 | HTTP 200 即视为业务完成 |
| 全球扩展 | Canonical Kernel 外围的 country/platform/locale/currency/tax adapter | 复制一套 Amazon/WB/Yandex 事实和权限 |

## 7. 全球扩展顺序

1. **Russia/Ozon**：继续以已固定、已测试合同为唯一首市场实现。
2. **Russia 邻接平台**：Wildberries、Yandex Market 先做官方合同/许可/只读样本准入，
   不继承 Ozon 身份或字段语义。
3. **Amazon/Shopify/eBay**：复用 Product/Passport/Content/Approval 内核，分别验收
   类目、Listing、广告、订单和财务合同。
4. **Temu/SHEIN/TikTok Shop/Shopee/Lazada/AliExpress/Etsy**：只有在目标市场、
   本地运营 Owner、税务/物流/支付和真实样本齐备后解冻。
5. 每个平台先只读 Evidence，再影子、有限写、独立回读；任何阶段可撤销。

## 8. 验收边界

- 机器注册表生成检查必须稳定输出 143/14/8。
- 服务启动时拒绝重复 ID、悬空引用、未知状态/来源/profile 和 LinkFox 事实晋级。
- API 只读、鉴权，匿名失败关闭；客户端不能重算路径或状态。
- Web 支持点/线/面/主干切换和跨层搜索、市场/状态过滤。
- `implemented` 不等于外部业务结果；`ready` 不等于已上线；`gated` 不得绕过准入。
- 新平台、模型、Skill、浏览器或 API 必须完成许可、身份、最小权限、固定样本、回放、
  评测、成本、审计、回读和回滚。
