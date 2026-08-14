# ADR-0035：统一 Commerce OS 与可审计 Agent Team

| 元数据 | 值 |
|---|---|
| status | Accepted for incremental implementation |
| date | 2026-07-28 |
| affects | BR-055 / BR-075 / BR-078–BR-085 |
| decision owner | 经营负责人 |
| implementation owner | Commerce OS |

## 背景

无忧易售、妙手、芒果店长、Maozi ERP 与荔枝 ERP/助手分别提供采集、商品库、
批量刊登、订单、采购、库存、物流、财务或运营分析体验；LinkFox 等产品还提供
商品素材库、批量生图、视频和 Agent 内容工作流。当前 KJDS 只把其中部分
流程登记为 C/D 级竞品模式，并仅实现 ERPNext `Item` 草稿同步；这不等于完整业务
覆盖。继续按产品逐个复制业务逻辑会产生多套商品身份、利润、任务和执行状态，无法
对账，也不能形成 AI Agent 的稳定工具接口。

## 决策

1. 新增一个 `CommerceOperatingSystem` 深模块。唯一外部接口以认证
   `tenant_ref + store_ref + as_of` 返回经营状态机、能力覆盖、当前对象、阻断、责任
   Agent、SLA、下一工作区和执行包络。客户端与 Agent 不重算 readiness。
2. 经营状态机固定为：
   `observe → identity → qualify → item_draft → content → listing_approval →
   publish → order → procurement_review → fulfill → settle → reconcile → learn`。
   每级只读取现有权威模块；没有事实时返回 `no_data/blocked`，不能用竞品功能声明
   或模型文本填充。
3. KJDS 原生经营内核覆盖以下能力族：市场与采集、精确商品/变体身份、供应商与报价、
   十五项利润、商品库、内容与媒体、Listing、订单、售后、采购、库存、物流、广告/
   促销、结算/到账、异常任务、团队权限和审计。无忧易售、妙手、芒果店长、Maozi、
   荔枝与 LinkFox 只是产品与运营流程基准，不是 KJDS 运行依赖、数据源或目标系统；
   KJDS 不要求连接这些产品才能完成任何经营闭环。
4. Adapter seam 只用于真正的外部经营系统，例如 Ozon Seller API/官方导出、1688
   允许的公开观察或授权导出、物流商、仓库、支付/银行和可选财务侧车。Adapter 状态
   必须诚实区分：
   `reference_only | import_ready | export_ready | connected_read |
   connected_draft_write | reconciled`。没有官方合同、授权凭证、样本回放与回读测试时，
   不得标记 connected 或 covered。
5. Agent Team 固定包含经营总控、市场雷达、商品身份、供应链、利润定价、内容媒体、
   Listing、订单履约、库存补货、结算对账、风险合规、实验学习十二个责任 Agent。
   Agent 只接收服务端事实快照，输出版本化内部 artifact、差异、任务或建议；不得直接
   写仓库，不得自批、不得签发 Permit、不得绕过验证码/限流/条款、不得自动采购付款。
6. 自动动作按风险分层：
   - 可自动：只读归一、去重、规则评估、利润复算、草稿生成、内部任务去重、回读比较。
   - 人工复核：事实晋升、供应商报价接受、内容/媒体 QA、价格/库存/广告建议。
   - 独立批准 + 一次性 Permit：任何 Ozon/供应商/采购/付款/广告外部写。
7. 商业套餐只改变配额、并发、协作、连接频率和可申请的执行包络；不得降低事实、
   Evidence、利润、审批、回读、Kill Switch 或 Compensation 门禁。
8. `D:\KJDS\ozon` 保持只读研究样本。不得复制 Cookie/localStorage、CSP 移除、
   `<all_urls>` 注入、内部接口、静态费用真源或未经许可的媒体。
9. 原生 AI 内容工厂以 Product/Quality/Compliance Passport 和已核权素材为唯一商品
   事实输入。竞品只能用于结构与差距观察；不得复制标题或图片。图片覆盖批量 Brief、
   主图/详情图/场景图/俄语信息图、固定工作流版本、成本/延迟、部分失败、幂等重试和
   Delivery Manifest；视频覆盖已批准商品图、人工确认脚本/字幕、有权音频和固定
   FFmpeg 多画幅链。所有产物记录输入哈希、模型/模板/编码器版本、Lineage 与 QA，
   全过后才可被 Listing 草稿引用；A/B 指标必须回到转化和结算后 CM3。
10. 通用 ERP、媒体、Agent 与可观测组件的复用由
    [ADR-0036](./ADR-0036-open-source-reuse-and-agent-tooling.md) 管理。复用目标是减少
    非差异化自研面积，不允许引入第二套经营真相或让通用框架取得审批/执行权威。

## 首个可验收切片

- 认证 `GET /v1/commerce-os/workspace` 动态组合 Truth/Governance、Batch
  Opportunity、利润 ERP、Operating Analytics/Workbench 与当前连接器状态。
- 返回上述完整状态机、相对五款业务基准的原生能力差距、十二 Agent 的当前任务和稳定
  快照哈希；不得把“连接五款 ERP”列为完成条件。
- Web `/commerce-os` 直接显示服务端状态、真实漏斗、覆盖差距和 Agent handoff；
  支持授权店铺选择、loading/error/no_data/forbidden、桌面和 390px。
- 匿名 401、越权 403、确定性 `as_of`、坏 Evidence/rule gap/no_data、外部写始终为
  false 都有回归测试。

## 后续增量

按同一接口继续完成 KJDS 原生 PIM、OMS、采购、库存/WMS、履约、财务、BI 与 CRM
经营模块，再逐步加入 Ozon、1688、物流、仓库和支付/银行官方导出或授权连接器，以及
真实小流量 Pilot 与订单—采购—结算回读。任何新增 Adapter 必须先有数据合同、作用域、
幂等、速率、撤销、回读、错误分类和卸载方案。
