# BAS-215A 全域 AI ERP 组织、Squad、WBS 与成熟度机器合同 Evidence

- Task：`BAS-215A`
- 基线日期：`2026-08-07`
- 机器租约：Lane `M`，Owner `019fd4c1-60c9-79a0-9338-8c204ba0f312`
- CAS commit：`cbab2c93dbc0c3064a217490691213397ae00010`
- follow-up 基线：`d9042de6b2515fc6ac101b8da83a67358b089009`（首个 BAS-215A exact4 功能提交；本次不 amend，只闭合迟到独立红队发现）
- 实施状态：`DONE_ENGINEERING_CANDIDATE`
- 外部经营状态：`UNKNOWN`
- Runtime/API/Web/DB/G-1/外写：未接入、未运行、未授权

## 1. 本切片证明了什么

本切片新增一个只读深模块 `EnterpriseAiErpProgram`，把用户批准的全域 AI ERP 组织和 Day 0–365 计划编译为确定性机器合同：

- 14 个企业领域 Lead，逐个冻结唯一主责、角色替补、30/60/90 天结果、工具/数据白名单、SLA、Reviewer、预算和最大损失未知状态、冲突声明、Evidence、Stop 与交接条件；
- 30–60 人任务有界全球专家池目标及九类专业覆盖；静态容量合同不证明任何专家已签约或取得资质；
- 8 个并行 Squad，每组固定五类职能，并只引用现有 Capability Atlas 的真实 capability ID；每组只保存 `first_acceptance_contract` 验收要求，不保存或投影完成语态的结果；尚不存在的 HCM、PLM、MES 等能力只登记为 gap，不冒充已实现能力；
- `EAERP-01..06` 完整 WBS 合同、依赖 DAG 和四个并行波次；14 个领域角色必须至少映射一项 Squad/WBS 主责、替补或审阅责任，Squad↔WBS 引用边必须双向精确相等；
- Day 0–30、31–60、61–90、91–180、181–365 五阶段验收合同；
- M0–M4 能力成熟度 Evidence 要求、顺序晋级和失败关闭策略；
- 六类职责分离、`1 总控 + 最多 3 专业 Agent`、最多 3 个并行 Writer、每专家和每 Writer 最多 1 个 active task、每 Lane 最多 1 个 current task、每周最多 3 个公司结果、每周 2 次集成列车和六个单一集成人写域；
- 机器合同、Team Control、Global Expert Team、Capability Atlas 四源语义哈希和确定性 projection hash。

`contract_integrity=VERIFIED` 只说明上述静态结构和引用闭合；总体状态、真人绑定、Squad readiness、WIP、Gate、成熟度、现金、客户和 Top1 始终为 `UNKNOWN`。提交 `d9042de` 后收到的独立早期红队 P1 使旧冻结双签失效；本 follow-up 专门关闭“验收结果静态冒充完成”和“角色/双向责任边不闭合”两个反例，必须重新冻结和独立签署后才能释放 Lane M。

## 2. 方案比较

### 方案 A：直接扩展 `TeamControlTower`

优点是老板端最终投影路径短。淘汰原因是本切片尚未连接真人、OperatingTask、Evidence 和 Gate 权威，直接加入 Tower 会改变现有 decision basis 和 continuation，扩大共享 Runtime/Router 风险。

### 方案 B：建立 vendor-specific ERP 或第二任务/组织账

优点是表面上接近 SAP、用友、金蝶产品结构。淘汰原因是会复制 OperatingTask/Event、Team Control、Capability Atlas 和 Evidence 真源，并产生供应商锁定和虚假完成声明。

### 方案 C：单一 `EnterpriseAiErpProgram` 静态合同编译器

已采用。构造时只读验证四个注册表并编译一次，公开业务 Interface 只有零参数 `project()`；构造完成后无 I/O，不读取运行任务或身份，不创建 Fact、FinanceEntry、Approval、Permit，也不接外部写。后续只有在 BAS-215B 获得独立租约后，才可把该投影接入现有 `TeamControlTower.brief`。

## 3. 企业产品对标与 KJDS 决策

本次只使用官方一手资料做设计影响分析，没有安装厂商 SDK、采购产品或把厂商结论升级为 KJDS 运行权威。

### SAP

截至复核日，SAP 官方实施主线是 `RISE with SAP Methodology`，以 SAP Activate 为基础，并组合 clean core、SAP Signavio、SAP LeanIX、SAP Cloud ALM、SAP BTP、Joule 与 S/4HANA Cloud 的转型和持续运行能力。官方资料：

- <https://help.sap.com/docs/cloud-alm/applicationhelp/rise-with-sap>
- <https://www.sap.com/products/erp/rise/methodology.html>
- <https://www.sap.com/products/erp/rise/what-is-rise-with-sap.html>

KJDS 采用其 Fit-to-Standard、clean core、流程/架构建模、实施质量 Gate 和持续优化思想；SAP 产品只允许未来的可导出、可卸载、只读 partner/sidecar Pilot。不存在名为 “AI Native Implementation” 的 SAP 官方第三代替代方法论证据，因此本项目不把该民间名称写成官方事实。

### 用友

用友官方材料展示了 BIP 企业 AI 产品矩阵、企业业务本体/本体智能体及覆盖财务、人力、供应链、制造、营销等领域的 Agent/Skill 能力：

- <https://www.yonyou.com/news/4796>
- <https://www.yonyou.com/news/8553db86-9457-4887-a700-35ffc34eb8f7>

KJDS 对标企业业务本体、稳定 ID、领域 Skill、Agent 生命周期和全域业务覆盖；超越路径固定为 exact-scope、valid-time/current-authority、Actual Cash CM3、Evidence lineage、Permit/Readback 和确定性回放。用友平台不得替换 KJDS 控制面或成为生产事实/权限权威。

### 金蝶

金蝶官方材料展示了 AI 苍穹平台、领域模型、低代码、智能体平台和 AI 超级套件的企业级组合：

- <https://www.kingdee.com/products/cosmic_platform.html>
- <https://www.kingdee.com/resources/articles/1488184050126660673>

KJDS 对标领域模型、流程平台、Agent/Skill、全域 ERP 与实施平台；厂商低代码、Agent runtime 和领域套件保持 `partner/pilot/watch`，只有通过数据主权、成本、权限、回滚、导出和卸载 Gate 才能进入隔离 Pilot。

### 固定 build/buy/partner/defer/no_action 边界

- `build + adopt_now`：Evidence-first、企业业务本体、稳定 ID、有效时间、Actual Cash CM3、exact-scope、Agent Eval、Permit/Readback、确定性回放；
- `partner + pilot`：SAP、用友、金蝶及其他 ERP 的只读 sidecar、官方 API、导出和差异对账；
- `watch`：厂商 Agent runtime、低代码、数据云和自动配置；
- `defer`：HCM、PLM、MES、EAM、GL 全量替换，直到真实客户 Pilot、成本和卸载证据闭合；
- `reject_now`：任何厂商 ERP 替换 KJDS 控制面、取得 Fact/FinanceEntry/Approval/Permit 权威或形成不可导出生产锁定。

## 4. 前沿技术 freshness 复核

重大任务按 `AGENTS.md` 读取唯一前沿技术注册表，并核对与本切片相关项目：

- `agent_run_tracing_and_evals`：`changed`。OpenAI hosted Evals/Graders 弃用已在 BAS-213 修正；BAS-215A 仅采用 provider-neutral 本地 AgentRun/Trace/Eval 合同，不引入 hosted Evals 运行依赖；
- `genai_semantic_conventions`：保持 `pilot`。OpenTelemetry GenAI 语义约定仍处 Development，必须有 translation boundary、版本 pin 和默认不捕获内容；
- `a2a_cross_agent_interoperability`：`checked_no_change`，保持 `watch`。A2A 协议稳定不等于 KJDS authority、撤销和 Permit 可用；
- `mcp_tasks_durable_protocol`：`checked_no_change`，保持 `watch`。Tasks 扩展和 SDK 支持仍不足以替换 OperatingTask/Event；
- `causal_temporal_graphrag_memory`：`checked_no_change`，保持隔离 `pilot`。GraphRAG 只可消费 canonical Graph 的只读导出，不能成为因果、时态或权限权威。

未刷新上述后三项注册表日期；无官方材料变化就不伪造 freshness。材料变化和边界详见 [BAS-213 Evidence](20260807_PROJECT_ENTRY_AND_FRONTIER_REVIEW_GOVERNANCE.md)。

## 5. 权威与防伪边界

- `OperatingTask/Event` 仍是唯一任务状态权威；Lane affinity 不是租约；
- `active_workstream_assignments.json` 仍是唯一机器写域/泳道权威；
- `TeamControlTower` 和 Global Expert Team 仍是现有组织合同；静态 14 角色不证明真人主责、替补或资质已到岗；
- Capability Atlas 仍是现有能力 ID 权威；gap 只证明缺口被命名；
- Evidence、StrategicBenchmark、Finance 和现有 Gate 仍是成熟度、Top1、现金和发布权威；
- M0–M4 是能力成熟度，不复用经营 `OperatingStageVerifier`，任务 resolved 和日历均不能晋级；
- projection 不读取 active assignment、OperatingTask、Evidence、Finance、Fact、身份、Gate 或当前时间；
- 所有外部动作、付款、合同、法律结论和账户权限仍需既有真人权威和 Permit。

## 6. exact4 与哈希

精确写集：

1. `apps/control_plane/enterprise_ai_erp_program.py`
2. `docs/project/registries/enterprise_ai_erp_program.json`
3. `tests/test_enterprise_ai_erp_program.py`
4. `docs/project/evidence/20260807_BAS_215A_ENTERPRISE_AI_ERP_PROGRAM.md`

当前非自引用原始 SHA256：

- Module：`3884190fff0f3a115f3167abf47b1234718ba141518b37080a7f884988bc2e8a`
- Registry raw：`8d5fb2cf5b1824957ce6a62f7e86c961d75f162f042232f88f2db8f4d165499d`
- Tests：`726ea5c02919500325d1eea993b206ab27c62c3c2b62f96a374d6d07c0c2b115`

确定性语义哈希：

- Program registry：`8ba3f6a2a3293a66416dd474223d538c7dc1ff5a3c57789c34d994be0aa26657`
- Team Control：`7ea44e05ef2d4dc8d3a476d0933991c42a63ea0bcd5827c588b3312d627debc5`
- Global Expert Team：`1c6fd73a84d49bcfda5f98f2490ed2e9b0adc17bc4479163353d9cc22a2f3950`
- Capability Atlas：`db5c29731bc8bfa5d5c0f7dc9d35247a4ab3a98dc149afe88745637376507eeb`
- Source bundle：`5a19123b858752d8a7611e542e918a5b81a9c7b24131291116135736f12b93f5`
- Projection snapshot：`c203e25a36ed257e0757eeff0d9124dfe4db1dcd2225d12e2d9d06d4fca583f9`

## 7. 验证记录

- `py_compile`：PASS；
- `tests/test_enterprise_ai_erp_program.py`：`67 passed in 0.68s`；
- BAS-215A + Team Control + Global Expert Team + Capability Atlas focused 回归：`115 passed in 4.38s`；
- 负向覆盖：完成语态动态真相字段、14 领域角色责任覆盖、Squad↔WBS 单边删边/增边、角色/Squad/WBS/引用、DAG cycle、阶段、M0–M4、SoD、并发上限、三类上游版本漂移、四源哈希和零 I/O；
- Ruff：`All checks passed!`；
- 初次 pytest 在系统全局 temp 根因 `WinError 5` 中止；未改代码，改用本任务独占 `D:\KJDS\.runtime\bas215a-pytest-e32448d75d0d4bbaa79288f63772653f` 后全绿；最终 focused 回归使用独占 `D:\KJDS\.runtime\bas215a-focused-24e0ffc618f644208ecfead8ae0d8e8f`；受控递归清理被本地策略拒绝，两目录登记为 `cleanup_pending`，位于仓库外且不计入 exact4 manifest；
- Secret：`Secret scan passed: 1420 non-ignored worktree files and 1415 historical paths checked`；
- `git diff --check`：exit `0`；cached diff check：exit `0`；
- DB、Alembic、G-1、API/OpenAPI、Web build：本切片明确不运行。

## 8. 未证明事项

以下全部保持 `UNKNOWN/BLOCKED_EVIDENCE`：

- 14 个新角色、8 Squad 和 30–60 人专家池的真人主责、替补、签约、资质、预算、最大损失及利益冲突；
- 任何 EAERP work item 已启动、完成或取得 Lane/共享写域租约；
- 任何能力达到 M0–M4；
- 一个真实 SKU 的订单、结算、银行和 Actual Cash CM3；
- C0、设计伙伴、SOW/DPA/SLA、客户价值和续费；
- 生产 RPO/RTO、p95、99.9% 可用性和发布 Gate；
- 任何 KJDS 对 SAP、用友、金蝶或其他产品的 Top1 市场宣传结论。

后续唯一集成方向是 BAS-215B：在不增加第二命令总线的前提下，把纯投影通过依赖注入接入现有 `TeamControlTower.brief`，并由真人/任务/Evidence/Gate 权威填充动态状态。BAS-215B 未获独立租约前不得启动。
