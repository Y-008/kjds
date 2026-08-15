# KJDS AI 自动经营与卖家店铺递归扩品 PRD

| 字段 | 值 |
|---|---|
| status | Frozen for incremental implementation |
| date | 2026-08-08 |
| product owner | 经营负责人 |
| first market | Russia / Ozon |
| source channels | 1688 first；Pinduoduo、闲鱼等经独立 Provider 准入 |
| architecture | Ponytail full；复用现有 Product/Evidence/Profit/Listing/ERP |

## 1. 产品结果

KJDS 是唯一经营工作台。经营者从一个 Ozon 商品或候选开始，系统自动完成可合法取得的
数据采集与归一化，筛出“有正式成本 Evidence 且 CM3 为正”的利润款，展示同款卖家及店铺，
允许一键进入该店铺继续采集全部可见商品和新品，再把新商品送回同一套 SKU、货源、利润、
内容、上架、订单、结算和现金闭环。该循环持续发现候选，但永远不把公开价格、AI 猜测或
相似图片当成正式报价和利润事实。

```text
Ozon 市场/商品信号
  → 精确同款与变体归一
  → 同款卖家/店铺图谱
  → 进入高价值店铺采集商品与新品
  → 去重、排除自家商品、候选评分
  → 1688/拼多多/闲鱼等货源精确匹配与多家比价
  → 正式 RFQ + 物流/费率/退货成本 Evidence
  → Decimal CM3 利润判定
  → 商品护照 + 图片/视频/俄语内容
  → 审核、批准、Permit、受控发布、回读
  → 上架链接反查货源并由卖家自行采购
  → 订单/退货/结算/银行现金回流
  → 店铺与商品价值重排，再次扩品
```

## 2. 与传统 PRD 的不同

传统 PRD 通常假设输入确定、规则确定、页面输出确定。本 PRD 把 AI 的不确定性本身作为
产品对象，每个 AI 节点必须同时定义：

1. **输入合同**：允许的字段、Evidence 等级、scope、时效、缺失值语义和禁止输入。
2. **任务合同**：模型只做分类、提取、匹配建议、文案/图片方案或解释；不得创建 Fact、
   SupplierOffer、ProfitScenario、Approval、Permit 或平台回读。
3. **结构化输出**：固定 JSON schema、候选列表、置信度、引用、冲突、`unknown` 和下一步。
4. **确定性裁决**：SKU identity、价格单位、币种、利润、去重、门槛和权限由代码执行。
5. **评测合同**：离线 golden set、影子流量、人工复核采样、错误类型、回归阈值和版本。
6. **降级路径**：模型不可用、低置信度、证据冲突、字段漂移时转人工或保持待补证，不输出
   一个看似完整的答案。
7. **运营指标**：除点击/时延外，衡量正式利润误报、错 SKU、上架退回、退货、现金 CM3、
   发现到上架周期和每个合格候选的 AI 成本。
8. **可追溯性**：模型、Prompt、工具、输入快照、Evidence、输出、人工编辑和后续实际结果
   全部可定位。

案例研究强调“AI PRD 要把不确定性变得可控”，并展示多平台情报、七层利润、逐 SKU
退货诊断、每日行动、库存现金和广告预警。本 PRD 吸收这些经营结果，但每个数字继续使用
KJDS 的 Evidence/Fact/Finance 权威，不把演示数据或内容笔记当成项目事实。

## 3. 核心对象（不新增第二真源）

| 产品概念 | 复用对象 | 说明 |
|---|---|---|
| 商品/变体 | Product + SKU Identity Card | 同款判断必须到具体变体 |
| 市场商品 | MarketplaceObservation + Catalog | 来源、时间、卖家、价格状态 |
| 卖家店铺 | capture merchant + store catalog snapshot | 是可递归探索节点，不是 KJDS 店铺账户 |
| 货源商品 | SupplierOffer + capture item | 正式报价和公开观察严格分开 |
| 利润 | ProfitScenario | 十五项成本、Decimal、Evidence |
| 内容与素材 | Passport + ContentAsset + Media execution | 权利、版本、QA、用途 |
| 上架 | ListingDraft + Approval/Permit/Execution/Readback | 不设第二发布状态机 |
| 实际结果 | Order/Return/Settlement/Bank/Actual Cash CM3 | 反哺评分，不能由 AI 伪造 |

## 4. 用户工作台

### 4.1 利润候选池

每行显示商品、精确变体、Ozon 售价观察、正式采购成本状态、CM3、盈亏平衡价、敏感性、
同款卖家数、可探索店铺数、新品标记、素材就绪度和下一动作。默认分栏：

- `正式利润款`：成本完整、CM3 > 0；
- `待补证潜力款`：市场信号有价值，但报价或成本不完整；
- `不盈利/风险款`：完整计算后 CM3 <= 0，或同款/合规冲突；
- `已上架/经营中`：有平台回读，可进入订单、退货、库存、广告和现金视图。

AI 可排序和解释，不得把 `待补证潜力款`改名为利润款。

### 4.2 同款卖家与店铺抽屉

点击商品后展示同款卖家列表：seller/store identity、店铺链接、该同款链接、观察时间、价格、
销量/评价等已验证公开字段、店内匹配商品数、店内新品数、历史命中利润款数、来源 Evidence
和身份匹配理由。用户可执行“采集该店铺”，生成现有
`store_catalog_candidates` Capture，不直接生成 SupplierOffer 或利润。

### 4.3 店铺雷达

店铺页按以下分组展示：

- 新上新：首次观察时间在选定窗口内；
- 同类扩品：与已验证利润款类目/用途/变体相近；
- 潜在利润款：存在可比售价和可继续寻找的货源，但未宣称正式利润；
- 已核算利润款：已绑定正式 SupplierOffer 和完整 ProfitScenario；
- 排除项：自家 SKU、重复变体、身份冲突、知识产权/合规/物流硬阻断。

每个商品都可回到“寻找多家货源 → RFQ → 利润 → 内容 → 上架”的主链。店铺本身获得一个
动态探索价值：正式利润命中率、新品速度、同类集中度、数据新鲜度和采集成本；该分数只决定
采集队列，不证明店铺或商品盈利。

### 4.4 每日行动清单

同一工作台输出有证据边界的动作：补报价、补物流、补图片、补俄语审核、批准上架、查看
异常退货、补库存、停止亏损广告、查看现金缺口。动作必须链接回权威对象和缺口，不生成
无法执行的自然语言建议。

### 4.5 RFQ 与报价就绪度

自动经营工作台不建立第二套询价流程，直接读取现有 exact-scope Sourcing Intelligence。
每个 ListingDraft 按 canonical Product 精确对应 RFQ package、dispatch proof、报价、独立接受
供应商数量、`three_accepted_quotes_ready` 与下一补证动作。查询先沿权威游标读取全部页，再
做 Product 映射；漏页、重复 work item、分页循环、无效结构或页面间 scope/authority 漂移都
必须失败关闭，不能把“未读到”显示成“没有回复”。该视图始终只读，不发送询价、不接受报价、
不新建报价真源。现有 Supplier Quote Authority 仍是正式报价唯一入口：只有绑定 RFQ package、
dispatch lineage、原始书面 Evidence 且经非上传者复核的 supplier-confirmed quote 才能晋升。
acknowledgement、clarification、alternative、platform notice、自动消息及
`latest_reply_unknown` 只作为 Observation/待分类回复。若书面原件包含 100/300/500 等多阶梯，
而当前 SupplierOffer 行不能无损表达全部阶梯，则完整原件与会话身份继续保存在 Evidence，
所有单档价格保持 `unknown/BLOCKED_EVIDENCE`，不得截取一档写入正式报价或利润。
不联系供应商。

## 5. 递归扩品规则

1. 种子只能来自当前 scoped 市场观察、正式利润款或经营中 SKU。
2. 同款必须经过 SKU Identity Card；只有类目/图片相似时标为“相似候选”。
3. 卖家与店铺 URL、ID 和商品 URL 分开保存；同店不同 URL 需 canonicalize 后去重。
4. 每个店铺按快照采集，记录首次/最近观察时间；“新品”是相邻快照差集，不用页面排序猜。
5. 每轮先排除 KJDS 自家 offer/product、已处理商品、相同变体和重复来源。
6. 广度和深度均有预算：每个种子最多探索 N 家店、每店最多 M 个商品、最大深度 D、最大
   Evidence/AI/人工成本和 freshness TTL；默认 D=2，不能无限爬行。
7. 只有新增的精确 SKU、店铺价值提升或新的正式 Evidence 才允许入下一轮；无增量即停止。
8. 多家货源并行：展示价作为 B-grade 观察用于初筛，正式利润必须取得可接受的书面报价及
   其他完整成本 Evidence。
9. 每轮产出可重放快照和 lineage：seed → seller → store → product → source match → scenario。

## 6. 利润产品合同

利润引擎继续采用现有十五项成本：采购、国内物流、国际物流、包装、仓储、关税、税、尾程、
平台费、广告、退货、汇兑、资金、售后、损耗及未分类成本。输出三个互斥状态：

- `recommended`：全部 Evidence 当前、无未知成本、CM3 > 0；
- `not_recommended`：全部 Evidence 当前、CM3 <= 0；
- `awaiting_evidence`：任何正式成本缺失、未知、过期或冲突。

AI 负责解释利润驱动项、敏感性和优先补证项；确定性公式拥有最终显示权。后续订单、退货、
结算和银行现金进入后，计划 CM3 与 Actual Cash CM3 并排，模型不得覆盖实际账。

## 7. 上架前运营内容与媒体 Definition of Done

### 商品事实与内容

- Identity：品牌/无品牌、型号、颜色、尺寸、套装数量、条码、供应变体 ID；
- 商品护照：材质、尺寸/重量、功能、使用方式、包装清单、警示、适用/禁用场景；
- Ozon 类目与必填属性映射，单位和枚举合法；
- 俄语标题、卖点、长描述、搜索词、FAQ、规格表和包装信息；
- 所有功效、认证、兼容性和比较性陈述都有允许等级的 Evidence；
- 母语审核和独立 Listing 审核完成。

### 图片

- 主图：白底、完整商品、准确变体、无虚假附件；
- 多角度、细节/材质、尺寸比例、使用场景、功能说明、包装清单；
- 每张图绑定来源、权利、目标 SKU、生成/编辑 lineage、尺寸与 SHA-256；
- 供应商图只在授权或许可成立时使用；AI 图必须与商品护照一致；
- OCR/拼写、变形、重复、错色、错数量、禁用声明、平台尺寸/格式和店铺差异化水印 QA。

### 视频

- 15–30 秒首版脚本：3 秒价值点、真实演示、尺寸/用法、包装、CTA；
- 竖/横版按平台位生成，俄语字幕、封面、无版权风险音频；
- 画面中的型号、颜色、数量和功能与目标 SKU 及护照一致；
- 资产、字幕、音频、模板、渲染和 QA 均可追溯。

### 发布门

上述任一必填事实、权利、媒体 QA、俄语审核或利润 Evidence 不完整时，系统停在相应工作区。
“AI 已生成图片/文案”不等于“该 SKU 已具备上架条件”。

## 8. AI 任务与评测

| AI 任务 | 允许输出 | 硬性评测/失败关闭 |
|---|---|---|
| 同款/变体候选 | 候选、锚点、冲突、置信度 | 自动绑定要求精确 ID 锚点；冲突转隔离 |
| 店铺商品分类 | 类目/用途/新品候选 | 新品必须由快照差集确认 |
| 货源匹配 | 多个候选及字段对比 | 不自动形成 SupplierOffer |
| 利润解释 | 驱动项、敏感性、补证顺序 | 公式/状态不可由模型覆盖 |
| 俄语 Listing | 结构化草稿及 Evidence 引用 | schema、禁词、事实一致性、母语审核 |
| 图片/视频方案 | shot list、Prompt、QA 建议 | SKU/护照/权利不完整不生成终版 |
| 每日行动 | 有对象、有理由、有下一工作区的动作 | 不得直接批准、发 Permit、付款或发布 |

发布前评测至少覆盖：精确 SKU 错绑、公开价误升正式成本、利润假阳性、俄语事实幻觉、图片错
变体、店铺 URL 错绑、自家商品未排除、Prompt 注入、模型/Provider 降级、成本/时延上限。
任何会造成错 SKU 上架或假利润的 golden case 失败均阻断版本晋升。

## 9. 指标

- Seed → 合格候选 → 三家 RFQ → 完整利润 → 上架 → 首单 → Actual Cash CM3 转化漏斗；
- 每个正式利润款探索店铺数、每店新增候选数、重复率和新品命中率；
- SKU 自动绑定精度、隔离率、利润假阳性率、上架退回率、素材返工率；
- 发现到上架周期、每个合格候选 AI/Provider/人工成本；
- 订单后退货率、广告效率、缺货/滞销、计划与实际 CM3 偏差、现金占用。

“月销”“热销”“利润”“新品”均必须带来源、窗口、scope 和状态；没有 28 天或实际数据时
显示 `unknown/awaiting_evidence`。

## 10. 分期

### P0（当前）

自动推进现有 AI Listing；证据化利润状态；Ozon 上架链接反查 Product、SupplierOffer、采购
商品和店铺链接；卖家自行采购。真实发布继续受既有 Gate 控制。

### P1

扩展现有 Browser Capture `store_catalog_candidates`：保存卖家/店铺 canonical identity、店铺
商品快照与首次/最近观察时间；利润候选池增加“同款卖家/进店采集”。

### P2

店铺快照差分、新品队列、递归预算/去重/停止规则、多 Provider 货源匹配、三家 RFQ 并行。

### P3

上架前内容媒体完整度工作台、真实发布回读、上架链接采购反查、订单/退货/结算/现金学习；
以实际结果校准候选排序，但不让模型自改权限或公式。

## 11. 不在首切片

自动向供应商下单、自动付款、用公开展示价冒充报价、无限递归采集、绕过平台登录/权限、
复制第三方受保护素材、自动批准 Listing、自动签发 Permit、没有回读的“发布成功”，均不在
首切片，也不得由 Agent 隐式执行。

## 12. 自适应经营策略图（取代固定“选品→上架→广告”）

KJDS 不把经营压缩成固定三段，也不把任意数量的“打法”硬编码成第二套流程。主状态继续复用
Commerce OS 的 `observe → identity → qualify → item_draft → content → listing_approval →
publish → order → procurement_review → fulfill → settle → reconcile → learn`。在这个唯一真相链
上，版本化策略注册表按 SKU 当前阶段并行投影市场/货源、身份/合规、利润/现金、内容/媒体、
Listing/渠道、订单/履约、退货/质量和实验/学习工作流。

经营不是单向漏斗。系统必须支持以下证据化反馈：

- `learn → observe`：现金结果或新假设触发新市场、供应商、卖家店铺观察；
- `learn → qualify`：真实退货、费率、采购和现金偏差重算资格；
- `learn → content`：搜索词、评论、退货根因进入内容修正；
- `reconcile → qualify`：计划 CM3 与 Actual Cash CM3 偏差回到利润门；
- `fulfill → content`：包装、使用和买家预期差异进入图片、视频、FAQ；
- `settle → procurement_review`：只有到账现金与组合额度允许时才提出补货。

每个 SKU 的经营投影必须同时返回：当前真相状态、匹配打法、准入 Evidence、缺口、内部下一
动作、预算/最大损失、观察窗、成功指标、停止条件、Owner、外写门和来源版本。系统可自动生成
内部草稿、计算和任务；`proposal_ready` 只表示可以准备提案，Evidence Gate 未运行或未通过时
不得转义为“可发布/可投放/可采购”。

外写关闭时动作不能消失：系统仍要生成待调价（含证据完整时的建议售价/区间）、待改广告预算
或出价、待改 Listing/素材、待补货、待暂停/清仓等提案。人工可批准进入既有 Gate、拒绝并写
理由、延期或要求补证；资料不完整时保留动作但数值为空。人工决定管理“是否继续处理”，不替代
正式成本、合规、Listing、Permit 或 Readback 门。

首批研究打法保存在
`docs/project/registries/store_category_strategy_registry.json`，当前覆盖多供应商 RFQ、店铺递归、
小单试销、搜索内容、媒体、价格、广告、促销、仓群库存、履约包装、退货纠偏、季节、组合现金
和滞销退出。条目数量不固定；任何新增打法都必须带一手来源、适用阶段、Evidence、动作、指标、
止损和自动化权限。检索与推导记录见
`docs/project/evidence/20260808_RESEARCH_BACKED_OPERATING_PLAYBOOKS.md`。

## 13. AI-native 技术执行合同

1. **商品数字孪生**：一个精确变体贯穿来源、报价、内容、Listing、订单、退货、结算、现金和
   采购反查；任何跨层身份冲突先隔离。
2. **结构化 Agent 合同**：每个 Agent 固定输入 schema、工具白名单、输出 schema、引用、预算、
   时延、失败降级、人工 Owner 和 trace；模型不写核心事实。
3. **评测驱动发布**：确定性校验负责身份、金额、权限和守恒；模型 grader 只评语言/视觉等非
   确定部分。金标覆盖错 SKU、假利润、权利、俄语幻觉、Prompt 注入和工具越权。
4. **来源时效**：平台规则/能力至少每 30 天复核，策略研究至少每 90 天复核；来源过期进入
   `awaiting_source_review`，不能静默沿用。文章里的示例数字不得变成经营阈值。
5. **官方/授权适配优先**：官方 API 或授权导出优先；浏览器采集只处理用户当前页可见公开数据，
   保存来源、覆盖率和失败页。Adapter 不拥有 Canonical Product 或利润事实。
6. **Agentic commerce 就绪**：Canonical Product 维护新鲜的价格、可售性、媒体、政策状态和
   货源 lineage，可投影到未来渠道/协议；商户系统、履约、退货和客户关系仍由 KJDS/商户控制。
7. **最小权限协议**：MCP/Provider 工具按 tool 与身份授权，浏览器不保存服务端密钥；写动作仍
   经 Approval、一次性 Permit、Executor、Readback、Kill Switch 和 Compensation。
8. **可解释下一最佳动作**：推荐由阶段、Evidence、组合预算、边际现金价值、时间窗口和风险
   排序；输出必须说明为何现在做、缺什么、何时停，不用模型分数冒充事实概率。

## 14. 自动化升级阶梯与复选项

Store Profile 提供一个默认关闭的门店自动化总开关；每个待处理动作卡再显示独立的
“自动执行此类动作”复选项，默认也不勾选。总开关本身不会批量启用任何动作，动作未显式启用
时继续人工处理。勾选只保存当前 exact-scope 自动化请求，不直接产生平台权限。每个动作可继承
门店默认模式，也可单独选择模式和设置每日动作数、预算、单价、调价幅度、数量、最大损失及
有效期上限。支持三个逐步开放的模式：

1. `manual_each_action`：当前默认，每次由人工决定；
2. `supervised_batch`：人工批准一个有界批次，批内每个动作仍独立复验、幂等和回读；
3. `policy_bound_autonomous`：在精确店铺/SKU/类目、动作、价格/预算/数量/最大损失、有效期、
   Evidence/策略版本和停止条件内自动执行。

全自动不是无限授权。Automation Grant 必须绑定 exact tenant/entity/store、打法和动作类型、SKU/
类目范围、金额/价格/数量上限、观察窗、有效期、独立批准、执行时 `authorize_action()`、幂等、
权威回读、Kill Switch 与 Compensation。任何输入过期、身份/变体漂移、CM3/预算/退货/库存越界、
回读缺失或策略版本变化，立即暂停并回到 `pending_human_decision`。

接口必须并列显示 `requested_mode`、`effective_mode`、`grant_ready` 和
`runtime_execution_enabled`。只有总开关、动作开关、打法准入、运行时能力和既有执行授权链
全部通过时，`effective_mode` 才可离开 `manual_each_action`；Profile 偏好、复选框和额度都不是
Grant。这样既保留后续全面自动化，又能阻止前端选择状态被误报成生产动作已经放行。

隔离分支曾实现 API Profile；BAS-219A 主线切片只接入注册表、Store Profile 领域合同中的
总开关/单动作偏好/额度及四状态投影，不接 Router/API/OpenAPI/Web。`supervised_batch` 和
`policy_bound_autonomous` 运行时仍为 `planned`，不得在没有 Automation Grant/Executor/Eval 的
情况下伪称已自动执行。后续按“Shadow → 小范围监督批次 → 单打法全自动 → 跨打法闭环”逐级放量。
