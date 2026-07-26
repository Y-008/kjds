# BAS-097 真实商品供应商 RFQ 询价包验收

- 日期：2026-07-26
- Requirement：BR-072、BAS-097
- ADR：`docs/adr/ADR-0023-supplier-rfq-package.md`
- 实现分支：`feat/supplier-rfq-packages`

## 业务缺口与结论

已有 Ozon Listing 已经绑定 Canonical Product，供应商报价权威门也能固化、独立复核并最终化三家
报价；此前缺少的是两者之间的可比较询价合同。本次新增一个深接口
`SupplierRfqWorkspace`：它在一个调用内复验当前目录哈希和绑定、区分目录观察与采购要求、生成完整
中文询价正文、固化不可变 Evidence、处理幂等和建立血缘。

询价包只是真实业务准备，不等于供应商已经收到、回复或接受。平台不会把公开价、目录属性或 AI
猜测伪装成确认报价。

## 真实输入

本次通过正式 API 对当前店铺商品执行受控回放：

- 店铺作用域：`ozon-primary`
- Seller Offer ID：`2105343364UB`
- Marketplace SKU：`2216781923`
- Canonical Product：`prd_2215304aca03f42ab0921102a2d58de9`
- Canonical SKU：`ozon:ozon-primary:2105343364UB`
- Catalog Evidence：`evd_dc94091bb94d490ba8866caad7548415`
- Catalog item hash：`8631d985815528f7eec912dd73d48f40e2cd10bc6e472fba265a98c21f4fa55d`
- 目录重量/尺寸：`11.999 kg`、`37.9 × 31.9 × 24.9 cm`

目录标题仍含机器翻译污染，目录媒体仍为 `unverified_external_reference`。这些内容只作为供应商重新
确认的上下文，没有被提升为采购规格、合规结论或素材权利。

## 冻结的采购要求

正式 `POST /v1/sourcing/rfq-packages` 使用当前 item hash、`confirmed=true` 和幂等键
`2105343364UB-20260726-v1`，冻结：

- 数量阶梯：1、10、50、100 件；
- 额定载重 500 kg、钢丝绳 7.6 m、220V±10%/50Hz、手动/有线/无线三控；
- 提升速度、钢丝绳直径/材质/破断载荷、安全保护、完整配置和插头/功率逐项确认；
- 样品、含税发票、交期、日产能、MOQ、报价有效期、国内运费和售后条款；
- 营业执照、生产主体、已有合规文件及编号、质检报告和中俄文说明书；
- 单件净重/毛重/箱规、防潮防跌落、中性/定制包装和条码能力；
- 交付至河北保定指定集货仓，最终地址下单前确认；
- 明确拒绝以低载重档位作为 500 kg 商品的引流报价。

## 不可变结果

- RFQ Evidence：`evd_ad50f959c4904a05852b0551f34761f3`
- Evidence Grade：`C`
- Package hash：`2340cf1342efd687c3bc47abc75d3a487b1ab0db6f3165000d8dcb043ab40ca4`
- 状态：`draft`
- 第一次请求：`idempotent=false`
- 第二次相同请求：`idempotent=true`，返回同一 Evidence
- `source_offers`：0
- `supplier_quote_source`：0

数据库血缘：

1. Catalog Evidence → RFQ Evidence：`catalog_context_for`
2. RFQ Evidence → Canonical Product：`rfq_package_for`
3. 后续上传真实回复时，RFQ Evidence → Quote Evidence：
   `supplier_response_context_for`

第三条已由集成测试覆盖，但本次真实回放没有虚构供应商回复，因此数据库中尚未出现该边。

## 外部动作边界

RFQ 权威字段全部保持：

- `counts_as_supplier_quote=false`
- `formal_offer_eligible=false`
- `automatic_supplier_contact=false`
- `automatic_procurement=false`
- `automatic_payment=false`
- `automatic_listing=false`
- `automatic_marketplace_write=false`

本次没有联系 1688 供应商、发送消息、创建订单、采购、付款、改价、投广告、发布或写入 Ozon。
运营可在前台复制询价正文，再在已登录供应商渠道中人工发送；收到原件后必须回到报价权威门上传。

## 前台验收

Playwright 在真实 Compose Web 的 `#sourcing` 工作区验证：

- `/auth/session`、RFQ、目录、Product、Evidence 等业务请求全部 HTTP 200；
- 页面显示 1 个真实询价包和 0 份已接受报价；
- 显示正确 Offer、Marketplace SKU、数量阶梯、重量、尺寸、Evidence 和 package hash；
- 完整询价正文可展开，复制按钮成功，状态明确提示“复制不代表已发送或已取得报价”；
- 供应商回复表单可以选择对应 RFQ；
- 三家 CM3 最终化按钮因 0 份已接受报价而保持禁用；
- 浏览器控制台 0 error、0 warning。

本地忽略目录截图：
`output/playwright/BAS-097-supplier-rfq-package.png`。

## 当前仍需真实业务完成

1. 由运营在供应商渠道向至少三家独立主体发送冻结询价正文；
2. 取得三份同规格、当前有效的确认报价或形式发票；
3. 上传每份回复并绑定本 RFQ，由另一身份完成五项独立复核；
4. 复验含税/未税价、MOQ、交期、包装、国内运费、资质与样品；
5. 结合版本化物流线路和十五项全成本生成三家 CM3；
6. Passport、俄语母语复核、配送覆盖、同行同款与转化事实仍需补齐。

在这些真实输入到达前，系统不会用公开展示价代替采购价，也不会让 AI 自动制造订单或“出单”。
