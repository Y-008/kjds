# BAS-059：候选证据权威等级门验收证据

| 元数据 | 值 |
|---|---|
| task_id | BAS-059 |
| requirement | BR-045 |
| status | DONE_ENGINEERING |
| verified_at | 2026-07-20 |
| scope | 候选研究 Evidence 等级、三报价放行、非技术 Web 提示 |
| business_gate | SKU-000 / SKU-001 / UNK-001 仍未放行 |

## 1. 发现的问题

候选研究已经复验原件哈希、来源、时效、测量合同、需求报告绑定和双来源族，但此前没有使用 Evidence 的 A/B/C/D 等级。操作者如果把第三方选品工具、ERP 或利润计算器资料作为五项指标来源，系统可能在两家第三方来源相互独立时进入三报价。

这不是文件完整性错误，而是证据权威性错误。删除这些资料会损失探索知识；允许它们单独放行又会污染选品决策。

## 2. 已实现合同

- 需求强度、竞争缺口、供货确认和退货风险至少需要 A/B 级 Evidence。
- 合规红线只接受 A 级官方原件。
- C/D/UNKNOWN 或未知等级的资料不进入指标聚合、来源族计数或三报价放行。
- 低等级资料仍保留在不可变观测账，并通过 `low_authority_evidence_ids` 独立返回；不伪装为坏文件或过期文件。
- 响应返回每项指标的 `minimum_evidence_grades`，便于 Web 和后续 Agent 解释缺口。
- Web 新原件默认按 C 级收集，显示每份 Evidence 等级，并明确 A/B 声明必须基于一手原件且后续仍需独立复核。

## 3. 外部工具准入边界

以下来源可用于发现候选、比较口径和交叉检查，但当前不能成为最终经营事实：

- [BDM Ozon](https://www.bdmozon.com/)
- [Menglar Ozon 工具](https://ozon.menglar.com/tools/)
- [Seerfar](https://www.seerfar.cn/features/)
- [妙手 ERP](https://erp.91miaoshou.com/)
- [51Selling](https://www.51selling.com/main)
- [Ozon.ru 公共超市类目](https://www.ozon.ru/category/supermarket-25000/?miniapp=supermarket&__rr=1)

只有在来源身份、授权范围、字段合同、版本、时间语义、原始数据血缘和真实样本对账均通过后，才允许走正式变更流程提高等级。Web 文案或营销声明不构成升级依据。

## 4. 验证

- `tests/test_core.py` 增加五项均为 C 级时的失败关闭回归：观测保留，结果为 `collect_evidence`，五项均列入低权威阻塞，合规最低等级为 A。
- 候选核心定向测试：25 passed。
- Ruff 定向检查：通过。
- Web 合同测试：11 passed，覆盖默认 C 级、第三方边界和低权威提示。

- 全量 Python：267 passed（另有一条上游 Starlette/httpx 弃用警告，不影响结果）。
- Ruff：全库通过。
- Web：11 项测试通过；Next.js 生产构建通过。
- JSON 注册表与 `git diff --check`：通过。
- G-1 真环境：PASS；Alembic head `20260719_0037`，迁移重放、PostgreSQL 数值约束、备份恢复、生产 API/Web 镜像、API health/auth、Web health/proxy、Evidence、Kill Switch 与清理均通过；运行摘要以 `.runtime/G1_VERIFICATION.json` 为准。

真实账号原件、三个候选、三家报价和经营负责人阈值批准仍是独立业务门。

## 5. 不代表什么

- 不代表任何第三方工具已完成 API 接入或商业授权。
- 不代表已取得 Ozon 真实 28 天需求/竞争报告。
- 不代表候选已确认可采购、合规、盈利或可上架。
- 不自动创建商品、采购单、Listing 或平台写操作。
- 本任务本身不证明录入者声明的 A/B 等级已获批准；后续 `BAS-060/BR-046` 已实现独立、指标级权威复核，真实双用户演练仍按 `BAS-026` 验收。
