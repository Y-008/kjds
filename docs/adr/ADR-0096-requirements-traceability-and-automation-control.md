# ADR-0096：需求追溯与自动化控制结构合同

## 状态

Accepted — 2026-08-09

## 背景

KJDS 已连续交付团队总控、全域 AI ERP、前沿技术治理、单 SKU 现金归因，以及隔离分支中的自动经营/RFQ 回链。此前信息分散在用户决策、MASTER_SPEC、动态任务、注册表、ADR、Evidence 和隔离 Git 历史中，容易出现三类错误：

1. 历史建议已经进入工程，却在下一版计划中被重复设计；
2. 隔离分支实现被误报为已经进入当前主线；
3. `DONE_ENGINEERING` 或静态合同完整被误报为真人、真实经营、客户价值或 Gate PASS。

同时，最新 AI 自动化方案提出 Automation Grant、Safety Case、Process Conformance、Value Ledger 和 Capability Passport。它们需要先形成可验证合同，但当前 BAS-186 正占用 `runtime.py` 与迁移租约，不适合立即接运行时。

## 方案比较

### 方案 A：立即合并隔离自动经营分支

拒绝。当前主线与隔离分支已长期分叉，且 BAS-186 正持有 runtime/迁移写域。直接 merge/rebase 会混合独立任务、文档上下文和发布证据，无法独立回滚。

### 方案 B：只增加一份 Markdown 清单

拒绝。可读但不可机器校验，不能冻结状态词、必填字段、隔离分支边界或阻止虚假完成。

### 方案 C：新增只读深 Module 与唯一机器注册表

采用。`RequirementsTraceabilityProgram` 在构造时读取并验证唯一注册表，公开 Interface 只有零参数 `project()`；复杂的字段、状态、路径、状态特例和防伪校验留在 Module 内。

### 方案 D：等待所有真实 Evidence 后再建立追溯

拒绝。等待会继续扩大版本漂移和重复建设风险；结构追溯本身不需要伪造真实经营结果。

## 决定

1. 建立 `requirements_traceability.json` 作为历次需求追溯的唯一机器真源。
2. 每项固定十类信息：需求来源、Requirement ID、机器合同、实现路径、当前版本、Owner、Gate、Evidence、状态、未完成项。
3. 状态只允许六种：
   - `ADOPTED_ENGINEERING`
   - `ISOLATED_IMPLEMENTED`
   - `CONTRACT_ONLY`
   - `PILOT_PENDING`
   - `BLOCKED_EVIDENCE`
   - `REJECTED_DUPLICATE`
4. 所有条目无条件保存 `business_truth_status=UNKNOWN`、`business_truth_proven=false`；动态权威接入前不得升级。
5. 隔离自动经营实现必须绑定分支和复核 HEAD，路径使用 `isolated:`，且选择性主线集成保持 `NOT_STARTED`。
6. 五个自动化控制对象当前只冻结结构合同，不接运行时，也不创建任何授权：
   - `automation_grant_authority_v1`
   - `automation_safety_case_v1`
   - `process_conformance_report_v1`
   - `automation_value_ledger_v1`
   - `automation_capability_passport_v1`
7. KJDS 现有 Commerce OS、OperatingTask/Event、Evidence、Finance、Approval、Permit、Outbox、Readback 和 Kill Switch 继续拥有运行权威；本决定不建立第二套控制面。

## Interface

```python
RequirementsTraceabilityProgram(...).project() -> dict[str, Any]
```

构造完成后 `project()` 不执行 I/O，只返回 defensive copy。调用方不得提交客户端状态或要求 Module 计算业务完成度。

## 后果

### 正面

- 历次用户要求、机器合同和真实缺口可以逐项审计；
- 隔离实现与主线实现不再混淆；
- 新计划可复用既有高级设计，而不是重复造概念；
- 自动化运行时可以在后续独立租约中按合同逐项接入。

### 代价

- 重大需求变化必须同步维护追溯注册表和 Evidence；
- 当前只证明合同完整，不提供运行态搜索、API 或老板页；
- 隔离分支继续需要独立的选择性集成任务与 G-1。

## 失效与后续

只有出现已批准的新追溯权威、隔离分支完成选择性集成，或运行时正式接入 Automation Grant/Safety Case 等动态权威时，才允许扩展或替代本决定。任何此类变化必须通过独立 ADR、租约、负向测试和回滚 Gate。

## 前沿技术复核

`checked_no_change`。本切片不安装、升级或运行第三方技术；现有 OPA、Temporal、SPIFFE、Agent Eval、GraphRAG 等采用决定不变。OpenLineage、Docling、OpenFeature、Toxiproxy、PM4Py 和其他候选只能由后续 Pilot 任务完成官方来源、许可证、数据边界、成本和卸载复核后进入使用范围。
