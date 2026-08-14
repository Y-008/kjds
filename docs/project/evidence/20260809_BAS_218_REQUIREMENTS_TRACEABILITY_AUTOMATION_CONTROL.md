# BAS-218 历史需求追溯与自动化控制机器合同 Evidence

## 1. 对象与边界

- Task：`BAS-218`
- 日期：`2026-08-09`
- 控制 CAS：`80c6bffbc4905bdd314bf56eed2b1ac791c324c9`
- Owner thread：`019fd4c1-60c9-79a0-9338-8c204ba0f312`
- Lane：`C / product_engineering`
- shared lease：`master_spec=BAS-218`

本切片新增唯一只读 `RequirementsTraceabilityProgram.project()`，把历次需求、机器合同、实现路径、版本、Owner、Gate、Evidence、六态状态和未完成项编译为确定性投影。它不读取运行任务、真人任命、现金、客户或外部平台，不创建 Fact、FinanceEntry、Approval、Permit，也不接外部写。

## 2. 设计比较

1. 立即合并隔离自动经营分支：拒绝。BAS-186 正占 runtime/迁移写域，分支也需要选择性语义合并和独立 G-1。
2. 只写 Markdown：拒绝。不能机器冻结字段、状态、路径与虚假完成负控。
3. 只读深 Module + 唯一 JSON 注册表：采用。构造时校验一次，公开 Interface 只有零参数 `project()`。
4. no_action：拒绝。会继续扩大版本漂移和重复建设风险。

## 3. 首版覆盖

追溯注册表覆盖：

- 18+12+20–40+5 团队总控；
- 14 领域角色、8 Squad、30–60 扩展专家池的全域 AI ERP；
- Coding Agent 文档先行与前沿技术复核；
- 单订单 Canonical Product/SKU Actual Cash CM3；
- 隔离自动经营四态、RFQ 回链和 Commerce OS；
- 成熟开源积木与可卸载 sidecar；
- Automation Grant 与 Safety Case；
- Process Conformance、Automation Value Ledger 与 Capability Passport；
- 商业化、客户价值与资本配置；
- 真实 SKU/RFQ/Ozon/现金阻断；
- 拒绝第二 ERP、任务总线和第三方事实权威；
- 因果策略、数字孪生、Skill 演进和竞争能力图谱保留。

## 4. 防伪规则

- 六种状态之外全部失败关闭；
- 每项必须有用户来源、Requirement ID、机器合同、实现路径、版本、Owner/替补、Gate、Evidence 和未完成项；
- 所有条目强制 `business_truth_status=UNKNOWN`、`business_truth_proven=false`；
- `ISOLATED_IMPLEMENTED` 必须绑定隔离 branch/head、isolated 路径、选择性集成 Gate 和 `mainline_integration_status=NOT_STARTED`；
- Pilot 必须同时具有 entry/exit Gate；
- `BLOCKED_EVIDENCE` 必须列出缺失权威；
- `REJECTED_DUPLICATE` 必须列出 canonical owner 和拒绝理由；
- 五个自动化控制合同均固定 `CONTRACT_ONLY`，且 `runtime_connected/creates_authority/external_write_allowed=false`。

## 5. 前沿技术复核

`frontier_review=checked_no_change`。本切片没有安装或升级依赖；只冻结后续 Pilot 合同。现有 frontier registry 的 OPA、Temporal、SPIFFE、Agent Eval 与 Graph/Memory 决策不变；OpenLineage、Docling、OpenFeature、Toxiproxy、PM4Py 等候选必须在独立任务完成官方来源、许可证、数据边界、成本、回滚和卸载 Gate。

## 6. 精确写集

1. `apps/control_plane/requirements_traceability.py`
2. `docs/project/registries/requirements_traceability.json`
3. `tests/test_requirements_traceability.py`
4. `docs/project/MASTER_SPEC.md`
5. `docs/adr/ADR-0096-requirements-traceability-and-automation-control.md`
6. `docs/project/evidence/20260809_BAS_218_REQUIREMENTS_TRACEABILITY_AUTOMATION_CONTROL.md`
7. `项目.md`

不修改 BAS-186 的 runtime、media、migration、worker、测试或 Evidence，不修改 router/API/OpenAPI/Web/DB/G-1。

## 7. 验证回执

- Python 编译：`PASS`（`requirements_traceability.py` 与对应测试）
- 定向 pytest：`58 passed in 0.19s`（追溯合同、工作流租约、前沿技术注册表）
- Ruff：`All checks passed!`
- JSON/路径/投影检查：`PASS`（12 条需求、6 种状态、5 个自动化控制合同；注册表与投影 SHA-256 可复算）
- Secret scan：`PASS`（1449 个非忽略工作树文件、1459 个历史路径）
- `git diff --check` 与 cached diff check：`PASS`；验证时 index 为空
- PostgreSQL、迁移、G-1、生产运行与外部写：`NOT_RUN / OUT_OF_SCOPE`

## 8. 未证明事项

以下全部继续 `UNKNOWN/BLOCKED_EVIDENCE`：真人任命与资质、真实六家 RFQ 和正式报价、Ozon offer 映射、退货退款观察窗、真实订单/结算/银行/Actual Cash CM3、设计伙伴、C0、生产 SLO、Automation Grant runtime、任何外部写和 Top1 宣传结论。
