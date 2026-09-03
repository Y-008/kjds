# 2026-08-15 W2 Runbook 索引

| 分类 | 文件 | 用途 |
|---|---|---|
| 主执行总包 v2 | 20260815_W2_MASTER_EXECUTION_PACK_V2.md | 三店真人执行入口、D1-D7 顺序、授权门与签名栏 |
| 只读验证门 | 20260815_W2_READONLY_VERIFICATION_GATE.md | 本地 JSON、脚本语法、清单哈希与 staged 状态验证 |
| 启动包 v2 | 20260815_W2_STARTUP_PACK_V2.md | 权威签字入口，纠正 24i 旧事实 |
| 单页总控 | 20260815_W2_EXECUTION_CONTROL_SUMMARY.md | D1-D7 执行顺序、Go/No-Go 入口与 AI 边界 |
| 总诊断 | 20260815_W2_STORE_OPERATIONS_ANALYSIS_AND_NEXT_STEPS.md | 三店诊断、事实表和唯一执行顺序 |
| 风险优先级矩阵 | 20260815_W2_STORE_RISK_AND_PRIORITY_MATRIX.md | 修正后历史净额、三店风险与 D1-D7 优先级 |
| 历史 SKU 复投 | 20260815_W2_HISTORICAL_SKU_RELIST_CANDIDATES.md | 修正 CSV 聚合的历史净额 Top SKU 与首轮复投建议 |
| 改价/复投/归档交叉矩阵 | 20260815_W2_PRICE_RELIST_CROSSWALK.md | 合并 24x/24z 价格指数预演与历史 SKU 复投候选，形成 D1 真人三列执行矩阵 |
| 封锁法医 | 20260815_W2_BLOCK_FORENSICS.md | realFBS 封锁根因、仓库与官方规则只读证据 |
| 仓库恢复矩阵 | 20260815_W2_WAREHOUSE_RECOVERY_MATRIX.md | 三店 blocked/created/disabled 仓库明细与 D1 工单截图依据 |
| 解封文案 | 20260815_W2_UNBLOCK_SUPPORT_TICKET_V2.md | BEIJI 与 LINYAN 的事实校正俄语工单 |
| D1 清单 | 20260815_W2_D1_HUMAN_EXECUTION_CHECKLIST.md | 工单、归档、改价、Listing 执行顺序 |
| D1 授权门 | 20260815_W2_D1_PRECHECK_GONOGO.md | 执行前 Go/No-Go 状态与验收门 |
| D1 机器预检 | 20260815_W2_D1_MACHINE_PRECERT_CARD.md | 真人签字前的机器快照、NO_CHANGE 与写边界 |
| D2 清单 | 20260815_W2_D2_HUMAN_EXECUTION_CHECKLIST.md | 回复、评价、RFQ、Premium 执行顺序 |
| D2 授权门 | 20260815_W2_D2_PRECHECK_GONOGO.md | 消息、评价、RFQ 与 Premium 执行前 Go/No-Go |
| D3-D7 清单 | 20260815_W2_D3_D7_MONITORING_CHECKLIST.md | 解封检查、追问、节点和 Plan B |
| D3-D7 授权门 | 20260815_W2_D3_D7_PRECHECK_GONOGO.md | 解封、RFQ 跟催、TREAS、周五节点 Go/No-Go |
| 一致性审计 | 20260815_W2_RUNBOOK_CONSISTENCY_AUDIT.md | 引用、数字锚点和冲突处理 |
| 24 系列校正附录 | 20260815_W2_24_SERIES_DELTA_ADDENDUM.md | 24 卡片中需按 W2 最新证据替换的旧锚点 |
| 证据台账 | 20260815_W2_EXECUTION_EVIDENCE_LOG_TEMPLATE.md | 每日截图、工单号、SHA-256 回填 |
| RFQ 追踪 | 20260815_W2_RFQ_TRACKER_TEMPLATE.md | 三家产品供应商与深圳专线货代报价记录 |
| 只读探测 | 20260815_W2_CURRENTNESS_CDP_READONLY.md | 三店余额、仪表盘计数、仓库状态与 Premium 当前事实 |
| 基线快照 | 20260815_W2_AI_SNAPSHOT_BASELINE.json | 与 LATEST 比对的只读冻结基线 |
| 最新快照 | 20260815_W2_AI_SNAPSHOT_LATEST.json | 脚本生成的机器可读三店余额、订单、仓库状态与 Premium 快照 |
| 监控脚本 | scripts/capture_w2_ozon_cdp_snapshot.mjs | 每日只读生成三店余额、订单、仓库状态与 Premium 快照 |
| 值班命令 | scripts/run-w2-readonly-snapshot.ps1 | 先验证 CDP 9224 可达且 Ozon 卖家页已登录，再生成时间戳快照、latest、SHA-256 与当前摘要 |
| 差异比对 | scripts/compare-w2-ozon-snapshot.ps1 | 与 BASELINE 比对，输出余额、订单、仓库与 Premium 变化 |
| 只读审计 | scripts/verify-w2-readonly-audit.ps1 | 本地清单哈希、JSON/脚本语法、引用、敏感字样与 staged 状态 |
| 交付物清单 | 20260815_W2_GENERATED_ARTIFACTS_MANIFEST.md | 新增文件的 SHA-256 与大小 |

## 已有执行卡

| 文件 | 作用 |
|---|---|
| docs/project/24i_W2_STARTUP_PACK_20260815.md | W2 启动包与七步执行序 |
| docs/project/24j_DP8_UNBLOCK_EXECUTION_CARD_20260815.md | 解封工单原始执行卡 |
| docs/project/24k_DP2_ARCHIVE_EXECUTION_CARD_20260815.md | 15 项归档与暂停 |
| docs/project/24l_DP1_PRICE_CHANGE_EXECUTION_CARD_20260815.md | 两笔改价与 Listing 同步 |
| docs/project/24m_DP5_PREMIUM_TRIAL_CARD_20260815.md | BEIJI 免费 Premium |
| docs/project/24n_DP4_PROMO_ENROLL_CARD_20260815.md | 官促报名 |
| docs/project/24o_DP6_TREAS_WITHDRAWAL_CARD_20260815.md | TREAS 提现窗口 |
| docs/project/24p_W2_FRIDAY_NODE_TEMPLATE_20260815.md | 周五节点模板 |
| docs/project/24q_DP3_REPLY_EXECUTION_CARD_20260815.md | 39 消息与 337 评价回复 |
| docs/project/24r_DP7_RFQ_SEND_CARD_20260815.md | 1688 与货代 RFQ |
| docs/project/24s_W2_DAILY_SCHEDULE_20260815.md | W2 逐日安排 |
| docs/project/24t_PLANB_DECISION_PACK_20260815.md | 未解封时的 Plan B |
| docs/project/24v_QUALITY_TEST_ANSWER_PACK_20260815.md | Ozon Global 质量标准测试备料 |
| docs/project/24y_CONSISTENCY_AUDIT_20260815.md | 既有 24 系列一致性审计 |

## 使用顺序

先看总诊断与封锁法医，再按 D1、D2、D3-D7 清单执行。RFQ 与只读探测作为配套材料。所有外部写操作由真人完成，AI 只做只读核对和回填。
