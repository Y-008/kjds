# 2026-08-15 W2 Runbook 一致性审计

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-AUDIT-20260815-002 |
| 状态 | READ_ONLY_AUDIT |
| 范围 | 24 系列执行卡与本线程新增的 D1-D7 清单、授权门和总控卡 |

## 引用完整性

当前 W2 交付物由 `scripts/verify-w2-readonly-audit.ps1` 程序化检查：`W2_DOCS=26`、`W2_SCRIPTS=4`、`MANIFEST_CHECKED=30`、`TRACKED=0`、`STAGED=0`、`UNTRACKED=30`、`ISSUES=0`；`LATEST.json` 为当前权威快照。

已引用的 24 系列文件均存在，包括 24i、24j、24k、24l、24m、24n、24o、24p、24q、24r、24s、24t、24v、24y、24f、24h。当前程序化复核 `REF_COUNT=41`，`MISSING=0`；W2 v2 文档中未把 `4.92` 或四舍五入后的 `8,376` 当作当前事实。

## 授权门完整性

| 阶段 | 文件 | 状态 |
|---|---|---|
| D1 | 20260815_W2_D1_PRECHECK_GONOGO.md | 已生成并纳入索引 |
| D2 | 20260815_W2_D2_PRECHECK_GONOGO.md | 已生成并纳入索引 |
| D3-D7 | 20260815_W2_D3_D7_PRECHECK_GONOGO.md | 已生成并纳入索引 |
| 单页总控 | 20260815_W2_EXECUTION_CONTROL_SUMMARY.md | 已生成并纳入索引 |

## 数字锚点

| 锚点 | 审计结果 |
|---|---|
| 未读消息 39 条 | 与 24q、24s 一致 |
| 待处理评价 337 条 | 与 24q、24s 一致 |
| 文字评价 141 条、纯评分 196 条 | 与 24q 一致 |
| BEIJI 余额 8,568.15 ₽ | 与 24o、财务证据一致 |
| LINYAN 余额 8,375.94 ₽ | 与 CDP currentness 一致 |
| TREAS 余额 12,621.01 ₽ | 与 24o 一致 |
| TREAS 付款日 2026-08-29 | 与 24o 一致 |
| realFBS 14 天错误指数 0% | 与法医报告一致 |
| LINYAN 20 仓封锁 | 与 W2 仓库恢复矩阵一致 |
| BEIJI 2 仓封锁 | 与 W2 仓库恢复矩阵一致 |
| active FBS 订单 0 | 与 CDP 二次只读采样一致 |
| BEIJI/TREAS Premium grace 可用 | 与 CDP 二次只读采样一致 |

## 已处理冲突

1. 24i 和 24j 的旧俄语文案仍写“停运超过一年”，但法医报告显示 BEIJI 约 9.5 个月、LINYAN 约 7.5 个月。新增的 v2 工单文案和 D1 清单明确改用事实表述，不覆盖原 24i/24j 文件。
2. BEIJI 三次质量归档通知为 2025-10、2025-11、2025-12，v2 工单已按此表述。
3. 24i 的 W2 执行序是整周顺序，24s 是逐日安排。新增 D1、D2、D3-D7 清单按 24s 逐日口径，不把整周顺序当同日动作。

监控脚本 `scripts/capture_w2_ozon_cdp_snapshot.mjs` 已固化，并已通过本地 CDP 实跑验证。
`20260815_W2_AI_SNAPSHOT_LATEST.json` 已由该脚本生成，机器可读，三店余额、订单、仓库状态、商品状态与 Premium 无漂移。
PowerShell 值班命令 `scripts/run-w2-readonly-snapshot.ps1` 已固化，并已通过本地实跑验证。
`20260815_W2_AI_SNAPSHOT_BASELINE.json` 已冻结为当前基线；`scripts/compare-w2-ozon-snapshot.ps1` 可与 LATEST 比对输出余额、订单、仓库、商品状态与 Premium 变化，当前实测 `CHANGED`（LINYAN `to_supply` 6→7）。
`20260815_W2_STARTUP_PACK_V2.md` 已作为权威签字入口生成，纠正 24i 旧事实且不覆盖原文件。
## 工作树状态

- 本线程新增 W2 文件均为 `??`，未 stage；已清理两个测试时间戳快照，仅保留 `BASELINE.json` 与 `LATEST.json`。二者最近采样 2026-08-15T05:34:06Z，字段比对为 CHANGED；监测到 LINYAN `to_supply` 6→7，已记录为商品状态变化。
- 未发现行尾空白。
- 未覆盖或修改既有 24 系列 WIP。

## 未闭合项

- 工单发送、归档、改价、回复、RFQ、Premium、官促、提现均需真人执行，AI 不代发。
- `CASH_VERIFIED` 仍被银行或收款方流水原件阻塞，历史余额不能作为现金闭环证据。
- TREAS 提现窗口需到 2026-08-29 后确认。
- D1 签字尚未发生，因此全部店铺写操作仍处于 NO-GO。
