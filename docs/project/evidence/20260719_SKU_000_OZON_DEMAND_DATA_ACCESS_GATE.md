# SKU-000 Ozon 需求数据访问门

| 字段 | 值 |
|---|---|
| 日期 | 2026-07-19（2026-07-20 复验） |
| Gate | G0 |
| 状态 | PARTIAL_BLOCKED |
| 来源 | Ozon 官方 `data.ozon.ru`、已登录 Ozon Seller 分析页 |
| 证据等级 | B / `requires_review=true` |
| 平台写入 | 否 |

## 已核验

- Ozon 官方公开页说明“卖什么”分析应覆盖需求/销量、竞争和销售经济性，并给出热门商品、搜索查询、平均价格等示例。
- 公开页明确标注表格和类目数据为“报告示例，注册后显示真实数据”，因此示例中的商品、销量、搜索量和增长率不得写入候选研究清单。
- `https://data.ozon.ru/app` 当前登录态可访问，但真实分析首次开放要求账户主体勾选并接受 Ozon 要约与个人信息处理条件。
- 本次没有代替账户主体接受条款，没有提交表单、下载报告、修改 Seller 账户或触发上架。
- 已登录 Seller 分析页复验 2026-07-11 至 2026-07-17：33 次展示、1 次商品卡访问、0 加购、0 订单。该低流量基线只能证明现有目录不宜机械补货，不能证明任何新品有需求。
- 2026-07-20 进一步从 Ozon 官方文章定位到 Seller“我商品的搜索查询”真实入口；页面可读但“下载报告”实际触发 Premium/Premium Lite 订阅门，未生成原始文件。尝试的 28 天跨月范围也未被页面接受，因此不能用页面读数、截图或第三方报告满足 `SKU-000`。详细证据见 [Seller 搜索分析导出门复验](20260720_SKU_000_OZON_SELLER_ANALYTICS_EXPORT_GATE.md)。
- 私密 `.runtime/startup-intake` 已无覆盖地补入 `candidate-research.csv`；八份模板结构校验通过，严格 readiness 按设计返回 3，继续等待真实输入。

## 决策

1. 在账户负责人亲自接受 Ozon 条款并导出真实报告前，不确定三个候选，不发起供应商询价。
2. Ozon 公开页示例只用于验证字段结构，不作为 `demand_signal`、`competition_gap` 或利润输入。
3. 真实报告至少保留导出时间、筛选条件、观察窗口、原文件和 SHA-256；浏览器抄数只保留为 `requires_review`。
4. 获得报告后先排除儿童、服装尺码、化妆品、食品、医疗、电池/电器、易碎和高体积商品，再从轻小、非电、低认证候选中选择三项进入供货与三报价核验。
5. 即使 Ozon 给出“建议采购价”，正式 CM3 仍使用三家真实供应商报价、样品实测重量尺寸、实际物流/关税/平台费用与退货准备金重新计算。

## 账户负责人唯一人工动作

1. 在 `https://data.ozon.ru/app` 阅读 Ozon 要约和个人信息条款；只有本人同意时才勾选并继续。
2. 决定使用 Ozon Data 要约路径或购买 Ozon Premium 导出路径；在获准路径中选择俄罗斯/Ozon、最近 28 天，导出热门商品、搜索查询、缺失商品或售罄商品的可用报告。若改用 Seller API，必须先证明其官方原始响应与报告具有同等窗口、字段、身份和可复验强度。
3. 把原文件放入未跟踪的本地 Evidence 入库区，不在对话中粘贴个人信息或凭证。

完成这一步只解除需求数据访问阻塞，不代表候选、合规、采购、利润或上架获批。

## 复验来源

- Ozon 官方“在 Ozon 上卖什么”：<https://data.ozon.ru/>
- Ozon 官方真实分析入口：<https://data.ozon.ru/app>
- Ozon 官方分析工具说明：<https://docs.ozon.com/global/tr/analytics/analytics-and-metrics/analytics-tools/?country=TR>
- Ozon 官方搜索查询分析说明：<https://seller.ozon.ru/media/news/novaya-analitika-po-zaprosam-tovarov/>
