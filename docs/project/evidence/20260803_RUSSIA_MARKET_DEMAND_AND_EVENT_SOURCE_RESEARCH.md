# 俄罗斯市场需求与热点事件来源研究 Evidence

| 元数据 | 值 |
|---|---|
| evidence_id | KJDS-EV-RU-MARKET-RADAR-20260803 |
| observed_at | 2026-08-03 |
| status | Reviewed sources and two current public observations; connectors not claimed live |
| owner | Russia Market Intelligence |

## 来源能力结论

俄罗斯需求不能只看 Ozon 销量，也不能只抓社媒热词。可执行组合为：Ozon/Wildberries/Yandex Market 自有或获授权店铺数据回答“站内曝光、搜索、加购、订单和价格”；Yandex Wordstat 回答“关键词在俄罗斯各地区和时间上的搜索需求”；Telegram/VK 回答“公开讨论、传播与创作者变化”；俄罗斯央行及平台官方发布回答“成本、消费环境、规则和技术变化”。

Yandex Wordstat 官方 API 提供 Top、Dynamics、RegionsDistribution 和 RegionsTree。`GetTop` 可按关键词、地区与设备返回最近 30 天热门及相关查询，单次最多 2,000 个短语。这个 2,000 是来源上限，系统必须记录为 source cap，不能把它改写成全互联网完整集合。

- https://aistudio.yandex.ru/docs/en/search-api/concepts/wordstat.html
- https://aistudio.yandex.ru/docs/en/search-api/operations/wordstat-gettop.html

Wildberries 官方 Analytics API 覆盖销售漏斗、搜索查询、位置、曝光、商品卡访问、加购、订单、库存和 CSV 报告；搜索词接口受订阅与 30/100 条来源上限影响，分页接口必须走到结束并保留来源限制。

- https://dev.wildberries.ru/openapi/analytics
- https://dev.wildberries.ru/news/297

Ozon 与 Yandex Market 继续走官方 Seller/Partner API，只有绑定商家账号后的返回才能成为自有店铺经营输入。

- https://docs.ozon.ru/api/seller/
- https://yandex.ru/dev/market/partner-api/doc/ru/

Telegram 官方 API 当前提供公共频道搜索、历史、回复、推荐、公开转发与管理员统计；部分能力只允许用户身份、管理员或可能付费，采集器必须把权限和来源 cap 带入覆盖率，而不是静默丢页。VK 采用同样的官方方法级 scope 策略。

- https://core.telegram.org/methods
- https://core.telegram.org/api/stats
- https://core.telegram.org/api/recommend
- https://dev.vk.com/ru/method/wall.get
- https://dev.vk.com/ru/method/wall.getComments
- https://dev.vk.com/ru/method/stats.get

平台变更来自官方发布页，不用二手转载替代规则真源：

- https://ir.ozon.com/news/
- https://dev.wildberries.ru/news
- https://yandex.ru/company/news/

## 当前公共观察

俄罗斯央行在 2026-07-24 把关键利率下调 25 个基点至 14.00%；同一公告记载 2026-07-20 年通胀 5.9%，企业对未来需求和产出的预期显著下降。该事件影响融资、库存和消费者预算风险，但不证明任何具体 SKU 的需求变强或变弱，也不能替代实际换汇汇率。

- https://www.cbr.ru/eng/press/keypr/
- https://www.cbr.ru/hd_base/infl/

Yandex 2026 Q1 官方财报新闻称，Market 的 adjusted EBITDA/GTV 利润率同比改善 3.2 个百分点，来源将原因归于更有效的营销发展模式与成本下降。这是平台经营环境信号，不是 KJDS、卖家或商品利润事实。

- https://yandex.ru/company/news/28-04-2026

## 超越单平台抓取

1. 每个种子词扩展俄语词形、同义词、品类词、问题词、场景词和品牌词，分别保存查询来源与版本。
2. 对每个来源执行完整分页、历史回补和 checkpoint，输出 source total、accepted、quarantined、failed pages 和 native cap。
3. 将搜索量、站内漏斗、价格/评价/库存变化、社媒传播和宏观事件分开，不用一个热度分数掩盖原始维度。
4. 热点需跨源印证；单条帖子可进入观察池，但不能直接触发采购、广告、发布或库存动作。
5. 事件保留 first seen、effective、last seen、expiry/review、实体和地区，形成时序 Graph，并与 SKU、类目、内容 campaign、物流和利润 owner 通过引用连接。
6. 来源中断进入官方文档、源码、Issue、Release、Fork 与替代 Adapter 的问题解决 Loop；部分结果继续保存但标为 partial。

## UNKNOWN

- Ozon Analytics 的真实账号 scope、Premium 历史深度和请求上限尚未验证。
- Wildberries 商家账号、Jam 订阅与 Analytics Token 尚未提供。
- Yandex Search API service account、角色、API key 和预算尚未提供。
- Telegram/VK 专用身份、种子频道/社群和真实覆盖率尚未建立。
- 当前没有足够站内搜索、加购、订单和利润 Evidence 排名真实 SKU 机会。
