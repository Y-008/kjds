# 跨境 SaaS 竞品能力借鉴与 KJDS 超越路线

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-PRODUCT-BENCHMARK-001 |
| owner | 产品负责人（待确认） |
| approver | 经营负责人 |
| status | Active |
| version | 2.1 |
| last_reviewed | 2026-08-08 |
| next_review | 2026-09-08 |
| gate | G0–G4 |

## 结论

国内 ERP 值得借鉴的是“全链路、少切换、批量处理”，国际平台值得借鉴的是“AI 深入店铺上下文、
先生成建议、由人复核、再在原权限内执行”。KJDS 的超越点不是再包装一个聊天框，而是把这些效率
建立在原件血缘、独立复核、全成本 CM3、因果实验、审批、回读、回滚和审计之上。

`C:\Users\Lunar\Desktop\1` 的 58 张参考图已经逐张缩略审阅。它们主要是方法论文章、Skill 清单、
Harness 说明和“AI 自动运营”叙事，包含少量 Ozon 商品页和成本表截图，但没有可运行前台、接口合同、
真实订单/结算血缘或自动动作回读。因此它们可以用于信息架构和运营步骤启发，不能作为实现完成或
经营效果证据。

## 能力映射

| 产品 | 官网当前可见模式 | KJDS 借鉴 | 不照搬 | 下一步 |
|---|---|---|---|---|
| 萌啦 Ozon 定价精灵 | 采购、重量、体积、国内运费、类目佣金、折扣、广告、其他成本和国际物流集中录入；可保存模板并比较物流方案 | 将现有利润场景改造成逐项来源、估算/实际双列的可保存模板；同屏比较物流情景 | 未知公式/费率直接入账；“其他成本”吞掉已知成本；自动定价 | 先用 KJDS 全成本合同生成只读场景模板和差异解释 |
| Seerfar | 30–90 天产品趋势、搜索趋势、品牌/产品集中度、关键词挖掘/反查/排名、竞品与店铺监控；官网提供 Open API 入口 | 建立研究收集箱、趋势快照、关键词—竞品—候选关系和变化提醒 | 把估算销量/收入当真实账户数据；未经协议审核安装插件或共享会话 | Open API 文档、许可、字段、速率和血缘审核后再做只读适配器 |
| SellerSprite MCP/API | 官方 MCP 以自然语言编排商品、市场、竞品、关键词、流量、评论、定价与广告研究；API 支持选择返回字段；MIT 社区仓库示范场景工作流、原始 JSON、结构化结果和报告分层 | 借鉴“锚点 SKU/问题→最小字段并行查询→原始 Evidence→口径/样本/缺失校验→规范化 JSON+报告”的研究编排，并落入现有 Source Adapter、Evidence、Market Recon 和工作台 | Amazon 信号冒充 Ozon 事实；个人 MCP 账户用于多人内部系统；共享 Key、MCP 批量爬取、硬编码秘密、估算销量/利润晋升 actual | 当前仅做工作流对标；真实 Ozon 证据仍不足且完成 Provider 准入后，才评估许可的 provider-neutral 只读 API Adapter |
| 妙手 ERP | 多平台采集/刊登、货盘、AI 内容、定价模板、订单、采购、库存、物流与仓储协同 | 借鉴采集箱→认领→编辑→审批的工作台；批量任务显示进度、失败项和重试 | 采集后直接刊登、自动采购、自动调价；让 ERP 成为 Canonical Product 或利润真源 | 先实现 KJDS 内部采集箱和只读批量差异预览 |
| 51Selling | Ozon 刊登、订单、退货、库存、账单/毛利报表；账单拉取字段有来源标识，未覆盖费用会保持未归类；多平台采集、批量编辑、发货扫描和称重 | 借鉴订单异常队列、扫描/称重实测、逐字段来源标识、未归类费用队列、批量编辑预览、账单到毛利的导航 | 未复核账单直接成为毛利；自动回复或批量写操作绕过审批 | 把实测重量、费用原件和异常队列接入现有 Passport/Evidence/CM3 |
| 店小秘 / 马帮 / 易仓 | 厂商公开页面覆盖采集/搬家、刊登、订单、采购、仓储、物流、财务和多维分析；易仓强调多平台利润和业财一体 | 借鉴按角色的一站式导航、跨店铺异常中心、库存—采购—财务联动 | 把厂商营销数字当基准；让第三方数据库拥有 KJDS 证据、利润或审批真源 | 连接器只做来源专用适配，先原件、后映射、再对账 |
| LinkFox | 官网公开呈现 Agent、AI 作图、Listing、竞品评论洞察、多源选品、定时报告、批量生图、团队资料库和按积分/算力计费；公开平台清单以 Amazon、Walmart、Temu、TikTok 等为主 | 借鉴“对话目标→工具编排→报告/素材”的低门槛入口、视觉资产工作台、团队算力与素材治理 | 把营销案例当效果证据；未见 Ozon 官方集成就推断已打通；只生成内容却缺商品、供应商、利润、订单和结算血缘 | 把 LinkFox 视为内容与研究能力供应候选；任何 API、平台覆盖、数据许可、模型成本和导出合同先做准入复核 |
| Ozon Seller | 官方页面提供商品搜索词分析、FBO 库存/周转、促销效果、广告工具、类目趋势和内容建议；部分指标受 Premium/Premium Plus 限制 | 以“搜索→曝光→卡片→订单→利润”的漏斗组织增长诊断；明确订阅/接口缺口 | 绕过订阅、抓取受限数据、把公开页面估算当店铺事实、未经批准自动投放 | 只读 API/正式导出优先；受限指标明确 `subscription_required` 或 `no_data` |
| Amazon Seller | 官方生成式 AI 可从文字、图片、网址或表格生成/增强 Listing，Seller 保留接受、编辑或拒绝控制；Product Opportunity Explorer 用搜索、点击、购买、评价和价格寻找未满足需求 | 多模态输入→结构化属性→质量建议→人工复核；候选机会与现有组合联动 | 把模型生成属性直接视为真实规格、合规或效果保证 | 生成内容必须回到 Product Passport、Evidence、QA 和审批 |
| Shopify Sidekick | 在店铺上下文中分析数据、生成内容/工作流，并在应用前展示变更；支持 ShopifyQL 报告和柱/线/环形图导出 | 自然语言作为导航/解释层，权限沿用用户角色，图表可回到查询和数据 | 另建不受权限控制的“超级 Agent”；聊天结论绕过事实与审批 | Agent 只调用版本化读模型和受控命令，不直接拥有平台凭证 |
| eBay Seller | 官方 AI Listing 从图片/少量输入补充标题、类目、属性、价格和运费建议；另有批量 Listing、背景清理和 Listing 图片生成短视频 | 冷启动引导、图像→结构化商品、批量预览、素材工具 | 把视觉识别结果当产品真相；无权使用来源不明素材 | 每个推断保留来源/置信度，批量动作先 Diff、风险分组和人工确认 |

## KJDS 必须超越的五点

1. 每个数字都能回到原件、哈希、时间、适用范围和责任人。
2. 计算器默认值只能形成 scenario；实际利润只认供应商、物流、平台、税务和银行原件。
3. 外部市场数据先进入 C/D 级研究收集箱，只有独立指标级复核后才可能成为 A/B。
4. 批量动作先预览差异、风险和最大损失，再审批、限量执行、观察和回滚。
5. 平台适配器可替换；Canonical Product、Evidence、决策、利润和审计永远由 KJDS 持有。

## 独立工具决策：EvidenceOps Copilot 0.54.0

KJDS 已将 LinkFox 擅长的低门槛目标入口重新设计为独立的 `EvidenceOps Copilot`，但没有复制
“对话即结果”的产品假设。一个经营目标只会成为 `user_intent`；服务端随后从 KJDS 当前经营
简报与分析快照编译出已验证事实、明确 unknown、排序任务、责任 Agent、验证条件、禁止动作和
稳定计划哈希。目标、第三方营销信息或未来模型输出都不能晋升为经营事实、审批或执行许可。

该产品比单纯的 AI 作图、Listing 或报告工具更靠近真实经营闭环：

1. **事实优先**：先显示 Ozon 目录、库存、阶段和 Evidence，再讨论策略。
2. **未知可见**：缺供应商报价、CM3、订单、结算、银行或 FX 时明确阻断，不用演示数据补齐。
3. **任务可复验**：每项任务带来源、当前/目标、责任 Agent、下一动作和服务端验证条件。
4. **安全控制面**：首版只读，不联系供应商、不采购、不改价、不发布、不投放、不写平台。
5. **独立入口、同一内核**：Web 有单独产品入口，但共享 KJDS 身份、真源、Gate、审批和回读，
   不创建第二数据库、第二权限面或通用 Agent 市场。

这不构成 LinkFox 已接入 Ozon 的声明。LinkFox 继续按 C 级公开营销参考管理；研究、内容生成、
模型成本、素材权利和导出合同只有完成提供方准入后才可进入后续集成。

## 逐功能工具决策：Cross-border Capability Atlas 0.55.0

2026-07-26 使用未登录公开页面逐页复核 LinkFox 首页、服装套图、商品套图、设计器、AI 视频、
智能修图、批量生图、链接管理、Skills、Agent、Claw 与价格页。观察到的功能被拆为 10 个
能力域、49 个宏观叶子；公开价格矩阵进一步把会话/插件、商品/服装图、设计器、视频、POD、
修图、批处理、企业配额和 API 示例拆到原子层。KJDS 因而没有停在 49 个菜单项，而是在同一
机器注册表中建立 143 个原子点、14 条端到端价值流和 8 个经营控制面。

每个原子点都记录父能力、业务对象、操作类型、来源等级、输入输出、技术、Evidence 门、
责任/复核、失败队列、回读、KPI、SLA、市场/平台、状态和价值流成员关系；每条线记录对象
状态变化、入口/出口门、事件、异常、人工接管和适配器边界；每个面记录维度、真源、经营
决策、KPI、预警和写边界。这让 LinkFox 的单点创作能力真正接入选品、供应商、CM3、商品
Passport、内容、Listing、审批发布、广告、库存采购、订单履约、退货售后和结算对账。

| 能力域 | LinkFox 公开可见重点 | KJDS 超越点 |
|---|---|---|
| 灵感/商品/资产 | 灵感库、图片交付、商品/链接、品牌与合规、素材库 | 来源/许可/时间/Evidence、Canonical Product、Passport、团队作用域 |
| AI 服装视觉 | 服装套图、真人换模特、换场景、穿衣、姿势、穿戴 | 肖像授权、商品/颜色/尺寸保真、偏差评测、RU 尺码和 Ozon profile |
| AI 商品视觉 | 商品套图、商品替换、场景裂变、翻译、手持、白底/特写 | Passport grounding、OCR/属性 QA、IP 相似性、实验 ID 与真实效果回读 |
| AI 修图 | 智能修图、多图融合、重绘/消除、换色、裁剪、放大、扩图、抠图 | 结构化 edit plan、before/after diff、mask/色差/边缘 QA、逐项批量隔离 |
| 视频/POD/设计 | 图转视频、口播、复刻/剪辑、POD、设计器/模板 | 镜头 JSON、时序保真、ASR/OCR、声音/音乐/人物权利、print preflight |
| 批量与企业 | 批量项目、并发/算力/保存期、团队协作 | 幂等、预算、逐项失败、成本/质量/人工/业务价值账、职责分离 |
| Agent/Skills/Claw | 商品库、词库、定时任务、技能市场、跨境专家、云电脑/记忆 | 目标→事实/unknown/任务合同；Skill 准入/评测；临时权限；一次许可与人工接管 |
| 市场/Listing | 选品/市场/评论/前台搜索类 Skills、Listing 快捷入口 | Ozon 官方数据优先、测量合同/双来源、字段级来源、俄语母语与发布分离 |
| 供应链/利润/增长 | 1688 搜索/图搜；公开创作页未形成 Ozon 财务/CM3/履约闭环 | 三家独立报价、15 项成本、库存履约、广告止损实验、结算/银行/FX 对账 |
| 治理/全球 | 多平台链接过滤、模型名/调用量/套餐宣称 | Evidence/Lineage、L0–L4、模型/Skill 影子评测、官方合同与适配器准入 |

### LinkFox 公开价格矩阵的原子拆分

| 公开分组 | 页面可见原子项 | KJDS 补齐的经营合同 |
|---|---|---|
| Agent/会话/插件 | 作图 Agent、ZX-3.5/ZX-4 名称、个人模板、模板会话、敏感词、自由会话、智能问答、插件/页面识别、运营模板、智能分析 | 型号只保留 C 级观察；KJDS 增加 Objective、Evidence grounding、结构化 I/O、评测、预算、工具权限和人工接管 |
| 商品图/服装图 | 套图、替换、场景、手持、翻译、白底/细节、换模特、换场景、穿衣、姿势、穿戴 | Product Passport、权利、商品/服装保真、俄语 OCR/术语、平台 profile、逐资产 QA 与 manifest |
| 设计/视频/POD | 设计器、个人/团队模板、图转视频、口播、拼接、复刻、POD 场景、相似裂变、自由绘图、贴合、印花提取 | 可重放 Design/Timeline 合同、人物/声音/音乐/字体许可、关键帧真值 QA、print preflight 和交付清单 |
| 修图 | 智能修图、长图、局部重绘/消除、换色/2.0、裁剪、放大、扩图、精修、色差、印花、手部、抠图、批量抠图 | mask、before/after diff、ΔE、边缘/纹理/结构 QA、逐图失败队列、不可变 lineage |
| 企业 | 算力、账号、并发、无水印、历史、存储、优先级、企业素材、批量会话/图片、Team API 示例 | 配额/并发/存储/保留/优先级账本，团队作用域、逐项门禁、幂等与恢复；API 必须独立准入，公开示例不等于可用接入 |

前沿实现不等于堆叠依赖。首版选择 Next.js 16、React 19、TypeScript 5.9、FastAPI、
PostgreSQL 和原生 HTML/SVG；多模态生成通过 provider-neutral adapter，输出通过 JSON
Schema、商品保真/OCR/ASR/合规 QA、champion/challenger 影子评测和人工批准。只有真实图查询、
长事务或检索基准证明现有内核不足时，才复审图数据库、Temporal 或向量库。

机器可读逐功能真源见
[`registries/cross_border_capability_atlas.json`](registries/cross_border_capability_atlas.json)，
架构边界见
[`ADR-0027`](../adr/ADR-0027-cross-border-capability-atlas.md)，完整点—线—面经营合同见
[`12_CROSS_BORDER_POINT_LINE_SURFACE_OPERATING_GRAPH.md`](12_CROSS_BORDER_POINT_LINE_SURFACE_OPERATING_GRAPH.md)。

## 2026-07-26 产品与技术架构结论

### 清晰运营流

```text
官方/授权数据
  → 需求与候选
  → Product / Compliance / Quality Passport
  → 1688/Alibaba RFQ 与三家独立报价
  → 物流计费重 + 15 项全成本 + CM3
  → 图片/视频/俄语 Listing QA
  → 价格/内容/广告有上限实验
  → 双人审批 + 一次许可 + 平台回读
  → 订单/退货/结算/银行/FX 对账
  → 经营结果与负知识回灌
```

前端每一步必须显示 `current/target`、事实成熟度、来源 ID、Owner、下一动作和副作用边界。没有真实
历史序列时显示缺口，不提供“模拟 GMV 上升”曲线。

### 分层架构

1. **Source Adapter**：Ozon、供应商、物流、银行和第三方研究各自版本化；原始响应先固化。
2. **Evidence / Canonical Fact**：哈希、血缘、有效期、独立复核；事实、推断、方案和结果分层。
3. **Domain Services**：商品、供应链、物流、CM3、内容、增长、执行、财务各自持有业务不变量。
4. **Decision & Control Plane**：Readiness、Action Policy、审批、一次性命令、回读、止损和事故。
5. **Operating Analytics Projection**：只读聚合阶段、漏斗、覆盖率和 Listing 画像，不建第二真源。
6. **AI Experience**：解释、生成候选方案、编译受控任务；模型可替换，权限不可自我升级。

相比“每个场景一个 Agent + 一个脚本”，该结构让模型、Prompt、平台和 ERP 都可替换，经营事实和
安全边界保持稳定。

## 实施顺序

### P0：研究收集箱

状态：`DONE_ENGINEERING`（BAS-062）；真实第三方文件和双身份业务复核仍待执行。

- 保存提供方、原始 ID/URL、捕获时间、原始字段、Evidence、许可状态和 `requires_review`。
- 去重但不覆盖历史；同一信号可绑定多个候选，不能直接创建 Listing。
- 支持手工导出优先；Open API 只有完成准入后才启用。

### P1：场景模板与比较

状态：`DONE_ENGINEERING`（BAS-063）；真实 Ozon 账单、物流账单、税务和银行凭证仍待逐项替换预估值。

- 按全成本合同保存模板，不允许使用无解释的“其他成本”。
- 并排显示采购、重量/体积、佣金、广告、物流、退款、税费、FX 和资金成本。
- 每项标注 `estimate/actual/unknown`、来源和有效时间；展示敏感性与盈亏平衡点。
- 当前模板为服务端 `ozon-ru-full-cost-v1`；15 项逐项状态和 Evidence 已进入原有场景 JSONB，未知/缺证据/未分类成本会阻断采购和 Listing，且始终不自动定价。

### P1.5：三候选组合决策台

状态：`DONE_ENGINEERING`（BAS-064）；真实候选与真实账单仍待录入。

- 借鉴 Seerfar 的候选对比效率和 ERP 的集中工作台，但只展示通过 KJDS 候选资格门的 Product。
- 每家供应商只采用最新报价和该报价的最新场景；旧报价上的历史利润不参与当前 readiness。
- 同屏展示 Passport、供应商数、完整正 CM3、最佳供应商和阻断原因，并保持 `advisory_only`。
- 服务端固定禁止自动选品、采购、定价和上架；详细三报价和逐项 Evidence 仍走原有受控流程。

### P1.7：证据支撑的经营异常工作台

状态：`DONE_ENGINEERING`（BAS-065）；真实 Gate 输入和经营 Owner 仍待补齐。

- 借鉴 51Selling/妙手把分散问题收敛到单一工作台，但不复制“异常即自动处理”。
- Gate 阻断只从服务端 readiness 读取稳定 requirement、当前/目标、责任角色和下一动作；页面不重算放行规则。
- 事故、受限执行命令和观察窗口继续保留真实 SLA、风险等级和升级账；资料缺口不伪造发生时间或逾期。
- 工作台只解释和导航，不自动补证、关闭事故、释放熔断或执行任何平台写入。

### P1.8：逐项成本来源标识与未归类费用暴露

状态：`DONE_ENGINEERING`；真实财务原件仍需独立 Reviewer 和版本化会计分类。

- 借鉴 51Selling 在毛利字段旁标识平台账单拉取来源，但 KJDS 显示的是自己的 Evidence 标识，而不是厂商内部图标。
- 报价与 CM3 卡片可以展开查看 15 项成本的 `预估/实际/未知`、Evidence 尾号；没有 Evidence 就明确显示“无证据”。
- Ozon 费用代码继续显示“已覆盖/待批准”，未知代码不能被塞入“其他费用”。
- Ozon 应计文件进入同一独立来源复核界面；因为它混合销售、折扣、佣金、物流和补偿，来源通过后仍禁止直接入利润账。

### P2：受控批量工作台

- 批量编辑先产生 Diff，不直接写平台。
- 按低/中/高风险拆批；设置条数、预算和价格变动上限。
- 逐项失败可恢复，整批可暂停；平台写入仍使用既有 Approval、Kill Switch 和审计。

## 当前证据边界

- 萌啦官网当前页面可直接核对上述定价字段和模板/物流比较，但公式版本和费率权威性未验收。
- Seerfar 官网可直接核对趋势、关键词、竞品监控和 Open API 入口；本次 Open API 文档抓取超时，接口合同保持 `requires_review`。
- SellerSprite 官方 MCP/API 页面可核对工具域、字段选择和 Codex 配置方式；官方使用规则把个人 MCP 使用与内部系统集成分开，后者应使用 API。当前没有账户、订阅、Key、付费调用或 KJDS Adapter；其 Amazon 数据只作 C 级跨市场研究参考。
- 妙手官网可直接核对多平台采集/刊登、定价、订单、库存、采购和物流等模块；这些是厂商公开声明，不是 KJDS 的真实执行验收。
- 51Selling 官方 Ozon 帮助页可核对刊登、订单、退货、库存、账单和毛利报表；其账单教程还明确列出字段映射、“拉”来源标识和未归类费用处理。它证明公开产品行为，不证明算法完整、映射正确或我方账单适用，仍需账号内只读验收。

## 官网核对入口

- 萌啦定价精灵：`https://ozon.menglar.com/tools/`
- Seerfar 功能与 Open API 入口：`https://www.seerfar.cn/features/`
- SellerSprite MCP：`https://open.sellersprite.com/mcp`
- SellerSprite 使用规则：`https://open.sellersprite.com/help/36`
- SellerSprite 商品/市场 API：`https://open.sellersprite.com/api/2`、`https://open.sellersprite.com/api/29`
- SellerSprite Codex 配置：`https://open.sellersprite.com/mcp/40`
- MIT 社区场景工作流：`https://github.com/liangdabiao/amazon-sorftime-research-MCP-skill`
- 妙手 Ozon 入门：`https://erp.91miaoshou.com/help_center/article_2278.html`
- 51Selling Ozon 功能：`https://www.51selling.com/HelpDocument/Details/156`
- 51Selling Ozon 账单教程：`https://www.51selling.com/HelpDocument/Details/176`
- Ozon 商品搜索词分析：`https://seller.ozon.ru/media/news/novaya-analitika-po-zaprosam-tovarov/`
- Ozon FBO 周转报告：`https://seller.ozon.ru/media/news/fbo-novoe-v-otchyotah-po-prodazham-so-skladov/`
- Ozon 类目/内容/物流建议：`https://seller.ozon.ru/media/trends/issledovanie-kategorij-dom-i-sad-mebel-stroitelstvo-i-remont-osen/`
- Amazon 生成式 AI Listing：`https://sellingpartners.aboutamazon.com/product-listings-with-gen-ai`
- Shopify Sidekick：`https://help.shopify.com/en/manual/shopify-admin/productivity-tools/sidekick`
- Shopify Sidekick 图表与导出：`https://changelog.shopify.com/posts/sidekick-data-visualization-and-export-updates`
- eBay Magical Listing：`https://innovation.ebayinc.com/stories/magical-listing-tool-harnesses-the-power-of-ai-to-make-selling-on-ebay-faster-easier-and-more-accurate/`
- eBay AI 批量 Listing：`https://innovation.ebayinc.com/stories/ebay-empowers-sellers-with-innovative-tools-at-ebay-open-2024/`
- 店小秘：`https://www.dianxiaomi.com/`
- 马帮 ERP：`https://www.mabangerp.com/main_productErp.htm`
- 易仓 ERP：`https://www.eccang.com/erp.html`
- LinkFox 一站式入口：`https://www.linkfox.com/home`
- LinkFox 服装套图：`https://www.linkfox.com/draw/clothing-image-suite`
- LinkFox 商品套图：`https://www.linkfox.com/draw/product-image-suite`
- LinkFox AI 视频：`https://www.linkfox.com/draw/video`
- LinkFox 智能修图：`https://www.linkfox.com/draw/smart-repair`
- LinkFox 批量生图：`https://www.linkfox.com/draw/batch-generate-images`
- LinkFox 链接管理：`https://www.linkfox.com/linkManagement`
- LinkFox Skills：`https://skill.linkfox.com/`
- LinkFox Agent：`https://os.linkfox.com/`
- LinkFox Claw：`https://os.linkfox.com/claw`
- LinkFox 套餐与算力边界：`https://www.linkfox.com/price`

官方或厂商公开页面只证明其公开声明/界面能力。Ozon 订阅、API、地区、账号和时间范围可能限制可用
字段；KJDS 必须在真实账号中按条款、身份、速率和导出合同逐项验收。

机器可读边界见 [`registries/competitive_capability_patterns.json`](registries/competitive_capability_patterns.json)。
