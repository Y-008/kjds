# KJDS 项目文档中心

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-DOC-INDEX |
| owner | 项目负责人（待确认） |
| approver | 经营负责人 |
| status | Active |
| version | 1.0 |
| last_reviewed | 2026-07-16 |
| next_review | 2026-07-23 |
| gate | G-1–G8 |

本目录是 KJDS 的项目唯一真源入口。《方案001》保留为研究母稿，不能直接生成开发承诺；任务工作簿保留全部候选任务，但只有本文档中心明确进入阶段门的任务才属于当前执行范围。

阅读入口：[`KJDS_项目总纲与实时方法论.docx`](../planning/KJDS_项目总纲与实时方法论.docx) 汇总了章程、方法论、阶段门、当前 P0、运行手册和模板，适合评审与打印；日常更新仍应回到下列 Active 文档。

## 唯一真源

| 主题 | 权威文档 | 使用规则 |
|---|---|---|
| 目标、边界、成功定义 | [00_PROJECT_CHARTER.md](00_PROJECT_CHARTER.md) | 其它文档只链接，不复制改写 |
| 经营与工程方法 | [01_LIVE_METHODOLOGY.md](01_LIVE_METHODOLOGY.md) | 每周复审，变更必须留证据和原因 |
| 阶段门与放行标准 | [02_ROADMAP_AND_GATES.md](02_ROADMAP_AND_GATES.md) | Gate 未通过不得用“基本完成”代替 |
| 当前剩余任务与并行调度 | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) | 当前 P0 只来自这里 |
| 决策、来源和未知项 | [04_SOURCE_DECISION_UNKNOWN_REGISTER.md](04_SOURCE_DECISION_UNKNOWN_REGISTER.md) | 事实、假设、决策、未知分开登记 |
| Build / Buy / Reuse | [05_BUILD_BUY_REUSE.md](05_BUILD_BUY_REUSE.md) | 新技术先判断必要性和阶段适配 |
| OpenClaw–Hermes 运维 | [06_OPENCLAW_HERMES_RUNBOOK.md](06_OPENCLAW_HERMES_RUNBOOK.md) | 不记录任何明文密钥 |
| 可复用模板 | [templates/README.md](templates/README.md) | 先用真实 SKU/账单试填再冻结 |

## 受控来源

- `方案001.docx`：研究母稿，只读引用；包含 Ozon 三 SKU 经营系统、Harness 工程、全球经营系统与成熟度研究。
- [sources/方案001_全文顺序提取.md](sources/方案001_全文顺序提取.md)：按原 Word 顺序保存的完整机械提取稿，仅用于全文检索和追溯。
- `Ozon_90天执行总纲.md`：既有经营计划，需按当前阶段门解释。
- `docs/planning/KJDS_可执行任务总库_Backlog.xlsx`：108 项候选任务库存，不等同于当前 P0。
- `docs/planning/KJDS_可执行任务总库.docx`：任务库阅读版。
- `docs/architecture.md`、`docs/adr/`：当前工程边界与已批准架构决策。

## 状态规则

- `Draft`：正在形成，不能用于放行。
- `Active`：当前唯一有效版本。
- `Frozen`：保留历史，不再派生当前任务。
- `Superseded`：已被新文档取代，必须指向替代版本。
- 工作项状态只允许：`NOT_STARTED`、`IN_PROGRESS`、`BLOCKED`、`NEEDS_REVIEW`、`DONE`。
- 任何 `DONE` 必须同时具备负责人、验收结果和证据链接。

## 当前项目判断

当前 KJDS 是可演示、可扩展的工程骨架，不是已打通的经营闭环。工程骨架约 35%–40%，90 天真实经营闭环约 10%。当前瓶颈是三个真实 SKU、Ozon 账户与权限、合规/样品证据、物流、结算和银行到账，而不是继续扩展平台模块。
