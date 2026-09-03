# 2026-08-15 W2 当前店铺只读探测

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-CURRENTNESS-20260815-001 |
| 状态 | READ_ONLY_OBSERVED |
| 方式 | 本地 Chrome CDP 9224 页面内同源 fetch 与仪表盘只读提取，零写操作 |

## 三店当前余额

| 店 | 月初余额 | 月末余额 | 8 月应计 | 8 月已付 |
|---|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 8,568.15 ₽ | 8,568.15 ₽ | 0 | 0 |
| LINYAN888 | 8,375.94 ₽ | 8,375.94 ₽ | 0 | 0 |
| Treasures of the road | 12,621.01 ₽ | 12,621.01 ₽ | 0 | 0 |

## 三店仪表盘计数

| 店 | 未读消息 | 新评价 | 新问题 | 商品评分 | 未认购 SKU | 价格不利 |
|---|---:|---:|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 15 | 125 | 2 | 4.86 | 3/5 | 38% |
| LINYAN888 | 24 | 212 | 6 | 4.57 | 2/7 | 100% |
| Treasures of the road | 0 | 0 | 6 | 未提供 | 未提供 | 71% |

BEIJI 价格不利 38% 为 `2026-08-15T05:20:20Z` 仪表盘实读；其余计数沿用当前只读采样。

## 商品状态

| 店 | in_sale | to_supply |
|---|---:|---:|
| BEIJIXINGYOUXUAN | 14 | 5 |
| LINYAN888 | 27 | 7 |
| Treasures of the road | 64 | 1 |

说明：数值来自 `/api/site/product/list/summary-count` 的 `visibilities` 计数，键 `15` 对应在售、键 `14` 对应待补货；仅作商品池监控，不作为归档名单。监测到 LINYAN `to_supply` 由 6 变为 7（`2026-08-15T05:34:06Z`），仅商品状态变化，非店铺写操作。

## FBS 订单计数

统计区间为 2025-01-01 至 2026-08-15，按状态别名独立读取。

| 店 | awaiting_packaging | awaiting_deliver | delivering | delivered | cancelled |
|---|---:|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 0 | 0 | 0 | 301 | 74 |
| LINYAN888 | 0 | 0 | 0 | 570 | 143 |
| Treasures of the road | 0 | 0 | 0 | 0 | 29 |

当前 active 订单为 0。历史 delivered/cancelled 仅用于经营参考，不作为当前 cash-verified 证据。

## Premium

| 店 | is_premium | grace_period_available | PREMIUM.available |
|---|---:|---:|---:|
| BEIJIXINGYOUXUAN | false | true | true |
| LINYAN888 | false | false | false |
| Treasures of the road | false | true | true |

BEIJI 与 TREAS 均有免费 PREMIUM grace 窗口，LINYAN 已过期。

## 仓库封锁快照

`2026-08-15T05:21:42Z` 复采样，接口 `/api/posting-service/posting/count-by-warehouses`（`limit=1000`），仅读取仓库状态与 posting_count。

| 店 | 仓库总数 | blocked | created | disabled |
|---|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 2 | 2 | 0 | 0 |
| LINYAN888 | 20 | 20 | 0 | 0 |
| Treasures of the road | 12 | 8 | 1 | 3 |

说明：该接口当前对 BEIJI 返回 2 个 blocked 仓，未返回前端所称的 1 个活跃仓；对 LINYAN 返回 20 个 blocked 仓。TREAS 的 8 个 blocked 仓与 3 个 disabled 仓仅作状态记录，本轮不操作。

## 合同与收款

三家公司使用同一 INN，当前合同均为 CNY 结算，收款方式为 LianLianPay。四份合同中三份 Actual、一份 Stopped。

## 付款日历

`2026-08-15` 只读读取 `/api/site/seller-finance/drawers/payment`，三店付款参数一致。

| 店 | activePaymentTariff | 最近付款日 | delayInDays | countPerMonth | 提前付款服务 | 提前付款费率 |
|---|---:|---|---:|---:|---|---:|
| BEIJIXINGYOUXUAN | Default | 2026-08-29 | 14 | 2 | 未启用 | 4.69% |
| LINYAN888 | Default | 2026-08-29 | 14 | 2 | 未启用 | 4.69% |
| Treasures of the road | Default | 2026-08-29 | 14 | 2 | 未启用 | 4.69% |

三店 8 月应计和已付均为 0，因此 2026-08-29 当日预计无可付金额；需付款日重采确认，不能据此提前主张提现。

## 结论

三店 8 月应计和已付仍为 0，余额无变化，active FBS 订单为 0。BEIJI 与 TREAS 免费 Premium 窗口仍可用。未执行任何店铺写操作、付款、调价、改库存或工单提交。


## 复采状态

- 本文件生成后曾再次尝试只读快照，2026-08-15T13:37:00+08:00 左右两次均因 127.0.0.1:9224 连接被拒绝而失败。
- 失败发生在本地 CDP 会话，不是 Ozon 店铺写操作；BASELINE 与 LATEST 未被改变。
- 当前权威 LATEST 仍为 2026-08-15T05:34:06Z 采样，其中 LINYAN `to_supply` 为 7。
- 2026-08-15T14:45:47+08:00 当前 CDP 9224 不可用；两店解封工单已通过 SCRM 发出（LINYAN №90522913、BEIJI №90524416），未生成新的可信店铺快照。
- 2026-08-15T13:52:00+08:00 再次探测 127.0.0.1:9224，连接被拒绝；未生成新快照，BASELINE/LATEST 未改变。
- 执行前必须由真人恢复 Ozon 卖家登录态，并确认页面 URL 不再位于 signin；AI 不代登录。
- CDP 未登录前，不得把后续本地推理或旧快照当作新的店铺实时事实。