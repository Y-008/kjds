# Market Entry Gates

**截点**: 2026-08-02  
**判断原则**: 只要某一门槛仍然依赖未核实的费用、牌照、认证、税务或制裁边界，就不能标 `PASS`。

## Gate 1 - 卖家主体与开户注册

- Status: `PARTIAL`
- Evidence:
  - Ozon Seller 首页明确写明可以注册、上传商品并开始销售。
  - FTS 说明俄罗斯纳税主体使用 INN，企业和外国组织都有对应编号规则。
  - Ozon 的跨境卖家条款索引和税务居住证索引显示，主体类型和税务文件会影响后续合同路径。
- What is known:
  - Ozon 有正式卖家注册入口。
  - 俄罗斯税务身份不会完全缺位，INN 是基础输入。
- What is not yet known:
  - 目标主体应该是中国公司、俄罗斯本地实体、还是 Ozon 的特定跨境合作主体。
  - 是否需要本地公司、当地授权代表、税务代理或认证合作伙伴。
- Owner:
  - 商务负责人
  - 法务/税务负责人
- Promotion condition:
  - 拿到一份针对目标主体的律师/税务意见书，明确开户注册路径、税务登记、签约主体和付款主体是否一致。

## Gate 2 - 类目 / 禁限售

- Status: `PARTIAL`
- Evidence:
  - Ozon 商品内容政策和品牌页索引显示存在受限销售商品、年龄限制、内容政策和品牌文档要求。
  - Ozon 视频内容规则明确限制酒精、香烟、价格、联系方式、社交媒体等展示元素。
  - EEC 与 Честный ЗНАК 都说明部分类目有强制标识或特别监管。
- What is known:
  - 并非所有商品都能直接上架。
  - 服装、鞋帽、化妆品、食品、药品、酒类、烟草等类目很可能触发额外规则。
- What is not yet known:
  - 目标 SKU 的逐项禁限售、品牌授权、年龄分级和站内内容合规结果。
- Owner:
  - 商品合规负责人
  - 运营负责人
- Promotion condition:
  - 对每个 SKU 做 HS code / Ozon 类目 / 俄文文案 / 认证文件 / 标识义务五联映射。

## Gate 3 - 平台佣金与费用

- Status: `PARTIAL`
- Evidence:
  - Ozon 结算页明确说销售报表会显示 delivery cost 和 additional Ozon services，并指向 commissions and rates。
  - Ozon 费用索引页明确存在 Sales Fees Archive、Delivery Cost Calculation、Returns / Unredeemed Orders / Cancellations、Penalties 等模块。
- What is known:
  - 平台费用并非单一佣金，而是由销售佣金、履约费、配送费、退货费、取消费和附加服务费组成。
- What is not yet known:
  - 目标类目的当前费率表、促销/折扣对费率的影响、仓配模式差异。
- Owner:
  - 财务负责人
  - 价格策略负责人
- Promotion condition:
  - 拉取目标类目的最新费率表，并用真实 SKU 算出到手毛利区间。

## Gate 4 - FBO / FBS / 跨境物流与退货

- Status: `PARTIAL`
- Evidence:
  - Ozon 的索引页显示存在 Fulfillment、Sale from Partner Warehouse (FBP)、Return of Products、Available Warehouses、Delivery Cost Calculation 等模块。
  - 结算页与费用索引页都把配送费和退货费作为核心可见项。
  - Ozon 2026-05-06 版代理协议覆盖运输、配送、取消件退回/销毁、包装、合规文件、费率附件，并单列中国及相关地区发货的声明价值边界。
- What is known:
  - Ozon 至少存在仓配/伙伴仓/退货相关的明确业务模块。
- What is not yet known:
  - 哪一种模式适合 RU-001。
  - 入仓、出仓、退货回流、滞销、销毁和再上架的实际成本。
- Owner:
  - 物流负责人
  - 仓配负责人
- Promotion condition:
  - 先拿 1 个试验 SKU 做只读路由验证，再决定 FBO/FBS/跨境方案。

## Gate 5 - 收款、汇兑与制裁风险

- Status: `UNKNOWN`
- Evidence:
  - Ozon 结算公开页已限定中国卖家参数，但页面内容可能受登录状态和已签合同影响，不能仅凭公开渲染结果断言中国卖家的可用银行、币种或打款路径。
  - 公开一手来源未把“制裁筛查、冻结条件、拒付路径、合规银行名单”说明到可执行程度。
- What is known:
  - 收款路径必须按签约主体、卖家国家、合同和银行共同确认，不能从其他国家参数外推到中国卖家。
- What is not yet known:
  - 具体银行、收款行、结汇链路、冻结和拒付场景。
  - 制裁筛查责任在平台、银行、支付机构还是卖家。
- Owner:
  - 财务负责人
  - 合规负责人
  - 外部银行/支付顾问
- Promotion condition:
  - 取得已认证中国卖家后台或已签合同中的结算条款、收款行书面可接入确认，以及制裁筛查/黑名单/拒付处置说明。

## Gate 6 - 关税和 VAT

- Status: `PARTIAL`
- Evidence:
  - 俄罗斯税法典第二部分明确涉及货物进口到俄罗斯境内及其他管辖区域的特殊税务处理。
  - FCS 官方页面提供货物通关、税费管理和统一税费规则入口。
- What is known:
  - 进口货物一定要进入海关和税务框架，不存在“完全自然放行”假设。
- What is not yet known:
  - 目标 SKU 的海关编码、关税税率、进口 VAT 处理、代缴情形、申报主体。
- Owner:
  - 税务负责人
  - 报关负责人
- Promotion condition:
  - 完成 SKU 级 HS code、原产地、申报价值、Incoterms 和税负表。

## Gate 7 - EAC / 商品认证 / 俄文标签

- Status: `PARTIAL`
- Evidence:
  - Ozon 明确列出 Documents for Selling、Brand Certificates、Product Quality Certificates、Safety Data Sheet 等资料入口。
  - EEC 新闻明确说明 EAEU 标识规则和技术法规下的商品标识要求。
- What is known:
  - 认证、标签和说明书不是可选项，而是很多类目的先决条件。
- What is not yet known:
  - 每个 SKU 到底需要哪一种技术法规符合性文件、证书、声明、注册证或俄文标签。
- Owner:
  - 合规负责人
  - 产品负责人
- Promotion condition:
  - 每个 SKU 拿到持牌机构出具的合规矩阵和俄文标签样稿。

## Gate 8 - Chestny ZNAK 适用性

- Status: `PARTIAL`
- Evidence:
  - Честный ЗНАК 官方站说明其为国家商品数字标识系统，并强调全链路可追溯。
  - EEC 公告显示轻工类商品等持续扩围，部分类目可能禁售未标识商品。
- What is known:
  - 标识系统已经是俄罗斯零售和电商的重要基础设施。
- What is not yet known:
  - RU-001 的目标 SKU 是否命中强制标识目录，以及需要怎样的代码生成、贴标和回写。
- Owner:
  - 合规负责人
  - 供应链负责人
- Promotion condition:
  - 形成 SKU -> 标识目录 -> 操作步骤 -> 责任人的落表。

## Gate 9 - 个人数据、客服、消费者权益

- Status: `PARTIAL`
- Evidence:
  - Roskomnadzor 文档要求在线收集个人数据时使用位于俄罗斯境内的数据库。
  - Rospotrebnadzor 对远程销售和网购退货给出明确消费者指引。
  - EEC 电子商务消费者权益共识强调退货、退款和争议处理时限。
- What is known:
  - 个人数据、语言、退货和投诉处理都不是“后续优化项”，而是前置义务。
- What is not yet known:
  - 俄文客服 SOP、数据存储架构、投诉时限、退货地址和退款执行链路。
- Owner:
  - 客服负责人
  - 隐私/安全负责人
  - 法务负责人
- Promotion condition:
  - 出具俄文隐私政策、客服模板、退货流程和数据处理流程图。

## Gate 10 - 合同与税务边界

- Status: `UNKNOWN`
- Evidence:
  - Ozon 2026-05-06 版代理协议明确约定代理服务、报告与结算、责任、适用法、争议解决、单方修订和终止机制，并要求另行签署商业条款。
  - 公开页面没有把“谁是合同相对方、谁承担税负、是否形成常设机构、是否需要本地代理”说到最终可执行。
- What is known:
  - 合同边界和税务边界是存在的。
- What is not yet known:
  - 适用法、争议解决、税务居民身份、代理链条和可能的常设机构风险。
- Owner:
  - 外部律师
  - 外部税务顾问
- Promotion condition:
  - 拿到持牌律师/税务师的书面意见，且与平台合同文本一致。

## 总体结论

- `PASS`: 0
- `PARTIAL`: 8
- `MISS`: 0
- `UNKNOWN`: 2

因此当前总判定为 `NO-GO`。
