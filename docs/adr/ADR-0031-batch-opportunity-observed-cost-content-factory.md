# ADR-0031：批量机会挖掘、观察成本 Pilot 与内容工厂

- 状态：Accepted
- 日期：2026-07-27
- 需求：BR-082 / BAS-104
- Owner：经营负责人、商品负责人、供应链负责人、工程负责人
- Approver：经营负责人
- 复审触发：首个真实 100+ 观察批次；首个小流量 Pilot 结算；第二店铺复制

## 背景

0.58 已能把一个已绑定 Ozon SKU 与三条 1688 观察放进 Evidence-backed
Portfolio Pilot，但真实库只有一个目录条目和三条供应观察。该接口不能把 100–500 个
跨商品观察做精确身份匹配、十五项观察成本评估、策略分类、变体计划和内容准备。继续在
浏览器或客户端拼装会复制利润口径、制造模糊匹配，并把“页面差价为正”误报为可发布。

## best_solution

### 硬约束

- 原始市场与供应观察必须保留来源、URL、时间、Evidence、置信度和价格语义。
- `observed_checkout_price` 必须绑定精确商品身份、变体、MOQ、购买数量、税费/国内
  运费边界和下单页可购买状态；它永远不是 Supplier Offer、actual 或正式成本。
- 销量未知就返回 `no_data`，评价、排名和缺货只能标记为代理信号。
- 金额使用 Decimal、显式币种、FX rate/date/Evidence；客户端不得计算评分或 CM3。
- 不复制 Product、Profit Scenario、Passport、ContentAsset、Approval、Permit、
  OperationsQueue 或执行事实源。
- `pilot_ready=0` 时不生成 Permit 或 Ozon 写入。
- 首发采用 `sale_triggered_jit`：供应商库存只作时效化可采购性观察，不预采购、不预付款。
  只有带有效 Evidence、已解析到同一 Product/SKU、`store_ref` 与授权店铺完全一致且状态为
  `awaiting_packaging` 的正式 `ozon_order` FactRecord，才允许产生
  `eligible_for_procurement_review`。状态未知、取消、退货、跨店或坏 Evidence 均失败关闭。
  该状态只是采购评审输入，不创建购物车、Supplier Order、付款、Permit 或外部写入。

### 方案比较

1. 在前端把 Ozon 与 1688 搜索结果拼表并打分：淘汰。口径漂移、无法重放、无法守恒。
2. 每个候选都先 RFQ：淘汰为默认路径。对标准品吞吐过低；只保留为高风险条件门。
3. 直接把公开价格写成 Supplier Offer：淘汰。污染报价与 CM3 权威。
4. 在 BR-081 上增加一个批量深模块族：选定。Observation 继续保存原始观察；
   scanner/scorer/classifier/variant/content 在同一服务端 seam 后组合并持久化不可变 run。
5. 延期：淘汰。现有单 SKU 模块无法验证批量策略。

## 决策

外部 Interface 保持为：

```text
BatchOpportunityWorkspace.prepare(store_ref, policy_id, limits, as_of, actor_id)
  -> BatchOpportunityRun
BatchOpportunityWorkspace.latest(store_ref)
  -> BatchOpportunityRun | no_data
```

Implementation 内部包含五个可测试但不向调用方暴露的深 Module：

- `BatchMarketScanner`：按服务端 `candidate_key` 精确连接 Ozon 市场项与 1688
  checkout 项，绝不做标题或图片模糊猜配；保留产业带、供应密度、价格带、评价/销量
  代理、促销、季节、库存、MOQ、交期、包装和距离信号。
- 漏斗必须把 `exact_identity_matched`、`checkout_cost_eligible` 与
  `fully_costed_candidates` 分开：同一 `candidate_key` 已在 Ozon/1688 两侧出现只证明
  精确身份连接；只有 `observed_checkout_price + checkout_verified + purchase_available`
  才进入 checkout 成本候选；十五项 Evidence 完整后才进入 fully costed。兼容字段
  `exact_matched` 仅作为 `exact_identity_matched` 的 deprecated 投影，不得再用“缺 checkout”
  冒充“缺精确身份”。
- `OpportunityScorer`：使用版本化 `ru-ozon-observed-cost-v1` 对十五项成本分别计算
  baseline/downside，输出筛选 CM3、现金占用、风险和守恒；没有有效 FX 或关键输入时
  阻断，不显示 actual。
- `StrategyClassifier`：输出淘汰、探索、受控铺货、精品精细化、套装、配件、变体或
  店群复制建议及原因、Evidence 缺口、预算和晋级门；70/20/10 只在 policy 中展示。
- `VariantExpansionPlanner`：只使用真实结构化属性和已验证父 SKU；缺 24h/72h/7d
  回读或两个结算周期时返回 blocked。
- `ListingContentFactory`：基于真实俄语标题/属性生成确定性文案与媒体 Brief；只有现有
  Product 的三类 Passport 和有权利且 QA 通过的 ContentAsset 才能 content_ready。
- `SaleTriggeredProcurementPolicy`：复用正式 Ozon FactRecord/Evidence 和当前精确供应观察，
  把 `waiting_for_ozon_order`、`eligible_for_procurement_review` 与
  `order_received_cost_or_supply_escalation` 投影到同一候选；正式订单前采购数量恒为零。
  出单后建议数量只来自该正式订单的未履约数量，仍须重新核验库存、checkout 成本和悲观
  CM3，且只能进入既有采购审批/执行权威，不拥有供应商或付款写权限。

run 与候选行是不可变重放投影；阻断只通过现有 OperatingTask/OperationsQueue 投影。
状态为 `observe→match→evaluate→content_ready→pilot→scale|stop→reconcile`。本模块
不创建 Product、Supplier Offer、正式 Profit Scenario、Listing、Approval、Permit 或
外部命令。

## 数据与失败模式

- Observation item 增加 candidate identity、购买数量、checkout 核验、税/运费边界、
  市场代理、供应地理、包材、媒体权利、置信度和回读字段；旧 0.58 数据向后兼容。
- 搜索引擎对 Ozon 官方页面的索引摘要必须使用
  `public_search_index_observation`，保留官方目标 URL、查询时间和索引时效语义；它是
  C 级市场观察，不得冒充直接页面读取、销量真值或精确商品身份。
- `observed_checkout_price` 缺明确数量、MOQ、可购买状态或下单页复核时拒绝捕获。
- `ozon_order` 缺 `store_ref`、Product/SKU 解析、有效原件或明确 `awaiting_packaging`
  状态时不得触发采购评审；手工 Order、市场观察、评论或 Listing 状态不能替代正式订单。
- 不同来源 identity 只有规范化字典与精确变体完全一致才匹配；任一身份字段或变体仍为
  `unknown/unspecified/pending/未确认` 等占位值时，服务端不得生成可匹配
  `candidate_key`，历史观察也在扫描时失败关闭为 observe/no_match。类别有冻结的精确身份
  schema 时还必须包含全部必填维度；例如桌下理线架必须同时绑定数量、结构、安装方式、
  长宽高和颜色，仅有“40cm 黑色”不得成为精确匹配。
- 十五项成本严格守恒；跨币种无有效 FX date/Evidence 时 blocked。
- 任何外部页面、验证码或许可故障只减少真实样本数并生成瓶颈，不补造数据。

## 迁移、回滚和验收

- Alembic 0053 为 observation item 增加批量语义并新增 immutable batch run/candidate 表。
- 固定样本覆盖精确匹配、错变体、MOQ、重复导入、坏 Evidence、过期 checkout、FX、
  十五项守恒、销量 no_data、策略门、变体回读、媒体权利和零外部副作用。
- Web 展示真实计数、供应地理、价格带、精确身份/checkout/完整成本分层漏斗、策略、风险、变体和回读；桌面与 390px
  无横向溢出。
- 首批真实执行必须报告实际观察、精确匹配、downside 正、内容就绪和 Pilot 数；不足
  100 时记录访问/匹配瓶颈，不修改计数。
- 回滚删除新 run/candidate 表和新增列，不改变 Evidence、Product、Offer、Profit、
  Approval 或执行账。
