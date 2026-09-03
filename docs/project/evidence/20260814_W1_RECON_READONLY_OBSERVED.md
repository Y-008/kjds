# 2026-08-14 W1 只读侦查报告：三店 SKU 全量与价格指数分档

| 字段 | 值 |
|---|---|
| status | OBSERVED（只读采集，零写操作） |
| 采集时间 | 2026-08-14 |
| 来源 | Ozon Seller 后台（副本 Chrome CDP 9224，用户本人登录）+ 页面同源 API |
| 所属方案 | 24_7DAY_SPRINT_REVIVAL_PLAN.md（Active） |
| 原始数据 | D:\KJDS\.runtime\w1-3companies-full.json、w1-merged-3companies.json |
| 分档表 | D:\KJDS\.runtime\w1-gen-beiji-table.md、w1-gen-linyan-table.md、w1-gen-tierstats.json |

## 一、执行摘要

- 本次只读，未改价、未恢复订阅、未回任何消息，符合「写操作前必须 L2/L3 签字」红线。
- 核心结论：历史停店主因之一「价格指数不利」（BEIJI 92%、LINYAN 93% 商品处于不利区间）已被逐 SKU 量化；先修免费闸门（改价→订阅→评价/消息→官促），再开任何付费动作。
- 分档结果：T1 立即可调 4 个（降幅 ≤36%，绿价过毛利门）；T2 待 1688 报价 32 个；T3 冻结 8 个（绿价低于执行线或草稿无效）；观察 20 个。
- 所有改价动作已形成 L2 决策包 24a，待真人签字后执行。

## 二、三店当前快照（2026-08-14）

| 店 | CID | SKU 数 | 余额 | 未读消息 | 待回评价 | 未认购 SKU | 评分 |
|---|---|---|---|---|---|---|---|
| BEIJIXINGYOUXUAN | 2735620 | 20 | 8,568.15 ₽ | 15 | 125 | 3/5 | 4.92 |
| LINYAN888 | 2706897 | 44 | 8,376 ₽ | 24 | 212 | 2/7 | 4.57 |
| Treasures of the road | 2315091 | 77 | 12,621 ₽ | 0 | 0 | — | — |

## 三、价格指数全量统计（API 实测）

| 店 | SKU | GREEN | RED | YELLOW | 无指数 | 草稿(sku=0) |
|---|---|---|---|---|---|---|
| BEIJI | 20 | 1 | 12 | 0 | 7 | 0 |
| LINYAN | 44 | 0 | 28 | 1 | 11 | 4 |
| TREAS | 77 | 1 | 7 | 1 | 67 | 1 |

- BEIJI：RED 占 60%，仅 1 个 GREEN（2021933624 折叠床），无指数 7 个多为大件或冷门 SKU。
- LINYAN：RED 占 64%，0 个 GREEN，4 个草稿无效 SKU 待归档。
- TREAS：67/77 无指数（历史停运 19 个月，多数 SKU 已无索引数据），暂不投入，仅保留「收款+提现」验证。

## 四、分档建议（AI 建议，未执行）

分档规则：绿价 = 平台建议的「有利区间」价；竞对最低 = 前台抓取最低同款价。

| 档 | 定义 | BEIJI | LINYAN | TREAS | 动作 |
|---|---|---|---|---|---|
| T1 | 降幅 ≤36% 且绿价 ≥ 执行线 | 2 | 2 | 3 | 签字后直接改至绿价，7 天过毛利门复核 |
| T2 | 降幅 >36% 或需压本 | 7 | 25 | 4 | 先 1688 RFQ 过毛利门，再决定是否调价/下架 |
| T3 | 绿价 <15¥ 或草稿无效 | 3 | 5 | 1 | 冻结/归档，停止投入 |
| 观察 | 无指数 / YELLOW / 已有利 | 8 | 12 | 69 | 维持现价 1 节点，不动作 |

T1 明细（改价决策包见 24a）：

| 店 | SKU | 现价 RUB | 目标 RUB | 指数 | 商品 |
|---|---|---|---|---|---|
| BEIJI | 2021922800 | 7,301 | 4,665 | RED 1.22 | 折叠床 3in1 |
| BEIJI | 2216781923 | 16,036 | 11,193 | RED 1.22 | 便携电动提升机 500kg |
| LINYAN | 1958938002 | 611 | 390 | RED 1.37 | 激光水平仪 |
| LINYAN | 1991360967 | 2,490 | 1,899 | RED | 马桶椅 |

## 五、技术通路记录（供后续复用）

- 商品列表：POST /api/v1/products/list-by-filter，body {company_id, filter:'all', limit:1000, offset:0}
- 商品详情：POST /api/item/list，body {company_id, ids:[...]}
- 价格指数：POST /api/pricing/item-price-index/v1/get-items-indexes-by-skus-with-url，body {company_id, skus:[...]}（单批 ≤10）
- 余额：GET /api/site/self-gateway/api/balances/current_month
- 必需头：x-o3-app-name: seller-ui、x-o3-language: zh-Hans、x-o3-company-id:<CID>、x-o3-page-type、credentials:'include'
- 汇率锁定：营销价 1 CNY = 12.48 RUB；结算口径 1 CNY = 13 RUB（0.077），对账以结算为准。
- 会话载体：副本 Chrome profile D:\KJDS\.runtime\chrome-profile-copy，CDP 127.0.0.1:9224；页面状态 window.__MODULE_STATE__。

## 六、W1 剩余待办与前置依赖

| 项 | 前置 | 状态 |
|---|---|---|
| T1 改价 4 SKU | 真人签 24a DP-1 | 待签 |
| 恢复订阅 BEIJI 3 + LINYAN 2 | 真人签 24a DP-2 | 待签 |
| 39 条消息 + 337 条评价回复 | 真人批准回复模板（24c） | 待签 |
| 1688 RFQ（T2 优先池）+ 深圳货代询价 | 模板已备（24b），可直接发出 | 就绪 |
| Treasures 提现测试 12,621 ₽ | 真人签 24a DP-6（先查主体/税务/卡） | 待签 |
| Premium 订阅 4,990 ₽/月 | 真人签 24a DP-5（现金支出） | 待签 |
| 官促报名 | W2 上架完成后执行 | 排队 |

## 七、红线声明

- 本报告不含任何写操作证据；改价/订阅/回复/提现/订阅付费均以 24a 签字为唯一执行条件。
- AI 永不自动付款、调价、改库存；夜间只读 + 草稿。
- 敏感明细只落 .runtime（Git 忽略区），对外只引用聚合数字。
