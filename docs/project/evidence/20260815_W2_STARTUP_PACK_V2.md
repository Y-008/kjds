# 2026-08-15 W2 启动包 v2（权威签字入口）

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-STARTUP-V2-20260815-001 |
| 状态 | 待真人签字；未签字 = 零执行 |
| 取代 | 24i W2 启动包 v1 的旧事实与旧工单表述；不覆盖或修改 24i 原文件 |
| 依据 | W2 总控卡、D1-D7 授权门、封锁法医报告、最新只读快照 |

## 一、当前事实

| 店 | 余额 | active FBS | realFBS 14 天错误指数 | 封锁仓 | 最后活跃 |
|---|---:|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 8,568.15 ₽ | 0 | 0% | 2 | 约 2025-10 |
| LINYAN888 | 8,375.94 ₽ | 0 | 0% | 20 | 约 2025-12 |
| Treasures of the road | 12,621.01 ₽ | 0 | 未提供 | 8/12（另 disabled 3） | 约 2024-12 |

三店 8 月应计和已付均为 0。TREAS 付款日为 2026-08-29。

## 二、与 24i 的关键纠正

1. 不使用“停运超过一年”。BEIJI 约 9.5 个月，LINYAN 约 7.5 个月。
2. BEIJI 质量归档通知对应 2025-10、2025-11、2025-12。
3. 工单使用 `20260815_W2_UNBLOCK_SUPPORT_TICKET_V2.md`，不使用 24i 内旧模板。
4. BEIJI 当前仪表盘评分为 4.86，不是 4.92。
5. LINYAN 精确余额为 8,375.94 ₽，不使用四舍五入 8,376 ₽。
6. TREAS 也有免费 Premium grace，但本轮仍冻结。

## 三、执行顺序

| 日 | 动作 | 入口 |
|---|---|---|
| D1 | 签字、两店解封工单、15 项归档、2 笔改价 | W2_D1_PRECHECK_GONOGO.md |
| D2 | 39 消息、337 评价、RFQ、BEIJI Premium | W2_D2_PRECHECK_GONOGO.md |
| D3 | 检查自动解封、官促报名 | W2_D3_D7_PRECHECK_GONOGO.md |
| D4 | RFQ 跟催 | W2_D3_D7_PRECHECK_GONOGO.md |
| D5 | 工单追问、TREAS 应计 | W2_D3_D7_PRECHECK_GONOGO.md |
| D6 | 无真人动作 | W2_D3_D7_PRECHECK_GONOGO.md |
| D7 | 周五节点、Plan B | W2_D3_D7_PRECHECK_GONOGO.md |

## 四、Go/No-Go

- 未签字：所有店铺写操作 NO-GO。
- active 订单非 0：停止对应动作，转周五节点。
- Premium 首期非 0 ₽ 或要求绑卡：停止。
- RFQ 导致负毛利：停止该 SKU 改价或报名。
- TREAS 08-29 前不强制提现。

## 五、AI 边界

- AI 不代发工单、不代回复、不代改价、不代归档、不代提现。
- AI 不读取或输出敏感凭证、银行账号或 PII。
- AI 只运行只读快照、回填证据、生成草稿和复核哈希。

签字：________________　日期：2026-08-____
