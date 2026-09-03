# 2026-08-15 W2 三店风险与优先级决策矩阵

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-RISK-PRIORITY-20260815-001 |
| 状态 | READ_ONLY_ANALYSIS |
| 生成时间 | 2026-08-15T13:35:00+08:00 |
| 当前 HEAD | c744c7943e09b4890d07b0efc0ec1a031b408ba7 |
| 依据 | W2 封锁法医报告、W2 当前只读探测、20260814 财务全景与修正后应计账、提现与银行流水研究 |

## 1. 决策结论

本轮只读分析的最高优先店是 BEIJIXINGYOUXUAN，其次 LINYAN888，Treasures of the road 继续冻结。

- BEIJI：封锁范围小、当前指标 0%、有免费 Premium grace、历史经营最接近现在、账号卫生负担较低。先解封并清理，再作为第一个真实 SKU 复投对象。
- LINYAN：历史净额最大，但 20 个仓库被封锁，价格不利 100%，Premium 已过期，评价和未读消息积压最多。先解封和清积压，不作为首个上新对象。
- TREAS：余额最大但停运最久、无 active 订单、8/12 仓封锁，且当前余额极可能未达到 CNY 最低汇款门槛。本轮冻结，只在 2026-08-29 付款日做只读复核。

## 2. 三店优先级表

| 优先级 | 店 | 本轮动作 | 主要依据 |
|---|---|---|---|
| P0 | BEIJIXINGYOUXUAN | 解封工单、归档、账号卫生、免费 Premium | 封锁 2 仓，active 0，指标 0%，Premium grace 可用，价格不利 38% |
| P1 | LINYAN888 | 解封工单、两笔改价、消息/评价清理 | 封锁 20 仓，active 0，指标 0%，无 Premium，价格不利 100%，卫生积压最多 |
| P2 | Treasures of the road | 冻结，08-29 只读复核 | 无 active 订单，停运最久，8/12 仓封锁，余额可能未达汇款门槛 |

## 3. 修正后历史应计净额

早期 W2 运营总览引用的历史净额在 20260814 账本第九节被勘误，原因是合并 CSV 曾漏掉 3 行非订单应计。本矩阵采用修正值，旧值不再作为公司级净额口径。

| 店 | 修正净额 ₽ | 旧值 ₽ | 差额 ₽ | 说明 |
|---|---:|---:|---:|---|
| BEIJIXINGYOUXUAN | 227,743.63 | 242,303.35 | -14,559.72 | 2025-10 月净额由 +4,616.70 改为 -9,943.02 |
| LINYAN888 | 315,887.23 | 315,887.23 | 0 | 未受漏行影响 |
| Treasures of the road | 14,058.18 | 14,067.10 | -8.92 | 2024-11 广告 -8.92 补回 |
| 合计 | 557,689.04 | 572,257.68 | -14,568.64 | 已支付推算改为 528,123.94 ₽ |

修正源文件为 `D:\KJDS\.runtime\ozon_accruals_consolidated_corrected.csv`，SHA-256 `A02134794EA810C1A8BCDA7ABA02FB3457627157E7B9B475A74144759C933E3C`。

上述数字仍是历史应计口径，不是 `CASH_VERIFIED`。必须取得 LianLianPay 或银行到账原件、`order_id -> posting_number -> 平台应计/结算 -> payout -> 银行流水` 五段守恒且 `unmatched=0` 后，才能确认真实现金。

## 4. 分店风险判断

### BEIJIXINGYOUXUAN

- 有利：商品评分 4.86，当前余额 8,568.15 ₽，active FBS 0，8 月应计/已付 0，仅 2 个封锁仓，Premium grace 可用。
- 风险：价格不利 38%；页面旧缓存曾显示 212 等待备货订单，实际 API 为 0，执行前必须再刷新订单页。
- 建议：真人先发解封工单并归档，账号卫生先行；解封成功后选 1 到 3 个历史成交 SKU，不新建仓、不修改配送方式。

### LINYAN888

- 有利：历史净额最高，商品评分 4.57，当前余额 8,375.94 ₽。
- 风险：20 仓封锁，价格不利 100%，未读消息 24、待处理评价 212，Premium 已过期。
- 建议：D1 只执行两笔已过毛利门的改价，不发批量模板；解封工单明确要求告知封锁等级、累计次数和是否需 Ozon Global 质量标准测试。解封前不上新 realFBS 商品。

### Treasures of the road

- 有利：当前余额 12,621.01 ₽，`has_holds=false`，有 Premium grace 窗口。
- 风险：无 active 订单，delivered 0，停运约 19 个月，8/12 仓封锁；若合同币种为 CNY，当前 12,621 ₽ 远低于 6500 CNY 最低汇款门槛，因此不能提前主张提现。
- 建议：继续冻结，不报名 Premium、不新建仓、不上新。仅在 2026-08-29 付款日重采付款日历、余额和 `has_holds`，同时请真人确认合同币种、收款人名称与 LianLianPay 绑定状态。

## 5. D1-D7 优先级对应

| 日 | 店优先级 | 动作 |
|---|---|---|
| D1 | BEIJI/LINYAN | 两店解封工单、15 项归档、LINYAN 两笔改价 |
| D2 | BEIJI/LINYAN | BEIJI 免费 Premium；两店消息/评价/问题清理；RFQ |
| D3 | BEIJI/LINYAN | 检查自动解封窗口，不自动补仓 |
| D4 | BEIJI/LINYAN | RFQ 48h 无回跟催 |
| D5 | BEIJI/LINYAN/TREAS | 工单追问；TREAS 仅只读查看 |
| D6 | 全部 | 无真人写操作，AI 只读值班 |
| D7 | 全部 | 周五节点，未解封转 Plan B；TREAS 仍冻结 |

## 6. 不越权边界

- 不代发工单、不改价、不归档、不回复、不提现、不报名付费活动。
- 不启用评价工具、忠诚度机制、付费 Premium 或付费推广。
- 不新建仓、不修改配送方式、不解封前上新 realFBS 商品。
- 不读取或输出 `.env`、`Client-Id`、`Api-Key`、银行账号、PII。
- 不把历史应计净额、当前余额或研究笔记升级为 `CASH_VERIFIED`。

## 7. 下一步只读动作

1. 每天运行 `scripts/run-w2-readonly-snapshot.ps1` 生成 LATEST。
2. 运行 `scripts/compare-w2-ozon-snapshot.ps1`，仅当 `NO_CHANGE` 时维持当前 D1 门。
3. 重点监测三店 `active FBS`、余额、封锁仓数、Premium grace、商品 `in_sale/to_supply`。
4. 2026-08-29 只读重采 TREAS 付款日历、余额和 `has_holds`，不得提前执行提现。