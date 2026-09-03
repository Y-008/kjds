# 2026-08-15 W2 封锁法医报告（只读证据）

doc_id: KJDS-EV-20260815-BLOCK-FORENSICS
采集方式：Chrome CDP 只读（Runtime.evaluate / Network 捕获 / 页面内同源 fetch 带 x-o3-company-id 头），零写操作。

## 1. 店铺与公司状态

- 当前 cookie `sc_company_id=2706897`（LINYAN）；UI 可切三司（BEIJI 2735620 / LINYAN 2706897 / TREAS 2315091）。
- 同法人：Zhaodong City star cloud Hui Internet sales Co., LTD；INN 91231282MAE08E0C2C。
- LINYAN 财务接口显示 4 份合同：39-81237/25(Actual) + 39-98600/25(Actual) + 39-98592/25(Stopped) + 39-301280/24(Actual)，收款 LianLianPay CNY。

## 2. 质量指标（仪表盘实读，2026-08-15）

| 指标 | BEIJI | LINYAN |
|---|---|---|
| realFBS 错误指数（14天） | 0%，无费用 | 0%，无费用 |
| 退货和取消（等待决定/取消申请） | 0 / 0 | 0 / 0 |
| 因错误无法配送商品 | 0 | 0 |
| 商品评分 | 4.86 | 4.57 |
| 价格指数不利占比 | 25% | 100% |
| 未认购 SKU | 3 / 5 | 2 / 7 |
| 余额 | 8,568.15 ₽ | 8,375.94 ₽ |
| 8 月应计 | 0 ₽ | 0 ₽ |
| 未读消息 / 新评价 / 新问题 | 15 / 125 / 2 | 24 / 212 / 6 |

## 3. 仓库与封锁

| 店 | 活跃 | 已封锁 | 全部 | 活跃仓备货 |
|---|---|---|---|---|
| BEIJI | 1（陆空，哈尔滨） | 2（uni：哈尔滨、入库仓：哈尔滨） | 3 | 5 天/每天 |
| LINYAN | 1（E邮宝，zhaodong） | 20 | 21 | 5 天/每天 |

- 页面横幅：「realFBS销售已封锁——在质量指标封锁持续期间，您将无法创建新仓库并为仓库创建方式」。
- BEIJI 封锁仓页面显示「uni：212 等待备货的订单」→ 经 `/api/posting-service/posting/count-by-warehouses`（company_id=2735620，2025-01-01 起，全部状态别名）实查：两封锁仓各状态 posting_count 全为 0；`/api/posting-service/seller-ui/fbs/posting/list` awaiting_packaging = 空。**结论：212 为陈旧页面缓存，无真实待备货积压。**
- BEIJI 取消单实查（2025-09/10）：1 单买家拒收（不影响评级）、1 单「Товар закончился на складе」卖家缺货取消（计入取消评级）→ 历史质量封锁的合理触发器。
- LINYAN 20 仓被封锁：同为质量指标封锁波及（历史取消/逾期），当前指标已清零。

## 4. 解封规则（官方中文帮助文档已读，global-help.ozon.com/zh/fulfillment）

- 跟踪指标：报告→质量监管→取消百分比/逾期发运（`/app/analytics/fulfillment-reports/complaints` 与 `/fbs-rfbs-errors`）+ 工作质量页 realFBS 选项卡。
- 封锁触发：逾期发货 ≥20% 或取消超限。
- 解封：改善指标后约 3 天自动解封；技术错误或异议走客服主题「销售和供应封锁 → 根据realFBS指标」附截图。
- 多次封锁累计达 14 天 → 需完成 Ozon Global 质量标准测试；永久封锁 → 测试通过。

## 5. Premium 与评价工具（只读确认）

- BEIJI `/api/premium/status`：is_premium=false；grace_period_available=true；grace_periods.PREMIUM.available=true → **BEIJI 有免费 Premium 试用窗口**（¥4,990/月价值，搜索提升10%+徽章+高级分析）。
- LINYAN grace 已过（2025-06-03）→ 不买。
- TREAS `/api/premium/status`：is_premium=false；grace_period_available=true；grace_periods.PREMIUM.available=true → 本店也有免费 Premium 窗口，但本轮 D2 仍冻结，不操作 TREAS。
- 「快速收集评价」`/app/reviews/promotions`：收集前 10 条评价（21 商品 ~36% 转化增长预测）+ 很久无评价（4 商品）工具存在，启用流程=选品→设目标数与单条出价→Ozon 选择性发积分。未点任何启用按钮。
- 「忠诚度机制」`/app/loyalty/sellerpoints`（星星商品 1₽+140天免息，佣金 1.5%，免费 30 天）→ 本轮冻结。

## 6. API 通路备忘（供后续只读侦察复用）

- 订单计数：`POST /api/posting-service/v2/fbs/posting/count/by-status-alias`（body 需 company_id，否则 PermissionDenied）
- 仓库计数：`POST /api/posting-service/posting/count-by-warehouses`（filter.company_id）
- 订单列表：`POST /api/posting-service/seller-ui/fbs/posting/list`
- 商品汇总：`POST /api/site/product/list/summary-count`（BEIJI：IN_SALE=15，TO_SUPPLY=5）
- 商品列表：`POST /api/v1/products/list-by-filter`
- 公司财务：`POST /api/v2/company/finance-info`
- Premium：`POST /api/premium/status`（body company_id + 头 x-o3-company-id 即可跨司）
## 7. 补充证据（2026-08-15 第二轮，只读）

- LINYAN 客服 messenger（`/app/messenger?group=support_v2`）实读 Ozon 官方历史线程：
  - №73712587（2025/12/10）、№72431099（2025/11/22）、№70074329（2025/10/17）：主题「质量检查/隐藏/恢复商品」——"我们已将在发运前取消的商品和最近几天没有成功发货的商品归档。请检查您的库存，并在准备好发运已接收订单时将商品重新上架。" → 官方自证：2025 Q4 三次质量归档，与当前 realFBS 封锁同源。
  - 2025/7 多条「隐藏不受欢迎商品」通知。
  - 上述线程均显示「已锁定」，回复 textarea disabled=true（实测）→ 工单必须新建，不能回复旧线程。
- 知识库 realFBS 分区（global-help.ozon.com/zh/fulfillment/rfbs）文章结构已枚举；内容 API=`/document-manager-api/global-help/api/v3/document/public/by-path?path=…&lang=zh`。
- 客服「创建请求」入口三层备选路径已写入 24j（路径 A 帮助中心文章底部 / B messenger 新建对话 / C 帮助中心搜索）。
- 结论更新：封锁根因从「历史取消单」强化为「Ozon 2025 Q4 三次质量归档 + 发运前取消记录」；当前指标 0% 达标 → 申诉成功概率高，优先执行 24j。

## 8. TREAS 付款时间表（2026-08-15 API 实查）

- `/api/site/seller-finance/drawers/payment`（x-o3-company-id=2315091）：activePaymentTariff=Default 生效；nearestPaymentDate=**2026-08-29**；delayInDays=14；countPerMonth=2；提前付款服务可用（commission 4.69%，默认不启用）。
- `/api/site/self-gateway/api/balances/current_month`（2315091）：月初=月末=12,621.01₽；8 月应计 0、已付 0、has_holds=false。
- 结论：DP-6 提现测试窗口 = 8/29 付款日；24o 已按此更新。

## 9. 官方封锁分级与申诉主题（2026-08-15 网络取源，官方课程镜像）

- 封锁四等级：首次=观察期未纠正→3 天自动解封；二次=首次后 7 天→3 天自动解封；**暂时=60 天内 4 次→最多 14 天，解封需完成 Ozon Global 质量标准测试**；永久=未通过测试，无法解封。
- 阈值：卖家过失取消 <10%、逾期发运 <20%（渠道错误 ≥1% 亦触发）。
- 计算口径：取消%=过去 14 天（不含当天/前一天）卖家取消货件÷创建货件总数；逾期%=过去一周。
- 官方申诉主题原文：「**封锁以及货件费用**」→「**根据RealFBS指标**」，要求附个人中心截图（可见货件编号与错误文字）。
- 本案评估：两店 2025 Q4 三次质量归档 → 当前封锁可能属「暂时」级 → 24j 工单文本已加「请告知封锁等级与测试链接」；24t 已写测试备料职责。
- 来源：chwang.com 镜像官方课程《因质量指标低而产生的封锁期限》(2025-06-15)、《如何计算质量指标》(2024-12-19)。
