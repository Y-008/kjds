# Ozon 提现与银行流水对账研究笔记（2026-08-14）

> 状态：`RESEARCH / NON_FACT`。本文件是公开资料学习笔记，不是已签署的真实事实、报价、结算或银行原件。
> 真实证据只接受：原始文件 + SHA-256 + 时间 + Owner + 独立复核。银行/收款到账原件必须真人提供，系统不得补数。
> 与 [20260814_OZON_SELLER_API_RECON_FIELDS_RESEARCH.md](20260814_OZON_SELLER_API_RECON_FIELDS_RESEARCH.md) 配套，作为 FIN-001 现金闭环的证据层输入。

## 一、结论摘要

1. **提现规则有官方口径可确认**：跨境卖家按合同币种结算（USD / EUR / CNY / RUB），每月两批汇款，最低汇款门槛因币种不同（1000 USD / 6500 CNY / 60000 RUB；另有 EUR 口径见 §二）。
2. **平台侧“应计”和“付款”是两件事**：`财务 → 应计` 记录订单送达后按天累计的应计（含佣金、退款、赔偿），`财务 → 付款` 记录“平台已加算/即将加算给你的钱”。对账必须从应计 → 付款 → 收款方银行三条链路对清，不能只对一项。
3. **银行到账原件不可由 Seller API 替代**：Seller API 只覆盖平台侧订单、应计、结算报告；款项离开平台后进入支付系统（如 LianLian Pay）或银行，须由真人从收款方/银行导出流水和 reconciliation key。
4. **对账键固定**：`order_id → posting_number → 平台应计/结算记录 → 付款（payout）记录 → 收款方银行流水备注`，并要求 `unmatched=0` 才能升级为 `CASH_VERIFIED`。
5. **第三方“5000 ₽ 最低提现 / 1.5% 手续费 / 3–5 工作日到账”与官方口径不一致**，只能标为“支付服务商个性化费率 / 待核查”，不能当已签事实。

## 二、官方口径（可确认，来源见 §五）

### 2.1 结算币种与汇率

- 买家以卢布支付，Ozon 按“汇至商家当天的俄罗斯联邦央行官方汇率”兑换成商家的相互结算货币（USD 或 EUR）。
- 卖家结算币种在个人中心 `账户信息` 页指定。

### 2.2 汇款周期（每月两次）

- 第一批付款：覆盖 16 日之前完成的交易，Ozon 在 25 日之前汇款。
- 第二批付款：覆盖当月 16 日起至当月最后一日完成的交易，Ozon 在次月 16 日之前汇款。

### 2.3 最低汇款门槛（按合同币种）

- `1000 USD`（合同币种为美元）
- `6500 CNY`（合同币种为人民币）
- `60000 RUB`（合同币种为卢布）
- 另有一条 EUR 口径（`1000 EUR`）出现在“财务与会计”页的转述中，见 §五-2；建议以合同原文复核 EUR 是否等同 1000 门槛。

若当前付款期销售金额未达门槛，则累计至达到门槛后的最近付款日再汇款。

### 2.4 平台可扣除/预留款项

- 因取消订单或审核通过的买家索赔应退还给买家的款项。
- 未决索赔下预留的金额。
- 应付给 Ozon 的违约金和损失赔偿金。
- 买家退货时支付的运费（当纠纷处理结果支持买家时）。

### 2.5 付款状态

- `正在生成`：付款账单已就绪，但银行尚未确认或已拒绝。
- `等待付款`：账单已加入付款时间表，将在计划日期转款。
- `已付款`：已转款；若长时间不到账，与收款银行联系。

### 2.6 账户信息变更约束

- 收款人姓名必须与 Ozon 注册公司的法定名称一致，否则驳回，信息有误时款项退还。
- 银行信息用英文或俄文填写；RUB 币种字段用西里尔文，非 RUB 币种字段用拉丁文。
- 变更走支持单 `财务 → 更改详细信息`，或发 `marketplace.crossborder@ozon.ru`，并附完整 Excel 信息页。

### 2.7 跨境支付方式（大陆 / 香港卖家）

- 自（官方帮助页所述）3 月 15 日起，停止向大陆和香港卖家通过银行转账付款，改用支付系统（如 LianLian Pay）。
- LianLian Pay 仅适用于选择 CNY 或 USD 作为支付货币的大陆/香港卖家；若为 RUB，可联系客服更换。
- LianLian Pay 基本费率为“个性化”，需向分配的个人管理员确认，官方未给出统一百分比（第三方传的 1.5% 不属于官方统一口径）。

## 三、对账数据源映射（平台侧）

> 目标是 `Order → Settlement → Bank → Actual Cash CM3` 金额守恒，`未解释差异 = 0`。

| 环节 | 个人中心入口 | 可用报表 / API | 说明 |
| --- | --- | --- | --- |
| 订单事实 | `订单` 板块 | `POST /v1/report/postings/create` → `POST /v1/report/info` | 订单、posting_number、履约状态 |
| 平台应计 | `财务 → 应计` | 应计相关接口（见 §四） | 订单送达后按天累计，含佣金、退款、赔偿 |
| 付款 / 提现 | `财务 → 付款` | 付款列表（个人中心） | “已加算”与“即将加算”款项 |
| 结算文件 | `财务 → 文件` | 销售报告、相互结算报告、赔偿金报告、完工单、对账单 | 每月 5 日前生成上月文件；季度对账单在次月 15 日前生成 |
| 收款到账 | 收款方支付系统 / 银行 | 无 Seller API，须真人导出 | 银行流水 + 备注中的 reconciliation key |

### 3.1 结算文件清单（官方帮助页口径）

`财务 → 文件` 下可取得：

- 附加服务通用传输文件（销售佣金 / 服务费）
- 销售报告、销售报告详解
- 报告期由 Ozon 完成的服务报告
- 对账单（季度相互结算对账单，发布后 15 个工作日内接收或拒收，逾期视为接受）
- 分析报告（相互结算报告、服务金额和销售支出报告）
- 赔偿金和其它应计项目
- FBS 差异报告

### 3.2 关键风险

- 对账单是季度生成、且有 15 个工作日“默认接受”窗口：错过拒收窗口即丧失争议权，现金闭环应在窗口内完成差异核对。
- “应计”是权责口径（accrual），不是到账口径；“已付款”状态仅表示平台已转款，最终以收款方银行流水为准。

## 四、Seller API 财务接口口径（需以官方实时文档复核）

本笔记把公开 GitHub 镜像中可见的财务接口与早期研究中的应计接口并列，并明确分歧，避免把镜像快照当当前生产口径。

### 4.1 RU Seller API（`docs.ozon.ru/api/seller`）公开镜像可见

- `/v2/finance/realization`：月度销售报告（含退换货）
- `/v1/finance/realization/posting`：按订单销售报告
- `/v1/finance/realization/by-day`：按日销售报告
- `/v3/finance/transaction/list`：交易明细（官方镜像描述为“Returns detailed information on all accruals”，单次最长 1 个月）
- `/v3/finance/transaction/totals`：交易汇总
- `/v1/finance/cash-flow-statement/list`：现金流报表
- `/v1/finance/mutual-settlement`：相互结算报告
- `/v1/finance/compensation` / `/v1/finance/decompensation`：赔偿 / 冲销报告
- `/v1/finance/document-b2b-sales`（含 `/json`）：B2B 销售文档
- `/v1/finance/products/buyout`：平台买断商品报告

### 4.2 早期研究提出的应计接口（待实时官方核实）

早期研究笔记提出优先使用：

- `POST /v1/finance/accrual/postings`
- `POST /v1/finance/accrual/by-day`
- `POST /v1/finance/accrual/types`

本笔记未能在 RU Seller API 公开镜像中复现这些接口，也未能在 `docs.ozon.ru/global` 直连（返回 403）。**结论：这些应计接口的权威性、参数与返回结构必须在可访问的官方 OpenAPI/文档上二次确认后才能进入生产口径。**

### 4.3 关于 `v3/finance/transaction/list|totals` 是否停用

- 早期研究称其“2026-07-06 已标停用，不能当生产口径”。
- 本次可见的公开镜像（快照）仍将其列为现行接口，且无该条停用记录。
- **结论：存在快照时间差，不能据此断言停用或不停用。** 落地前必须用当前登录态在官方文档/个人中心确认接口当前状态，再选“应计接口”还是“transaction v3”作为平台应计源。

## 五、来源与可信度分层

### 官方口径（转述 / 镜像，需原文复核）

1. Ozon 官方帮助页《财务与会计方面》中文转述（出海网，更新 2024-12-06）：
   https://www.chwang.com/guide/485564690553
2. Ozon 官方帮助页《相互结算》中文转述（出海网，更新 2024-12-06）：
   https://www.chwang.com/guide/485564690497
3. Ozon Seller API 公开 GitHub 镜像 `DragonSigh/ozon-seller-api-docs`（`finance.md`、`getting-financial-reports.md`、`creating-and-getting-reports.md`、`news.md`）：
   https://github.com/DragonSigh/ozon-seller-api-docs

### 第三方交叉参考（可作旁证，不作事实）

4. 店小秘 ERP《Ozon 多少钱可以提现》（2026-07-13），与官方口径一致：
   https://www.dianxiaomi.cn/blog/article/580
5. AMZ123《Ozon 卖家怎么提款》（2025-05-28）出现“最低 5000 卢布 / 1.5% 手续费 / 3–5 工作日”：与官方“1000 USD / 6500 CNY / 60000 RUB”门槛冲突，判定为支付服务商个性化口径或错误，不可采用：
   https://www.amz123.com/ask/MnHZjj6A

### 未能直连的官方源

- `https://docs.ozon.ru/global/zh/accounting/`：403
- `https://docs.ozon.by/global/en/accounting/finance-management/`：403 / 超时

## 六、与 TRUTH-SKU-001 的关系

- `TRUTH-SKU-001` 仍为 `AWAITING_SIGNATURE`，不是 `CASH_VERIFIED`。
- 触发现金闭环所需的六项真实原件中，至少需要补充“收款方/银行流水 + reconciliation key + 实际到账金额 + 到账时间”，并完成 `order → posting → 平台应计/结算 → 付款 → 银行` 五段金额守恒、`unmatched=0`、独立复核通过。
- 未取得真实银行流水前，任何历史净额、余额、API 研究笔记均不得升级为 Cash 证据。
- 当前三店（BEIJI / LINYAN / TREAS）历史 8 月 `accrued=0`、`paid=0`，与停运事实一致，不能作为现金闭环样例。

## 七、下一步

1. 由真人提供收款方支付系统（LianLian Pay 等）/ 银行导出的流水原件，确认合同结算币种与最低门槛属于哪一档（USD / CNY / RUB / EUR）。
2. 用当前登录态在官方文档或个人中心复核 §四接口的现行状态，确定平台应计源的唯一生产口径。
3. 按 FIN-001 跑通 1 个真实 SKU 的五段对账，`unmatched=0` 后再谈 1→3 SKU 复制。
