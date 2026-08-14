# ADR-0097：自动经营闭环与上架链接货源反查

| 元数据 | 值 |
|---|---|
| status | Accepted for incremental implementation |
| date | 2026-08-08 |
| affects | BR-070 / BR-092 / BR-121 / BR-134 / BR-144 / BR-145 / BR-146 / BR-147 |
| decision owner | 经营负责人 |
| implementation owner | Product + Agent Platform + Sourcing + Listing |

## 背景

经营负责人要求 KJDS 在同一工作台内完成自动采集、AI 利润推荐、受控自动上架，并在
商品售出后可从平台上架链接准确反查货源渠道、供应商店铺和商品采购链接，由卖家自行
采购。现有系统已经有 Browser Capture Inbox、Product、SupplierOffer、ProfitScenario、
ListingDraft、AI Listing、Ozon Catalog、Approval、Permit、Executor 和 Readback；缺的是
把这些能力编译成一个经营视图，并消除 Ozon `offer_id`、平台数字 SKU 与内部
`SupplierOffer.id` 的命名歧义。

## 设计比较

| 方案 | 优点 | 风险与决定 |
|---|---|---|
| 深模块编排现有真源，实时投影反查链 | 无重复数据；每次按当前 Evidence、目录和绑定复算；可复用既有安全门 | **采用** |
| 新建 listing-source 映射表和第二套自动上架状态机 | 查询直接 | 会与 Product、ListingDraft、Catalog、执行回读漂移，形成第二 ERP 真源；拒绝 |
| 维持采集、利润、上架、采购四个独立页面 | 无代码变更 | 无法形成用户要求的一键闭环，也无法保证反查时使用同一 SKU；拒绝 |

## 决策

1. 新增深模块 `AutomatedCommerceLoop`，外部只提供两个命令/查询接口：
   - `start(...)`：从一个已进入现有 Browser Capture Inbox 的精确变体创建并推进既有
     `AiListingPipeline`，直到完成内部 dry-run 或遇到既有 Evidence/审核/批准门；
   - `workspace(...)`：按 exact tenant/entity/store/as-of 投影自动化进度、证据化利润建议、
     Ozon 上架身份和货源采购链接；可用 Ozon 商品链接、平台数字 SKU 或 seller offer ID
     精确反查。
2. 自动采集继续由现有合法 Provider/浏览器采集适配器写入 Browser Capture Inbox。模块
   不新建爬虫协议、不保存 Cookie，也不建立第二份采集数据库。
3. 反查主链固定为：
   `Ozon URL -> marketplace_sku/offer_id -> current scoped catalog -> canonical Product ->
   latest ListingDraft -> SupplierOffer -> source_url/store_url`。禁止把
   `ListingDraft.offer_id` 当成 Ozon offer ID；它是内部 SupplierOffer ID。
4. 平台商品链接只在 Ozon 当前目录返回数字 `marketplace_sku` 后形成
   `https://www.ozon.ru/product/{marketplace_sku}/`。未回读到平台 SKU 时仅展示 intended
   seller offer ID，不猜造上架链接。
5. `source_url` 是卖家自行采购的 `purchase_url`。供应商店铺链接仅从已采集
   `SupplierOffer.attributes` 的明确 `supplier_store_url/store_url/shop_url` 字段投影；缺失
   时保持 `null`。首切片不自动下单、不付款、不联系供应商。
6. “AI 利润推荐”是解释层，不是模型猜数。最终状态由现有 Decimal
   `ProfitScenario` 确定：十五项成本 Evidence 完整且 CM3 > 0 为 `recommended`；完整但
   CM3 <= 0 为 `not_recommended`；任何成本未知或 Evidence 缺失为 `awaiting_evidence`。
   输出保留 break-even、CM3、敏感性、Evidence 和缺口，AI 不得补齐报价、运费、汇率、
   退货率或平台费。
7. 自动上架只自动推进内部可逆步骤。真实 Ozon 发布继续复用独立俄语审核、Listing
   Approval、一次性 Permit、最小权限 Executor、权威 Readback 和 Kill Switch；本模块不
   签发 Permit、不直接调用平台写接口。
8. 首切片不新增数据库表或迁移。Product、SupplierOffer、ProfitScenario、ListingDraft、
   Catalog 和 AI Listing 是唯一真源。
9. 同款卖家与店铺递归扩品复用 Browser Capture 的 `store_catalog_candidates` 类型。店铺
   快照、新品差分、去重、探索预算和无增量停止规则按
   `docs/project/19_AUTOMATED_COMMERCE_AND_RECURSIVE_STORE_MINING_PRD.md` 分期落地；公开店铺
   观察只产生候选 Evidence，不绕过 RFQ 和利润 Evidence 门。
10. 渐进式自动化偏好保存在现有 exact-scope Store Profile JSON，不新增授权表：门店总开关和
    单打法开关均默认关闭，总开关不隐式开启任何打法；每个打法可冻结请求模式及有界额度。
    投影必须分离 `requested_mode`、`effective_mode`、`grant_ready` 和
    `runtime_execution_enabled`。Profile 偏好不是 Grant，真正执行继续复用既有 Policy、
    Approval、ExecutionPlan、Permit、Outbox 与 Readback。
11. 选择性主线接入分两期：BAS-219A 只接入深模块、Store Profile 机器合同、RFQ 只读回链、
    测试和文档；不接 `runtime.py`、Router、API/OpenAPI、Web、数据库、迁移或 G-1。隔离分支
    中的运行时/API/Web 只能在 BAS-186 释放共享 seam 后由 BAS-219B 独立接入和回滚。
12. 正式供应商报价继续由既有 `SupplierQuoteAuthorityService` / `SourcingIntakeService` 冻结
    原件、RFQ package、dispatch lineage 和非上传者复核。acknowledgement、clarification、
    alternative、platform notice 与 `latest_reply_unknown` 都不是 supplier-confirmed quote；
    当前 SupplierOffer 不能无损表达同一书面报价的 100/300/500 多阶梯时，必须保留完整
    Evidence、hash、身份/会话/message id 并阻断晋升，禁止截取单档冒充正式报价。

## 验收

- 精确 Ozon 商品链接可经当前目录绑定反查到同一 Product 的最新 ListingDraft、正式
  SupplierOffer、货源商品链接和可选店铺链接。
- Ozon URL 中的数字 SKU、纯数字平台 SKU 和 seller offer ID 均采用确定性解析；未知、
  多匹配、跨 scope 或未绑定状态失败关闭，不返回近似货源。
- 利润 Evidence 完整且 CM3 正/非正分别输出推荐/不推荐；缺任一正式成本时只输出
  `awaiting_evidence`。
- `start` 只调用现有 AI Listing 创建与处理接口，并在既有人工/证据门暂停。
- 自动化总开关关闭、单动作关闭、运行时未开放或授权未就绪时，有效模式必须保持
  `manual_each_action`；任何偏好和额度都不得令 `external_write_allowed` 变为 true。
- 测试证明不产生自动采购、自动付款、Permit 或平台写调用。
- 目录或 RFQ 权威的 scope、时间、snapshot、分页、计数、状态或控制信封漂移时，投影必须
  失败关闭；非有限利润数值、缺 Evidence、公开展示价和未知回复不得产生推荐或报价就绪。

## 失效条件

若 Ozon 官方稳定返回独立 canonical product URL、平台身份不再能由 seller offer ID 与数字
SKU 唯一表示，或一个 Product 合法绑定多个同时在售且来源不同的 Listing，则复审链接解析
和选择规则。只有现有真源无法表示一对多的已验证业务事实时，才允许追加版本化、不可变
绑定记录；不得先建重复映射表。
