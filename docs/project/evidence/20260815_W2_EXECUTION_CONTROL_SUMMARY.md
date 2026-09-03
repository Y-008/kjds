# 2026-08-15 W2 单页总控卡

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-CONTROL-20260815-001 |
| 状态 | D1_IN_PROGRESS（两店解封工单已发送） |
| 目的 | D1 进行中；用户已授权 D1 剩余写操作，恢复卖家会话后按顺序执行 |

## 当前快照

| 店 | 余额 | active FBS | delivered | cancelled | Premium grace |
|---|---:|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 8,568.15 ₽ | 0 | 301 | 74 | 可用 |
| LINYAN888 | 8,375.94 ₽ | 0 | 570 | 143 | 已过期 |
| Treasures of the road | 12,621.01 ₽ | 0 | 0 | 29 | 可用 |

8 月应计和已付均为 0。三店最近付款日均为 2026-08-29。仓库封锁：BEIJI 2、LINYAN 20、TREAS 8（另 created 1 / disabled 3）。

## 每日动作

| 日 | 动作 | 主要卡 | 门 |
|---|---|---|---|
| D1 | 签字已完成；两店工单已发送（LINYAN №90522913、BEIJI №90524416）；15 项归档、2 笔改价待执行 | 24j、24k、24l | 后续写操作待执行前复采 |
| D2 | 39 消息、337 评价、RFQ、BEIJI Premium | 24q、24r、24m | Premium 首期必须 0 ₽ |
| D3 | 检查自动解封、官促报名 | 24n、24y | 仅过毛利门 SKU |
| D4 | RFQ 跟催 | 24r | 48h 无回跟催 |
| D5 | 工单追问、TREAS 应计 | 24j、24o | TREAS 不强制提现 |
| D6 | 无真人动作 | 24s | DP-9 冻结 |
| D7 | 周五节点、Plan B | 24p、24t | unmatched=0；B1 首选 |

## Go/No-Go 入口

- D1：`docs/project/evidence/20260815_W2_D1_PRECHECK_GONOGO.md`
- D2：`docs/project/evidence/20260815_W2_D2_PRECHECK_GONOGO.md`
- D3-D7：`docs/project/evidence/20260815_W2_D3_D7_PRECHECK_GONOGO.md`

## 每日只读值班

- 运行 `scripts/run-w2-readonly-snapshot.ps1` 生成 `LATEST.json`。
- 运行 `scripts/compare-w2-ozon-snapshot.ps1` 对比 `BASELINE.json`。
- 仅当比对结果为 `NO_CHANGE` 时维持当前 Go/No-Go；出现余额、订单、仓库或 Premium 变化，先记录时间与字段，转真人复核，不自动放行。

## AI 边界

- D1 授权范围内可执行归档、改价、回复、RFQ、免费 Premium、官促；不执行提现、付费订阅、新建仓或上新。
- 不报名付费推广、不启用评价工具和忠诚度机制。
- 不读取或输出 `.env`、`Client-Id`、`Api-Key`、银行账号、PII。
- 不把历史余额升级为 `CASH_VERIFIED`。
- 不操作 TREAS，除非 08-29 后出现可提现金额且真人确认。

## 终止条件

任一店出现 active 订单、RFQ 导致负毛利、Premium 首期非 0 ₽ 或要求绑卡，立即停止对应动作并转周五节点。D7 未解封则进入 24t，B1 升级申诉优先，B4 新店默认否决。
