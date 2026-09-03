# 2026-08-15 W2 24 系列增量校正附录

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-24SERIES-DELTA-20260815-001 |
| 状态 | READ_ONLY_ADDENDUM |
| 范围 | 既有 24 系列执行卡中需要按 W2 最新只读证据替换的旧锚点 |
| 原则 | 不修改原 24 系列文件；执行时以本附录和 W2 最新文件为准 |

## 1. 权威替换表

| 原文件:行 | 旧值 | W2 权威值 | 依据 |
|---|---|---|---|
| 24_7DAY_SPRINT_REVIVAL_PLAN.md:35 | BEIJI 4.92 分 | BEIJI 4.86 分 | 20260815_W2_CURRENTNESS_CDP_READONLY.md |
| 24d_W1_NODE_STATUS_20260814.md:13 | BEIJI 销售中 15 / 准备销售 5；LINYAN 销售中 32 / 准备销售 3 | BEIJI in_sale 14 / to_supply 5；LINYAN in_sale 27 / to_supply 7 | 20260815_W2_AI_SNAPSHOT_LATEST.json，采样 2026-08-15T05:34:06Z |
| 24d_W1_NODE_STATUS_20260814.md:57 | 价格指数有利率 BEIJI 8% / LINYAN 7% | 价格不利 BEIJI 38% / LINYAN 100% / TREAS 71% | 20260815_W2_CURRENTNESS_CDP_READONLY.md |
| 24d_W1_NODE_STATUS_20260814.md:24 | LINYAN 余额 8,376 ₽ | LINYAN 余额 8,375.94 ₽ | 20260815_W2_AI_SNAPSHOT_LATEST.json |
| 24d_W1_NODE_STATUS_20260814.md:26 | 三店合计 29,565.16 ₽ | 三店合计 29,565.10 ₽ | 8,568.15 + 8,375.94 + 12,621.01 |
| 24aa_CASH_LEDGER_W2_20260816.md:14 | LINYAN 8,376.00 ₽ | LINYAN 8,375.94 ₽ | 20260815_W2_AI_SNAPSHOT_LATEST.json |
| 24p_W2_FRIDAY_NODE_TEMPLATE_20260815.md:11、26 | 现金余额 ≥29,565.16 ₽ | 现金余额 ≥29,565.10 ₽ | 同上 |

## 2. 历史净额补充

早期 W2 运营总览中的历史应计净额已由修正账勘误，详见 `20260815_W2_STORE_RISK_AND_PRIORITY_MATRIX.md`。执行现金账、KPI 或复投决策时使用修正值：

- BEIJI：`227,743.63 ₽`
- LINYAN：`315,887.23 ₽`
- TREAS：`14,058.18 ₽`
- 合计：`557,689.04 ₽`

旧值 `242,303.35 ₽ / 14,067.10 ₽ / 572,257.68 ₽` 不再作为公司级净额口径。

## 3. 执行提示

- 24 系列文件不覆盖、不重写；若某个 24 卡片与本附录冲突，以本附录标注的 W2 文件为准。
- `20260815_W2_AI_SNAPSHOT_LATEST.json` 仍为最近一次成功只读采样；当前本地 CDP 9224 已断开，恢复后需再次复采。
- 所有改价、归档、工单、提现、上架仍由真人执行，AI 不代写。