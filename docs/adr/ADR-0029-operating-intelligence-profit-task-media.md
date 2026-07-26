# ADR-0029: Operating Intelligence 的利润、任务与媒体深模块

- Status: Accepted
- Date: 2026-07-26
- Owners: Finance Owner、Operations Owner、Content Owner
- Approver: 经营负责人
- Requirements: BR-078、BR-079、BR-080
- Review trigger: 第二平台、长任务需要跨机调度、首份正式税务/银行口径冻结或外部视频 Provider 准入

## Context

0.56 已把点、线、面穿透到真实只读工作区，但经营者仍缺少三条可复算链：
订单/SKU 实际利润、数据异常到内部任务、已核权素材到可交付图片/视频。现有系统已经拥有
FactRecord、Finance Entry、FX、Evidence、Cost Authority、ContentAsset、QA、
Approval、OperationsQueue 和 PostgreSQL；复制事实表、队列或权限面会造成语义分叉。

## Decision

采用三个小接口、深实现的应用模块，共享一个 PostgreSQL、Evidence Ledger 和身份层：

1. `ProfitLedgerService` 只读组合正式 FactRecord、Finance Entry、FX、经权威复核的
   成本 Evidence、Supplier Offer/Profit Scenario 与 Listing/Product 绑定。唯一归集维度
   是 `store_ref + product_id/SKU + order_ref + accounting_date + currency`。只允许
   SKU、订单自然键、source fact 或显式绑定；无法映射的金额进入 `unallocated/blocked`，
   禁止按销售额、数量或比例猜分摊。场景 CM3、应计、结算和到账贡献分别报告；证据不全
   时不得输出 actual profit。侵蚀桥按明确类别严格守恒，任何未分类差额进入
   `unallocated`。
2. `OperatingIntelligenceService` 使用版本化指标注册表、固定基线、最小样本、严重度、
   冷却期、Owner 和 Evidence 条件生成稳定指纹。异常扫描只创建内部
   `OperatingTask`；任务和不可变事件保存在 PostgreSQL，并投影进既有
   `OperationsQueueService`，不建立第二队列或工作流引擎。解决/驳回必须提供理由和有效
   Evidence。0.57.1 将认证规范入口冻结为
   `GET /v1/operating-intelligence/metrics` 与
   `POST /v1/operating-intelligence/anomaly-scans`；原有短路径继续作为同一 FastAPI
   endpoint 的兼容别名，不复制服务逻辑、认证或客户端规则。
3. `MediaWorkbenchService` 复用 ContentAsset、Evidence、Lineage、QA 与 Approval。
   图片只允许固定版本模板；ComfyUI 未准入或工作流不匹配时保持 blocked。视频首版不接
   外部生成 Provider，只接收已批准商品图、人工确认俄语脚本/字幕和有权利音频，经固定
   FFmpeg 参数生成 9:16、1:1、16:9 MP4、封面、字幕、关键帧、编码报告与 Manifest。
   PostgreSQL 租约承载任务恢复，不引入 Redis、Kafka、Temporal。所有产物先进入
   Blob/Evidence；只有 QA 全过的资产可被 Listing 草稿引用。

所有金额使用 `Decimal`、显式币种和 FX 生效日期；所有外部写仍由既有
Evidence、Approval、一次性 Permit、Readback、Kill Switch、Compensation 控制。本 ADR
不授予 Ozon 写权限。

## Rejected alternatives

- 新建 BI/会计事实仓：拒绝，会复制 Finance/Fact/Evidence 真源并提高对账风险。
- 按销售额或数量自动分摊未知费用：拒绝，结果不可证明且会制造虚假 SKU 利润。
- 新建第二任务队列或引入 Temporal/Redis/Kafka：拒绝，当前单机 PostgreSQL 租约足够，
  且现有 OperationsQueue 已是统一运营队列。
- 首版接入外部视频生成 Provider：拒绝，权利、合同、质量、成本和回读尚未通过准入。
- 在浏览器计算利润、异常或媒体 readiness：拒绝，会使客户端成为第二规则真源。

## Consequences and rollback

优点是经营状态可复算、未知项不会被美化、任务去重和媒体重放均有单一审计链。代价是
首版会显示较多 `no_data/blocked/partial`，并要求人工建立明确绑定。回滚可停止新路由和
Worker；迁移只新增表/索引，不改写既有 Evidence、Fact、Finance 或 ContentAsset 历史。

## Acceptance

- 利润测试覆盖 Decimal、币种/FX 日期、SKU/订单映射、未分摊、重复导入、坏 Evidence、
  跨币种阻断、侵蚀守恒与不重复计入。
- 异常任务测试覆盖最小样本、稳定指纹、冷却、状态机、不可变事件、解决 Evidence 和
  零平台副作用；OperatingTask 出现在现有 OperationsQueue。
- 媒体测试覆盖图片批量部分失败、权利过期、QA、幂等重试、视频租约恢复、FFmpeg 失败、
  输出哈希、字幕、画幅与 Manifest。
- OpenAPI、迁移回放、全量后端/Web/容器/认证浏览器和匿名 401 全部通过，并形成
  0.57/0.57.1 版本化 Evidence；规范别名与兼容短路径必须指向同一 endpoint。
