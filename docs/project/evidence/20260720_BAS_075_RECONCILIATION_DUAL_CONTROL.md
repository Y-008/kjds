# BAS-075：财务三方对账双人控制与原件独立性

## 结论

三方对账不再只凭金额相等返回 `matched`。现有 `FinanceService` 增加双人控制和银行原件独立性复验，不增加数据表、服务、依赖或银行解析器。

状态：`DONE_ENGINEERING`。真实 Ozon 结算、银行到账和 FX 原件尚未取得，因此本次只证明控制逻辑，不宣称完成真实对账或真实利润核算。

## 失败关闭规则

1. 对账人若同时是相关 Evidence 上传者、Finance Entry 创建者、已采用费用映射批准者或已采用 FX 创建者，状态为 `blocked_self_review`。
2. 银行到账与平台侧订单、费用、退货或结算按 Blob SHA-256 比较；同一文件即使换来源重新存证，状态仍为 `blocked_evidence_independence`。
3. 快照保留自审依赖的对象类型/ID，以及冲突 Blob 哈希和两侧 Evidence ID，供责任人修复交接。
4. 缺 FX、未知费用、待复核和缺资金腿继续保持更早的阻断优先级，不因新增控制掩盖数据缺口。
5. 规则只影响对账判定，不自动批准分录、生成凭证、吞掉差异或写入 ERP。

## 验证

- 独立上传、独立录入、独立映射/FX 和独立复核的完整三腿：`matched`；
- 对账人创建任一相关分录：`blocked_self_review`；
- 对账人上传任一相关原件：`blocked_self_review`；
- 同一 Blob 以两个不同 Evidence ID 分别冒充平台与银行原件：`blocked_evidence_independence`；
- 财务目标测试：10/10 通过；
- Python 全量回归：309/309 通过（使用仓库内独立 pytest 临时目录；仅一条第三方 Starlette 弃用警告）；
- Ruff：通过；
- G-1 全量门禁：`PASS`（`2026-07-20T04:45:59.7943115Z`），迁移头 `20260720_0038`；
- G-1 同时验证 Python、16 项 Web 测试、Web build、财务对账、备份恢复和清理均通过；恢复包 SHA-256：`e95cd0cd1349dd15f19528ddc1e345727e903e98c42e2f40f1edb9dbdef48bd6`。

## Review

- P0：未发现。
- P1 / ask-user：财务负责人仍需提供真实 Ozon 结算、银行到账和 FX 原件，并指定互相独立的上传、录入和复核身份。
- P1 / defer：真实银行格式到达前不开发专用解析器；首份文件进入后再冻结字段合同和差异队列。
- P2 / no-op：不安装完整 ERP 来替代证据、对账和责任分离；ERPNext 仍只允许隔离侧车 PoC。
