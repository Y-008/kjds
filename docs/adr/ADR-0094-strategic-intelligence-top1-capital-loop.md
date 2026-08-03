# ADR-0094: 一手资料、Top1 对标与资本经营闭环

- 状态：Accepted（合同冻结）
- 日期：2026-08-03
- 任务：BAS-197
- 关联：BR-005、BR-007、BR-038、BR-039、BR-065、BR-076、BR-084，BAS-172、BAS-173、BAS-177、BAS-178、COM-002

## 背景

KJDS 已有 Evidence、Lineage、Fact、Finance、Operating Graph、AgentRun、产品与经营模块，也有技术采用、市场来源和成本权威注册表。当前缺口不是再建一个“资讯库”，而是把一手资料、外部领先基准、内部真实经营、产品/技术选择、商业实验和资本配置收敛为同一条可复验闭环。

“Top1”不能是全局口号。不同公司、平台、市场、阶段和约束不可直接总分排名；营销页、自媒体、模型回答和抓取页也不能自动成为事实。系统需要按明确指标、可比队列、时间窗、来源等级和适用边界识别“当前可验证的维度领先者”，再与 KJDS 当前 Evidence 做差距比较。

## 决策

### 1. 唯一深模块

新增概念模块 `StrategicBenchmarkKernel`，首版只形成合同，不建立第二事实库、第二财务账、第二权限面或第二任务系统。其外部接口固定为：

1. `build_snapshot(scope, as_of)`：只读组合现有 Evidence、Fact、Finance、Graph、AgentRun 和经营投影。
2. `compare(snapshot, benchmark_profile)`：按 metric/cohort/window/source contract 计算可解释差距。
3. `propose_portfolio(gaps, constraints)`：比较 build/buy/partner/defer/no_action，输出实验和资本配置提案。
4. `reconcile(experiment_receipts, as_of)`：把结果、成本、失败和失效条件回写为新的 Observation/Evidence 引用。

Kernel 不接收客户端自报 tenant/entity/authority，不保存原始经营正文，不创建 Fact、FinanceEntry、Entitlement、Approval、Permit、Payment、Pilot 或外部写。

### 2. PrimarySourceEnvelope

所有一手资料先形成 `PrimarySourceEnvelope`：

- `source_contract_id/version`、主体、来源 URI 或文件引用；
- 原始 Blob SHA-256、字节数、MIME、schema/parser 版本；
- `captured_at/effective_at/recorded_at/as_of`；
- tenant/entity/store/market/jurisdiction/category 适用范围；
- 数据许可、用途、保留期、删除/撤回和复审日；
- PII、秘密、商业敏感和跨境传输分类；
- 行数、字段数、分页/checkpoint、失败页和守恒报告；
- uploader、独立 reviewer、Evidence/Lineage 引用。

原件进入既有私密 Evidence/Blob 路径。Git 只保存合同、脱敏 fixture、哈希和验证报告，不保存账号、Cookie、API Key、银行信息、客户原始行、供应商原始报价或个人联系资料。

### 3. Top1 的精确定义

一个领先结论必须绑定：

`domain + metric + direction + unit + cohort + market + window + as_of + source_grade + sample + methodology + uncertainty + evidence_refs`。

规则：

- 只允许 `metric_leader`、`frontier_candidate`、`best_feasible_for_kjds`，不生成 `global_top1`。
- 当前值和基准值必须使用同口径；币种、税口径、时间窗、分母、样本和阶段不一致时状态为 `not_comparable`。
- 官方原件、审计披露、受许可原始数据和本地可复现实验优先；供应商营销声明只作候选。
- 低等级来源不能覆盖高等级来源；过期、撤回、合同漂移或哈希损坏会自动降级结论。
- 每项对标必须保留无动作选项、替代方案、敏感性、失效条件和复审日。

### 4. 九域全链路

1. 技术架构：交付频率、变更失败率、恢复、单位验证成本、可替换性。
2. AI/Agent：冻结评测通过率、unsupported rate、工具成功、跨作用域泄漏、成本、延迟、可重放性。
3. 产品体验：激活、首个价值时间、核心任务成功、留存、证据覆盖和可退出性。
4. 全球获客与销售：可验证账户覆盖、ICP 命中、触达依据、有效回复、会议、合格商机、成交、回款、CAC/payback。
5. 电商运营与供应链：需求、精确身份匹配、完整成本、库存周转、履约、退货、内容和刊登质量。
6. 财务与资本：现金底线、runway、现金转换周期、最大损失、downside CM3、回收期和资本效率。
7. 组织与执行：Owner 覆盖、决策延迟、阻断时间、自动化可回读率和人工接管。
8. 安全与韧性：跨租户泄漏、完整性、恢复、供应链证明、unknown outcome 和 kill switch。
9. 数据、合规与治理：新鲜度、Lineage、许可、PII 最小化、合同一致性和审计完成度。

### 5. 精准外贸获客资料

新增 `global_trade_lead_intelligence` 来源包，覆盖零售平台、B2B 平台、中国供应链站点、独立站、海关数据和专业网络。平台名称先做 alias 归一，再按来源适配器隔离。

对象严格分开：

- `seller_account`：平台卖家或店铺主体；
- `supplier_entity`：可供货主体；
- `prospect_account`：满足 ICP 的企业候选；
- `buyer_signal`：带来源、时间窗和行为语义的采购意向信号；
- `verified_contact_point`：有明确公开/许可依据、用途和撤回状态的企业联系点；
- `qualified_opportunity`：只有 CRM 真实互动、需求、预算/权限/时机证据后才成立。

店铺、商品、公司存在不等于买家意向；公开页面联系人不等于可无限触达。采集必须绑定官方 API/导出、许可数据集或平台条款允许的公开业务信息，记录 robots/terms/速率/字段许可和司法辖区。登录、验证码、Cookie、个人档案、私信和平台写入不由本模块获得权限。

### 6. 资本配置

`CapitalAllocationProposal` 只比较经营实验和企业能力投入，不执行证券投资。每个提案必须冻结：现金底线、runway、预算上限、最大损失、时间盒、downside/base/upside、回收期、Evidence 覆盖、依赖、Owner、主指标、护栏、停止条件、回滚和 no_action。

不得用不可交换维度的等权总分替代判断。先淘汰违反 Evidence、权限、合规、现金底线、最大损失和回滚要求的选项，再按长期风险调整价值、TCO、时间价值、运营适配和替换成本选择 `best_feasible_for_kjds`。

### 7. Constraint Breaker

“破甲”固化为本地受控的约束攻击评测：提示注入、间接文档/网页注入、跨租户/会话、幂等漂移、工具链投毒、数据污染、预算逃逸、unknown outcome 重放、权限声明伪造和指标游戏化。目标只允许 KJDS 本地合成 fixture 或显式准入的隔离测试端点；每次运行产生语料哈希、环境版本、攻击参数、安全输出、发现、修复和回归 Evidence。

候选工具首批为 Inspect AI、PyRIT 和 OpenAI Evals/Graders 适配器。PyRIT 必须固定版本并覆盖 breaking changes 与数据集模板注入回归；Inspect 必须设置 token/message/time/cost limits 和工具审批。它们只做评测适配器，不成为 KJDS 事实、权限或运行时控制面。

### 8. 演进与冲突边界

- BAS-173 负责 GraphRAG/检索基准；Kernel 只消费其可验证引用。
- BAS-177 负责 Skill/模型 Shadow、晋级、回滚；本 ADR 不允许自改代码、权限或策略。
- BAS-178 负责社媒采集/活动 grant/回读；本 ADR 不获得账号或发布权。
- BAS-180–189 负责媒体 Agent；本 ADR 只比较能力、成本和结果。
- BAS-190–196 负责合成 Demo；Demo 数据永不进入真实 Top1 当前值。
- COM-002 负责 Token、计费、收退款、SLA/DPA 与商业交付。

## 实施序列

- BAS-197：本 ADR、来源 intake 和 benchmark 合同。
- BAS-198：PrimarySource Intake 与 Evidence 标准化。
- BAS-199：多域可比队列与 Top1 metric registry。
- BAS-200：GapGraph 和战略机会组合。
- BAS-201：实验与资本配置提案。
- BAS-202：Constraint Breaker 与技术采用 Gate。
- BAS-203：只读战略/资本驾驶舱。
- BAS-204：结果回写、时效降级和可验证进化。

## 验收后仍保持的事实

BAS-197 完成只证明合同冻结。真实订单、结算、银行到账、买家意向、成交、利润提升、模型准确率、领先者排名和资本回报继续为 `UNKNOWN`，直到相应一手 Evidence、独立复核和结果回写存在。
