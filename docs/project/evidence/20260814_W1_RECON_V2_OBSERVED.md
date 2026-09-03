# 2026-08-14 W1 只读侦查报告 v2：状态精查 + 毛利门重算

| 字段 | 值 |
|---|---|
| status | OBSERVED v2（只读，零写操作；取代 v1 的 DP-2 解释与 DP-1 结论） |
| 采集时间 | 2026-08-14（下午–晚间） |
| 来源 | Ozon Seller 后台（CDP 9224 副本 Chrome）+ 页面同源 API + 1688 公开展示价（w1_sourcing_1688_shortlist.json） |
| 关联 | 24a v2 决策包；本报告是其中每项数字的出处 |

## 一、本轮新发现（关键更正）

1. **「未认购的SKU 3 于 5」是买断率指标，不是订阅开关。** 点击仪表盘该小部件后跳转 `/app/analytics/redemptions`（已购买商品分析）。BEIJI：低 3 / 平均 2 / 高 0（近50单口径）；可见明细：Phone Stand 买断率 0%（类目均值 98%）、Folding Tourist Bed 49%。根因 Top3：配送服务无法取货 ×2、您已取消订单 ×2、对价格不满意 ×1。
2. **三店 Premium 订阅状态均为 NONE**（`/api/premium/summary/company/<cid>` 实测）。v1 的「恢复订阅 3/5、2/7」表述撤销，替换为 DP-2 v2 的「恢复可售」。
3. **商品真实状态分布（`visibility` API 实测）**：
   - BEIJI：销售中 15 / 准备销售 5 / 下架 0（历史归档 1000+）
   - LINYAN：销售中 32 / 准备销售 3 / 其余 9（草稿、待修改、下架类）
   - 准备销售=买家无法下单，共 8 个 SKU 需要处置（详见 24a DP-2 v2）。
4. **Premium 实测价格**：PREMIUM 首期 4,990₽（50% off，原价 9,990₽/月）；PLUS 24,990₽（首期 12,495₽）；PRO 24,990₽（佣金 2.5%→1.5%）；BEIJI 的 PREMIUM grace period 显示 available。
5. **TREAS 余额实测**：12,621.01₽，8 月应计 0（收款通道可读）。

## 二、毛利门重算（DP-1 v2 的依据）

公式：`毛利 = 售价₽×0.75×0.077 − 货代 − 采购 − 杂费 ≥ 售价₽×0.077×15%`
- 货代假设：深圳→俄专线小包 ¥17 首重 + ¥30–32/kg（来自上轮情报，待 3 家书面报价替换）
- 采购价：1688 公开展示价（仅候选线索，正式报价以 RFQ 书面确认为准）

| SKU | 商品 | 现价₽ | 原目标₽ | 净额¥(0.75) | 货代¥ | 采购¥ | 毛利¥ | 门¥ | v2 结论 |
|---|---|---|---|---|---|---|---|---|---|
| 2021922800 | 折叠床3in1 6.3kg | 7,301 | 4,665 | 269.4 | ≈187 | 69.43 | ≈13 | 53.9 | 否决 |
| 2216781923 | 电动提升机500kg | 16,036 | 11,193 | 646.5 | 150–300 | 250–450 | −54~246 | 129.3 | 暂缓待RFQ |
| 1958938002 | 激光水平仪 | 611 | 390 | 22.5 | ≈20 | 2.2–3.8 | ≈0 | 4.5 | 目标改 450–500₽ |
| 1991360967 | 马桶椅 | 2,490 | 1,899 | 109.7 | ≈52 | 33 或 145 | 24.7 或 −87 | 21.9 | 有条件下通过 |

## 三、T2 候选毛利门预判（DP-7 RFQ 优先级依据）

| SKU | 商品 | 绿价₽ | 净额¥ | 估算毛利¥ | 门¥ | 预判 |
|---|---|---|---|---|---|---|
| 2021933624 | 折叠床3in1（GREEN，销售中） | 现价12,325（已绿） | 711.8 | ≈+455 | 142.4 | **通过，Double-down 目标** |
| 2078074677 | Makita DHR182Z | 18,452 | 1,108.9 | 负（正品成本¥2,500+） | 213.1 | 绿价必亏；维持高价或归档 |
| 2078100418 | 电锯 | 2,062 | 123.8 | ≈+20 | 23.8 | 差一点，压采购价可过 |
| 1958225675 | 混水器 | 2,798 | 161.6 | ≈+97 | 32.3 | **通过** |
| 1953273803 | 保险箱 | 1,998 | 115.4 | 负（10kg 货代≈¥300） | 23.1 | 小包不可行，归档/大货再评 |
| 2033248519 | 背靠式扶手 | 4,437 | 256.2 | ≈+26 | 51.3 | 边缘，待报价 |
| TREAS 模块化沙发 | — | 13,249+ | 796+ | 大件小包不可行 | — | FBO 渠道再评估，冻结 |

## 四、API 通路 v2（复用清单）

- 商品列表+状态：`POST /api/v1/products/list-by-filter`，body `{company_id, visibility:'IN_SALE'|'TO_SUPPLY'|'REMOVED_FROM_SALE'|'ARCHIVED'|'ALL', limit:1000, offset:0}`；响应 `products[].item_id`（visibility 是状态过滤真参，v1 用的 filter 无效）
- 商品详情：`POST /api/v1/item/list`，body `{company_id, ids:[...]}`
- 价格指数：`POST /api/v1/pricing/item-price-index/v1/get-items-indexes-by-skus-with-url`，body `{company_id, skus:[...]}`（≤10/批）
- 余额：`GET /api/site/self-gateway/api/balances/current_month`
- Premium 价格：`GET /api/premium/prices`；摘要：`GET /api/premium/summary/company/{cid}`；状态：`POST /api/premium/status`
- 买断率：`POST /api/site/analytics-returns/redeemed_goods/reason50/sku`（{} 即可，返回根因分布）
- 必需头：x-o3-app-name:seller-ui、x-o3-language:zh-Hans、x-o3-company-id:<cid>、x-o3-page-type、credentials:include
- 未打通（403 body company ID）：`company/v1/get_subscription_info`、`site/item-stock-service/*`、`v2/company/finance-info`——需在 UI 页面完成对应查证（已列入待办）

## 五、W1 剩余待办

| 项 | 状态 |
|---|---|
| TREAS 主体/税务/绑定卡 UI 查证（DP-6 前置） | 待 UI 页面（下一轮） |
| 发货时间模板核实（先卖后采缓冲 ≥5 天） | W2 前置，待 UI 页面 |
| 1688/货代 RFQ 发出（24b 模板已备） | 待 DP-7 签字 |
| 39 消息 + 337 评价批量回复 | 待 DP-3 签字 |
| 官促报名 | W2 |
| 首单测试链路（订单→采购→货代→妥投→结算） | W2 起 |

## 六、红线声明

- 本报告全部为只读采集，未改价、未订阅、未回消息、未提现。
- 1688 价格为公开展示价，不可当正式报价；正式报价须 RFQ 书面确认 + 真人签字。
- AI 永不自动付款、调价、改库存；夜间只读+草稿。
- 敏感明细只落 .runtime（Git 忽略区）。
