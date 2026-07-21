# BAS-063 版本化全成本场景模板实施证据

| 字段 | 值 |
|---|---|
| task | BAS-063 |
| date | 2026-07-20 |
| status | DONE_ENGINEERING |
| gate | G0 工程准备；不代表 G0 经营放行 |
| template | `ozon-ru-full-cost-v1` / formula `1.0.0` |
| migration | 无新增迁移；复用 `profit_scenarios.inputs_json` JSONB，并兼容旧平面结构 |

## 交付结论

现有 `ProfitScenario` 是唯一利润计算内核，本批没有复制萌啦公式、增加第二个计算器、安装第三方插件或新建模板表。服务端模板固定列出 15 项命名成本：采购、国内物流、头程、包装、仓储、关税、税费、尾程、平台佣金、广告、退款退货、汇兑、资金占用、售后和损耗。

每项必须记录：

- `estimate`：有 Evidence 支持的决策预估；
- `actual`：有 Evidence 支持的实际发生值；
- `unknown`：当前没有足够证据，必须阻断采购和 Listing。

缺少成本 Evidence、任一 `unknown` 或非零 `other_cost_cny` 都会使 `cost_complete=false`。解释接口返回逐项金额、状态、Evidence、CM3、CM3 率、保本价、安全边际和售价 `-10% / baseline / +10%` 敏感性，并固定声明 `automatic_pricing=false`。

## 主要实现

- `apps/control_plane/sourcing.py`：模板合同、状态校验、放行规则和场景解释。
- `apps/control_plane/sourcing_store.py`：在既有 JSONB 内保存 `values/template_id/cost_states`，读取时兼容旧平面输入。
- `apps/control_plane/sourcing_intake.py`：三家报价交接保留逐项状态；未知项不伪造假设 Evidence。
- `apps/control_plane/api.py`：API `0.41.0`，增加模板与解释只读接口，并扩展既有场景输入。
- `web/app/page.tsx`：补齐六类此前默认零的命名成本，并提供 15 项证据状态选择与比较卡状态摘要。
- `scripts/verify-g1.ps1`：在 PostgreSQL 重读后验收模板、15 项解释、放行状态和禁止自动定价。

## 验证记录

| 检查 | 结果 |
|---|---|
| 聚焦领域测试 | `15 passed` |
| API 合同测试 | `7 passed`；OpenAPI 快照已刷新 |
| Python 全量 | `284 passed`；仅保留 FastAPI/httpx2 上游弃用警告 |
| Web 契约 | `12 passed` |
| Next.js 生产构建 | PASS；类型检查和 13 个路由构建完成 |
| Ruff | PASS |
| G-1 | PASS；迁移回放、PostgreSQL 数值约束、API/DB/Web、生产容器、Evidence、采购链、备份恢复和清理全部通过 |
| G-1 新断言 | `versioned_full_cost_template=true`、`sourcing_evidence_gate=true`、`backup_restore=true` |

第一次 G-1 运行只在 Ruff 导入排序门失败，修正测试导入顺序后重新完整运行并通过；没有省略该失败记录，也没有用局部 smoke 替代完整重跑。Windows 全量测试第一次使用仓库内临时目录时被其他测试清理，随后改用 `D:\KJDS\pytest-temp\full-cost` 独立目录，284 项全部通过。

## 仍未完成

- 本批没有真实 Ozon 账单、物流账单、税单、银行成交汇率或供应商采购发票；页面默认值仍是待替换的场景输入，不是实际利润。
- 一个共同的“全成本依据清单”可以支持多项预估，但只有原件实际逐项覆盖时才有资格标记 `actual`；业务复核仍由人负责。
- 本批只有售价 ±10% 的确定性敏感性，不包含需求弹性、平台算法反应或竞争者跟价模型。
- 未实现用户自定义共享模板、自动费率更新、自动定价或平台写入；这些能力必须由真实使用瓶颈和单独 ADR 触发。
- G0 仍需要真实候选、真实一手成本原件、独立审批身份和经营负责人决定。
