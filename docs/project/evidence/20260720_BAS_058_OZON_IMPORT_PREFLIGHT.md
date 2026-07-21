# BAS-058：Ozon 原始财务文件只读预检验收证据

| 元数据 | 值 |
|---|---|
| task_id | BAS-058 |
| requirement | BR-044 |
| status | DONE_ENGINEERING |
| verified_at | 2026-07-20 |
| scope | Ozon 原始文件预检、正式导入复验、非技术 Web 交接 |
| business_gate | OZN-002 / FIN-001 / UNK-006 仍未放行 |

## 1. 问题与边界

正式上传后才发现 Ozon 原件列名不匹配，会留下拒绝导入；同一 SHA-256 原件在解析合同升级后又不能被静默重写或伪造为另一份文件。为避免运营人员手工改表头，本项增加正式存证前的只读预检。

初版没有猜测尚未见到的 Ozon 实际列名。2026-07-20 取得首份真实官方计提报表后，已按原件补充独立 `ozon_accrual` 合同；没有新增数据库表、服务或依赖，也不把预检结果晋升为财务事实。

## 2. 已实现合同

- `POST /v1/imports/ozon/preflight` 使用与正式导入相同的文件大小、期间、类型和解析合同。
- 返回文件 SHA-256、识别类型、行数、字段映射、缺失必需字段和 `ready`。
- 预检不写数据库、Evidence、暂存行、正式事实或费用映射。
- Web 先预检；只有 `ready=true` 才提交正式导入。
- 预检失败显示缺列并要求保留原文件，不要求改列名或另存伪原件。
- 正式导入不信任浏览器预检结果，重新校验文件、期间、哈希和解析合同。

## 3. 官方报告边界

[Ozon 官方代理协议](https://docs.ozon.ru/legal/en/partners/logistics/contract/?__rr=1) 将月度代理报告、服务文件/发票及异议确认周期作为独立结算文件与流程。由此，费用明细只能作为成本证据的一部分，不能单独证明结算、银行到账或会计归类。

首份 2025-10-01 至 2025-10-31 真实账户计提导出已经取得并通过无状态预检；哈希、结构和隔离复算见 `20260720_BAS_066_OZON_OFFICIAL_ACCRUAL_EXPORT.md`。仍需取得月度代理报告及服务文件、结算/现金流、广告、退款退货，并与银行到账及入账汇率核对。详细操作卡见 `docs/project/10_COST_SOURCE_AUTHORITY_AND_KUAJING84.md`。

## 4. 验证结果

- 定向 Python：21 passed。
- 全量 Python：266 passed；首次使用 Windows 公共临时目录时有 7 个用例因目录访问权限失败，改用仓库内隔离 `basetemp` 后全部通过，未掩盖产品失败。
- Ruff：全库通过。
- Web：11 项测试通过；Next.js 生产构建通过。
- OpenAPI：已重生成，应用版本 `0.38.0`，包含预检端点。
- JSON 注册表和 `git diff --check`：通过。
- G-1 真环境：PASS；Alembic head `20260719_0037`，隔离备份恢复、生产 API/Web 镜像、API health/auth、Web health/proxy、Kill Switch 与清理均通过；运行摘要以 `.runtime/G1_VERIFICATION.json` 为准。

## 5. 未完成与失败关闭

- 已取得一份真实 Ozon 计提原件、SHA-256 和实际表头；尚未正式存入 Evidence/Import Ledger，也未完成独立完整性复核。
- 尚未由独立 Reviewer 确认来源、期间、真实账户和导出完整性。
- 真实文件同时含收入、折扣、佣金、物流、冲抵和补偿，不能套用纯费用映射；尚未批准逐类会计分类和符号规则。
- 尚未完成 Ozon、银行到账与记账汇率三方对账。

因此 `OZN-002`、`FIN-001`、`UNK-006` 继续保持阻塞；BAS-058 只表示工程交接已就绪。
