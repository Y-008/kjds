# BAS-077：实际成本权威复核工作台

## 结论

BAS-076 的严格后端门禁已经补齐非技术人工入口。Operator 可以选择现有 Evidence 和成本项读取 `pending/accepted/rejected`；Reviewer、Compliance、Admin 可以在同一工作台核对四项条件并保存不可变接受或拒绝。页面不保存一份成本—权威映射，全部规则由后端只读目录下发。

状态：`DONE_ENGINEERING`。这证明人工复核路径可操作，不代表真实 SKU 已取得供应商、物流、Ozon、税关、银行或 FX 原件，也不代表任何实际成本已经被真实复核接受。

## 交付边界

- `GET /v1/finance/cost-authorities`：向 Operator/Reviewer/Compliance/Admin 返回 15 项成本、中文显示名和唯一允许的实际权威类型。
- `apps/control_plane/cost_evidence_review.py`：继续作为权威 ID 与中文名称的服务端唯一来源；未新增数据库或规则引擎。
- `web/app/page.tsx`：复用现有财务复核表单、会话角色和 Evidence 列表；没有新状态管理库、组件库或专用上传副本。
- Operator 只能查询；只有 Reviewer/Compliance/Admin 可提交；上传者自审仍由服务端拒绝。
- 复核只产生 Evidence/Lineage，不自动改写场景、入账、采购、定价、上架或晋升事实。

## 验证

- Python 全量：317/317 通过；仅有 1 条第三方 Starlette 弃用警告。
- Web 契约：19/19 通过。
- Next.js 生产构建：通过。
- Ruff：通过。
- OpenAPI：运行时与 `docs/project/contracts/openapi-v1.json` 一致；应用版本 `0.45.0`。
- G-1：`PASS`，`2026-07-20T06:35:03.0648792Z`–`2026-07-20T06:37:00.9618381Z`。
- G-1 运行验证：`actual_cost_authority_gate=true`、`actual_cost_authority_catalog=true`，目录恰好 15 项且自动状态变更、入账、采购和 Listing 全为 `false`。
- PostgreSQL 迁移：`20260720_0038`；无需新迁移。
- 隔离备份恢复 SHA-256：`b45228f5486b489c5dd7e7a79b7f488010b3b896fdfae919bf2afd99918e8fb1`。
- 清理：processes/database/files 全部完成。

## Review

- P0：未发现。
- P1 / ask-user：真实复核仍需要两个不同身份，以及具体 SKU 的一手账单；工作台不能替代这些输入。
- P1 / defer：首批真实原件出现重复格式前，不开发 15 套专用解析器。
- P2 / no-op：不增加第二套成本规则、通用表单引擎或完整 ERP；这些不会提高当前 G0 放行率。
