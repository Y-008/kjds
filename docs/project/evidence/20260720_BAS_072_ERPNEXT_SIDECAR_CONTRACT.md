# BAS-072 ERPNext 隔离侧车防双写合同证据

## 结果

ERPNext 首选侧车已从“公开能力候选”推进到可执行的合同级 PoC，但仍未安装或获得远程写权限。KJDS 现在可以离线生成 ERPNext Item、Purchase Order 和 Journal Entry 候选草稿，并在任何网络调用之前验证稳定外部 ID、来源版本、幂等、Evidence、Decimal、币种、FX、Owner 和平衡关系。

## 可复验产物

- `docs/adr/ADR-0013-erpnext-sidecar-poc-contract.md`
- `docs/project/registries/erpnext_poc_contract.json`
- `apps/control_plane/erpnext_poc.py`
- `tests/test_erpnext_poc.py`

## 已验证约束

- 所有 envelope 固定 `mode=poc_dry_run`、`docstatus=0`、`automatic_submit=false`；模块没有远程写方法。
- Item、采购单和财务候选单据使用稳定来源对象、版本、外部 ID、幂等键和 payload SHA-256。
- 无 Evidence、浮点金额、非法币种、缺 FX 原件、无时区 FX、同键不同 payload、生产写模式和自动提交均失败关闭。
- 跨币种采购单把汇率原件同时放入 FX 上下文和 envelope Evidence 列表。
- 财务候选必须精确借贷平衡；对账只返回 `matched/difference/blocked`，不会自动调账。
- Frappe Webhook 使用原始 body 的 HMAC-SHA256 常量时间比对。
- 机器注册表的 DocType、Owner 和写权限边界与代码一致。

## 验证

- `uv run ruff check .`：PASS。
- `uv run pytest -q --basetemp .pytest-tmp-full-0038-erpnext`：303 passed；仅 1 条上游 Starlette/httpx 弃用告警。
- `npm test`：16 passed。
- `npm run build`：PASS，Next.js 生产构建和 TypeScript 检查通过。
- `scripts/verify-g1.ps1`：PASS；`.runtime/G1_VERIFICATION.json` 记录迁移头
  `20260720_0038`、迁移回放、303 个 Python 测试、16 个 Web 测试、Web
  构建、容器导入、API/Web 健康、备份恢复和全部清理均通过。
- 完整验收同时修复了两个过期夹具：决策数值完整性插入补齐
  `selection_assessment_json={}`；交互档案验收从 5 个升级为 6 个，并显式验证
  `best_solution` 的 `/best` 别名和 `1.0.0` 版本。没有放宽数据库约束、秘密扫描
  或产品门禁。

## Review findings

- P0：无。
- P1 / defer：尚未启动 ERPNext 测试公司、最小权限用户、真实 Frappe REST round-trip、Webhook 回放、备份恢复或卸载演练；因此不得迁移 Owner 或写任何真实单据。
- P1 / ask-user：真实 Ozon 需求报告、三个候选、三家报价和独立财务复核仍缺，不得用本 PoC 宣称经营全链路完成。
- P2 / defer：Purchase Receipt、Landed Cost Voucher、Sales Invoice 和 Payment Entry 已在机器合同注册，但尚未添加投影器；应等对应真实脱敏样本出现后逐个实现，避免猜字段。

## 下一门

先由不同 Reviewer 接受或拒绝现有 Ozon 计提原件，并取得一个真实候选 SKU 的三家报价。随后用脱敏副本补足 Receipt、Landed Cost、Settlement 和 Payment 映射，再决定是否启动 ERPNext 隔离容器。当前状态为 `DONE_ENGINEERING`，不等于 ERPNext 已接入或生产可用。
