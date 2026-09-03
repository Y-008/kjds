# 2026-08-15 W2 三店真人执行总包 v2

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-MASTER-EXECUTION-20260815-002 |
| 状态 | D1_IN_PROGRESS（两店解封工单已发送） |
| 当前 HEAD | c744c7943e09b4890d07b0efc0ec1a031b408ba7 |
| 快照状态 | LINYAN `to_supply` 6→7 CHANGED；其余关键指标无变化 |
| CDP 状态 | 9224 已恢复，但 Ozon 为登录页；必须由真人恢复登录态后再复采 |
| AI 权限 | D1 剩余写操作已获用户授权；归档/改价/回复/RFQ/Premium/官促待会话恢复后执行 |

## 1. 当前三店事实

| 店 | 余额 | active FBS | 8 月应计/已付 | 封锁仓 | Premium grace | in_sale | to_supply | 价格不利 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 8,568.15 ₽ | 0 | 0 / 0 | 2 | 可用 | 14 | 5 | 38% |
| LINYAN888 | 8,375.94 ₽ | 0 | 0 / 0 | 20 | 已过期 | 27 | 7 | 100% |
| Treasures of the road | 12,621.01 ₽ | 0 | 0 / 0 | 8 | 可用 | 64 | 1 | 71% |

三店合计平台余额为 `29,565.10 ₽`，不是旧执行卡中的 `29,565.16 ₽`。

## 2. D1-D7 执行顺序

| 日 | 动作 | 主要执行卡 | 对应 W2 分析 |
|---|---|---|---|
| D1 | 签字已完成；两店解封工单已发送；15 项归档、LINYAN 两笔改价待执行 | 24j、24k、24l | `20260815_W2_D1_HUMAN_EXECUTION_CHECKLIST.md` |
| D2 | BEIJI 免费 Premium；39 消息、337 评价、14 问题；RFQ | 24m、24q、24r | `20260815_W2_D2_HUMAN_EXECUTION_CHECKLIST.md` |
| D3 | 检查自动解封，官促报名 | 24n、24y | `20260815_W2_D3_D7_MONITORING_CHECKLIST.md` |
| D4 | RFQ 48h 跟催 | 24r | 同上 |
| D5 | 工单追问，TREAS 只读观察 | 24j、24o | 同上 |
| D6 | 无真人写操作，AI 只读值班 | 24s | 同上 |
| D7 | 周五节点，未解封转 Plan B | 24p、24t | `20260815_W2_D3_D7_PRECHECK_GONOGO.md` |

## 3. 最高优先级结论

- BEIJI 为 `P0`：封锁仓少、指标 0%、Premium grace 可用、评分 4.86。
- LINYAN 为 `P1`：历史净额最高，但 20 仓封锁、价格不利 100%、Premium 已过期。
- TREAS 为 `P2`：继续冻结，只在 2026-08-29 付款日只读重采。

复投候选依据：

- [20260815_W2_HISTORICAL_SKU_RELIST_CANDIDATES.md](20260815_W2_HISTORICAL_SKU_RELIST_CANDIDATES.md)
- [20260815_W2_WAREHOUSE_RECOVERY_MATRIX.md](20260815_W2_WAREHOUSE_RECOVERY_MATRIX.md)
- [20260815_W2_STORE_RISK_AND_PRIORITY_MATRIX.md](20260815_W2_STORE_RISK_AND_PRIORITY_MATRIX.md)

## 4. 关键校正

- 历史应计净额：BEIJI `227,743.63 ₽`、LINYAN `315,887.23 ₽`、TREAS `14,058.18 ₽`、合计 `557,689.04 ₽`。
- BEIJI 商品评分为 `4.86`，不使用 `4.92`。
- 24 系列增量校正见 [20260815_W2_24_SERIES_DELTA_ADDENDUM.md](20260815_W2_24_SERIES_DELTA_ADDENDUM.md)。

## 5. Go/No-Go 总门

| 项 | 当前状态 |
|---|---|
| 真人签字 W2 总包 | 已签，D1 已进入执行 |
| 执行前 CDP 复采 | 未登录，NO-GO |
| 三店 active FBS | 0，GO |
| 余额、应计、已付 | 当前稳定，GO |
| LINYAN `to_supply` 漂移 | 已记录，HOLD |
| AI 代执行店铺写操作 | D1 授权范围内可继续；提现、付费订阅、新仓与上新仍禁止 |

## 5.1 D1 实际执行进度

| 店 | 工单号 | 状态 |
|---|---|---|
| LINYAN888 | №90522913 | 处理中，等待操作人员 |
| BEIJIXINGYOUXUAN | №90524416 | 处理中，等待操作人员 |

## 6. AI 边界

- D1 授权范围内可执行归档、改价、回复、RFQ、免费 Premium、官促；不执行提现、付费订阅、新建仓或上新。
- 不新建仓、不修改配送方式、不解封前上新 realFBS 商品。
- 不启用付费 Premium、评价工具、忠诚度机制或付费推广。
- 不读取或输出 `.env`、`Client-Id`、`Api-Key`、银行账号、PII。
- 不把历史应计净额、当前余额或研究笔记升级为 `CASH_VERIFIED`。

## 7. 真人签字栏

| 字段 | 填写 |
|---|---|
| 签字人 | |
| 角色 | |
| 签字时间 | |
| 执行结论 | APPROVE / REJECT / HOLD |
| 授权范围 | D1 / D1-D2 / D1-D7 |
| 复核说明 | |

- [ ] 我已阅读总包、D1 Go/No-Go、风险优先级矩阵和 24 系列校正附录。
- [ ] 我确认执行前会恢复卖家页会话并重新运行只读快照与差异比对。
- [ ] 我确认 AI 不代执行任何店铺写操作。