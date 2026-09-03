# 2026-08-15 W2 D3-D7 执行前 Go/No-Go 状态表

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-D3D7-GATE-20260815-001 |
| 状态 | READ_ONLY_PREFLIGHT |
| 目标 | 在 D2 完成后，按日检查 D3-D7 动作与终止条件 |
| 最新只读依据 | 20260815_W2_CURRENTNESS_CDP_READONLY.md + 20260815_W2_BLOCK_FORENSICS.md |

## 一、总闸门

| 项 | 状态 | 判定 |
|---|---|---|
| D1/D2 已完成 | 待回填 | CONDITIONAL |
| active FBS 订单 | 0 | GO |
| realFBS 14 天错误指数 | BEIJI/LINYAN 0% | GO |
| TREAS 本轮操作 | 冻结至 08-29 | GO |
| AI 自动写操作 | 禁止 | GO |

## 二、D3 自动解封与官促

| 项 | 当前事实 | 判定 |
|---|---|---|
| 仓库封锁横幅 | 仍显示 | CONDITIONAL，截图留证 |
| 自动解封窗口 | 工单后约 3 天 | GO |
| 官促报名 | 仅过毛利门 SKU | CONDITIONAL |
| 弹性提升 | BEIJI/LINYAN 可加 | GO |
| 付费推广 | 不报 | GO |

## 三、D4 RFQ 跟催

| 项 | 当前事实 | 判定 |
|---|---|---|
| RFQ 发送 | D2 完成 | CONDITIONAL |
| 48h 无回 | 发跟催 | GO |
| 72h 无回 | 换供应商重发 | GO |
| 回价毛利门 | 到价后重算 | CONDITIONAL |

## 四、D5 工单追问与 TREAS

| 项 | 当前事实 | 判定 |
|---|---|---|
| 未解封 | D5 仍封锁时追问 | CONDITIONAL |
| 已解封 | 不追问 | GO |
| TREAS 余额 | 12,621.01 ₽ | GO |
| TREAS 8 月应计 | 0 | GO，08-29 前正常 |
| TREAS 提现 | 可提现金额 >0 后由真人操作 | CONDITIONAL |

## 五、D7 周五节点

| 项 | 当前事实 | 判定 |
|---|---|---|
| KPI 证据 | 需 D1-D5 截图齐备 | CONDITIONAL |
| 对账三表 | 逐笔核对 | CONDITIONAL |
| unmatched | 必须为 0 | CONDITIONAL |
| 未解封 | 进入 24t Plan B | CONDITIONAL |
| B1 升级申诉 | 首选 | GO |
| B4 新店 | 默认否决 | GO |

## 六、后半周验收门

1. D3 已记录解封状态、价格、绿价和 SKU 状态。
2. D4 已确认 RFQ 是否跟催，回价是否进入毛利门。
3. D5 已根据解封状态决定是否工单追问；TREAS 应计已检查。
4. D7 KPI、现金账、对账三表和 Plan B 决策已闭环。
5. AI 未执行任何店铺写操作。

## 七、终止条件

D7 仍未解封且工单无实质进展，则转 24t，优先 B1；出现任何 SKU 连续两个节点负毛利，则下架。TREAS 在 08-29 前不强制提现。
