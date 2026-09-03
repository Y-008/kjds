# KJDS 董事会状态快照（只读核验）2026-08-14

| 字段 | 值 |
|---|---|
| 快照类型 | 只读核验（不补数、不写控制文件、不 stage/commit/push） |
| 生成时刻 | 2026-08-14（深夜） |
| 权威依据 | `00_KJDS_方案权威索引_20260814.md` + `KJDS_90天董事会执行与Truth_SKU清单_20260814.md` |
| 当前总状态 | `BLOCKED_EVIDENCE` |

## 1. 本次独立复核的现场基线

| 项 | 值 | 判定 |
|---|---|---|
| 当前 HEAD | `2a0fd81`（分支 `feat/ai-listing-first-real-sku`） | 与仓库一致 |
| 工程测试 | `14 passed`（`tests/test_agent_inference.py` + `tests/test_ai_listing_taxonomy.py`，隔离 basetemp） | 通过，但仅覆盖两个测试文件 |
| 修正应计 CSV SHA-256 | `A02134794EA810C1A8BCDA7ABA02FB3457627157E7B9B475A74144759C933E3C` | 存在且未变 |
| 修正 CSV 行数 | `7,181`（含表头 7,182 行） | 本次 Python 独立复算一致 |
| 修正 CSV 总额 | BEIJI `227,743.63` / LINYAN `315,887.23` / TREAS `14,058.18` / 合计 `557,689.04 ₽` | 本次独立复算一致 |
| G-1 快照 | `.runtime/G1_VERIFICATION.json` `status=PASS` 但 `git_commit=b4380078` ≠ 当前 HEAD；`backup_restore=false`；`g1_control_mutex_finalization_required=true` | **不能作为当前变更集 G-1 证据** |
| startup-intake | 8/8 区 `awaiting_inputs`，`ready_sections=[]`，`automatic_import=false`，`formal_fact_promoted=false` | 与权威索引一致 |

## 2. 两处内部不一致（需 Owner 裁决后回写）

1. **G-1 快照陈旧**：`G1_VERIFICATION.json` 记录的是旧 commit `b4380078`，而当前 HEAD 是 `2a0fd81`。权威索引已明确“G-1 PASS 不覆盖 BAS-223 当前变更，runtime/API/Web 必须在新 HEAD 重跑隔离 PostgreSQL G-1”。结论：工程线不能标记完成。
2. **历史财务口径陈旧**：权威索引与 `20260814_OZON_OWN_STORE_FINANCE_ANALYTICS_OBSERVED.md` 仍引用 `7,178 行 / +572k ₽`；修正账为 `7,181 行 / 557,689.04 ₽`，差 `14,568.64 ₽`，来自 3 行非订单应计（BEIJI 合同互抵 `-14,698.76`、BEIJI 争议 `+139.04`、TREAS 广告 `-8.92`）。建议经营/财务 Owner 确认采用修正口径并回写权威索引，避免“+572k”继续被误当净额。

## 3. 唯一硬阻塞（不变）

Truth SKU 的 `CASH_VERIFIED` 被真人原件阻塞，8/8 资料区全部 `awaiting_inputs`。系统不得补数，历史净额/余额/研究笔记不得升级为 Cash 证据。

## 4. 解除阻塞清单（交真人，按优先级）

1. 经营负责人 + 独立控制席（至少两个不同真人）签署 `TRUTH-SKU-001` 与四席责任、最大损失、阶段预算、停止线。
2. Truth SKU 身份：稳定 Product/SKU/Ozon offer 映射 + 名称/材质/用途/产地 + 实测重量/长宽高。
3. 同一 SKU 三家真实报价原件（报价 ID、MOQ、单价/币种、交期、重量尺寸、国内物流、有效期）。
4. 合规原件（HS、EAEU/EAC、Честный ЗНАК、俄文标签、知识产权、运输限制）。
5. 只读 Ozon 身份与权限盘点（脱敏引用，不录密钥）。
6. 财务五段：`order_id → posting_number → 平台费用/结算 → 银行到账 → FX`，含银行流水备注中的 reconciliation key。
7. 独立复核：提案人≠复核人，只接受原始文件 + SHA-256 + 时间 + Owner。

## 5. 下一步与冻结

- 90 天冻结清单继续生效（World Model、Venture Federation、新国家/平台、社媒自动化等）。
- 唯一下一动作：真人交齐 §4 后，按 FIN-001 用 1 个真实 SKU 跑五段对账，`unmatched=0` 且独立复核通过后晋升 `CASH_VERIFIED`，再谈 1→3 SKU 与商业 C0。
- 修复建议（供 Owner，不代改）：`_validate_taxonomy` 增加“必填属性已填”的独立 fail-closed 门（见 `20260814_W1_REDTEAM_VALIDATION_GAP.md`，P2）。

## 6. 补充核验（工程线全量基线，2026-08-14 续）

本轮对工程线做全量只读核验，修正此前“15 passed / 两处 Ruff import-order 错误”的陈旧快照：

| 项 | 本次实测 | 判定 |
|---|---|---|
| Ruff（E/F/I/UP/B/SIM） | `All checks passed!` | 通过（含 import-order） |
| 非 Postgres 全量测试 | `3450 passed, 2 skipped, 0 failed`（排除 8 个 `*_postgres.py`） | 通过 |
| 财务/结算引擎 | `tests/test_scoped_settlement_cash.py` 等 4 文件 `59 passed` | 通过（ADR-0069 契约已实现） |
| 全量测试（含 Postgres） | `3522 passed, 14 failed, 174 errors, 76 skipped`；`14 failed + 174 errors` 全部落在 8 个 `*_postgres.py` 集成测试 | 环境缺 PostgreSQL，非代码缺陷 |

结论：工程线非 DB 部分已绿；唯一未验证的是“隔离 PostgreSQL 上重跑完整 G-1”（与权威索引/董事会要求一致，需可用的 PostgreSQL 实例）。
