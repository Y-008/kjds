# ADR-0100：KJDS 自研 ERP 与多平台竞品货源观察

| 元数据 | 值 |
|---|---|
| status | Accepted |
| date | 2026-08-14 |
| affects | BR-082 / BR-093 / BR-147 / BR-150 |
| decision owner | 经营负责人 |
| implementation owner | Intelligence + Sourcing + Product + Commerce Control |

## 背景

经营负责人明确：KJDS 必须是自研且唯一的经营工作台。竞品 ERP、选品插件和外部平台仅用于
功能对标、市场观察与货源发现。现有观察合同只允许 Ozon 与 1688，导致拼多多、淘宝、闲鱼、
义乌购和 TVCMALL 等真实来源无法保留原平台进入同一批量筛选链，甚至可能被错误标成 1688。

## 决策

1. KJDS Product/SKU、SupplierOffer、ProfitScenario、ListingDraft、订单、库存、财务和 Evidence
   是唯一 canonical authority；外部 ERP 只能是授权、可撤销、可回读的边缘适配器。
2. 扩展唯一 `MarketplaceObservation` 合同，支持 `ozon/1688/alibaba/pinduoduo/taobao/tmall/
   tvcmall/xianyu/yiwugo`；每个平台使用独立适配器和 host 白名单，不共享身份。
3. Ozon 是销售市场观察；其余平台是供应候选观察。`BatchOpportunity` 聚合所有供应平台，但保留
   `marketplace/source_url/external_item_id/supplier_ref/Evidence`，并继续使用精确身份+变体键匹配。
4. 只有 1688 已验证 checkout 语义可生成 `observed_checkout_price`；其他平台在独立 checkout
   合同落地前只能提交公开展示价等研究观察，不能冒充到手采购成本。
5. 多平台观察永远不自动创建 SupplierOffer、actual cost、正式利润、采购单、付款或外部发布。
   进入 KJDS 商品主档的只是待审核候选，后续沿用既有审批、Permit、Worker 与 readback。
6. 数据库扩展既有 marketplace check constraint；降级若存在新平台数据必须失败关闭，禁止删行。
7. 批量规模 50/100/200/500/1000 是筛选目标，不是虚构候选数量。输入不足时返回 source gap。

## 验收

- 每个新增平台都能获得唯一冻结适配器，且 host、语义权威和平台一一对应。
- API 与数据库接受已登记平台并拒绝未知平台。
- 同一精确 SKU 的跨平台供应观察进入同一候选，供应密度增加且原平台可追溯。
- 不同 SKU/变体不得合并；公开展示价不得变为正式 SupplierOffer 或正式利润。
- 既有 1688/Ozon 批量筛选、幂等、Evidence、权限和零外写测试保持通过。

## 非目标

- 本 ADR 不授权绕过登录、验证码、访问控制、平台限流或使用私有接口。
- 本 ADR 不引入第二 ERP，也不直接执行采购、付款、改价、广告或上架。

