# KJDS 主规格：AI 原生跨境电商经营控制平面

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-MASTER-SPEC-001 |
| status | Active |
| version | 8.66 |
| last_reviewed | 2026-08-02 |
| owner | 项目负责人（待确认） |
| approver | 经营负责人 |
| source_of_truth | 本文件定义需求、产品、架构、数据和验收边界；运行事实以代码、迁移、测试和证据账为准 |
| live_task_status | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) |

> 本文件是 KJDS 的工程主规格，把需求、产品、系统架构、前后端模式、API 合同、核心业务流程、治理、安全、运行和阶段门集中在一个文件中。现有专题文档保留为证据和操作附件；新增工作必须先在本文件中找到对应的需求、Gate、Owner 和验收标准。

## 0. 设计原则与文档规则

### 0.1 三层设计模型

```text
第一层：Architecture
系统边界、核心模块、数据流、外部依赖、安全、性能、部署和灾备

第二层：Patterns & Abstractions
前后端分层、领域对象、服务接口、状态机、数据合同、权限模型和可替换点

第三层：File-level Code
路由、服务、模型、组件、脚本、迁移、测试和配置的具体实现
```

第三层不能反过来决定前两层。若一个功能只能通过在 `api.py`、页面组件或脚本中临时拼接完成，先补充第二层抽象；若抽象会改变边界或外部依赖，先补充第一层 ADR/Gate Review。

### 0.2 事实优先级

1. Ozon 后台/API/结算、银行、供应商、样品、合规原件等一手经营证据。
2. 代码、Alembic 迁移、自动化测试、G-1/Gate 报告。
3. 本文件及专题附件。
4. 研究母稿、行业文章、模型输出只能作为候选，不能直接晋升为事实。

### 0.3 不可逾越的边界

- 只读观察、模型建议和候选声明不能直接改价、投放、采购、上架、付款或平台配置。
- 正式事实必须有原件、SHA-256、来源、时间和血缘；候选声明必须独立复核，并保留 `formal_fact_promoted=false`。
- 高风险生产写入必须经过决策合同、角色授权、预算、审批、幂等执行、回读、审计和回滚。
- 未提供真实 SKU、Ozon 权限和一手经营文件前，不得宣称经营闭环已打通。

### 0.4 工作状态

`NOT_STARTED`、`IN_PROGRESS`、`BLOCKED`、`NEEDS_REVIEW`、`DONE` 是唯一工作状态。`DONE` 必须具备 Owner、验收结果和证据链接；外部输入阻塞不得用继续开发掩盖。

---

## 1. 产品定义与范围

### 1.1 产品定位

KJDS 是“确定性经营内核 + 证据优先数据层 + 受控 Agent 外层”的跨境电商经营控制平面。第一阶段服务一个经营主体、一个 Ozon 店铺和三个真实候选 SKU；成熟后再复制到更多平台和国家。

它不是万能聊天机器人、ERP、BI 或自动上架脚本的简单集合。核心价值是把每次经营动作变成可验证的事实、决策、实验和责任记录，再用这些记录改善下一次决策。

### 1.2 用户与角色

| 用户 | 主要任务 | 界面 | 角色 |
|---|---|---|---|
| 经营负责人 | 目标、预算、重大风险、Gate 放行 | 经营驾驶舱、审批、异常中心 | `admin`/`approver` |
| 商品负责人 | SKU、Passport、Listing、质量 | SKU Episode、证据包 | `operator` |
| 合规/复核人 | 证据、候选声明、Passport、实验复核 | Review Queue、Evidence Ledger | `reviewer`/`compliance` |
| 财务负责人 | 费用、FX、对账、现金 | Finance、Reconciliation、Cash | `reviewer`/`compliance` |
| 供应链负责人 | 报价、样品、包装、物流 | Sourcing、Procurement | `operator` |
| 只读 Worker | 按批准合同读取 Ozon | 无业务写界面 | `pilot_reader` |
| 执行 Worker | 执行批准的低风险命令 | 无事实写权限 | `executor` |
| 监控 Worker | 健康、回读、异常 | 无经营写权限 | `monitor` |

### 1.3 目标

- 统一商品身份、订单、库存、费用、结算、客户案例和证据对象。
- 让贡献利润、现金和风险使用同一套可复算口径。
- 以 Ozon 三 SKU 为最小真实闭环，先证据化再自动化。
- 让只读采集、实验、候选事实、策略发布和受控执行可追溯、可复盘、可回滚。
- 让模型、连接器和工作流引擎可替换，长期资产沉淀在数据、证据、实验和 Skill。

### 1.4 非目标（G7 前冻结）

- 多租户 SaaS、第二国家、第二平台、开放 Agent 市场。
- 自研基础大模型、通用向量库、通用 ERP/BI/工作流产品。
- 无账号授权的网页批量点击、绕过平台规则、付款和银行自动化。
- 未经真实订单、结算和银行到账验证的“自动盈利”承诺。

---

## 2. 需求规格（PRD）

### 2.1 业务需求

| ID | 需求 | 验收标准 | 优先级 |
|---|---|---|---|
| BR-001 | 三 SKU 经营闭环 | 每 SKU 有稳定 ID、Passport、报价、样品/物流/合规证据和 Gate Review | P0 |
| BR-002 | 真实利润与现金 | 订单—费用—结算—银行可对账；未知费用隔离；13 周现金可复算 | P0 |
| BR-003 | Ozon 只读证据 | 官方允许范围内读取商品/库存/价格，逐 run 产生响应哈希、证据和审计 | P0 |
| BR-004 | 候选事实桥接 | 成功 run 才能提声明；匹配 `state_sha256`；独立复核；不自动晋升正式事实 | P0 |
| BR-005 | 决策与实验 | 建议带假设、证据、主指标、预算、风险、停止条件、回滚和失效时间 | P1 |
| BR-006 | 受控自动化 | 仅通过策略、审批和执行链的低风险动作可以写入 | P1 |
| BR-007 | 持续情报 | 权威采集、去重、健康、证据门和候选记忆晋级可复现 | P1 |
| BR-008 | 韧性与可迁移 | 备份、重放、熔断、人工接管；模型/连接器/任务可替换 | P1 |
| BR-009 | 启动资料包合同 | 八份启动 CSV 的结构覆盖与人工证据录入前的内容完整度必须分别报告；其中候选清单固定三候选×五指标，Ozon API 身份盘点只保存脱敏引用、调用方、角色数、最后使用时间和处置决定，禁止保存密钥；严格预检在任一资料区仍缺值、证据引用、负责人、候选双来源或已核验素材时失败关闭；经营看板必须把本地完整度预检与系统 Evidence/Passport/事实账 readiness 明确分层；API 不读取或暴露私有 CSV；两层状态都不得自动导入、替代原始证据、晋升正式事实、批准 Gate 或触发上架 | P0 |
| BR-010 | Gate Review 可靠发布 | Gate Review 创建、提交和决定必须在同一数据库事务写入最小脱敏 Outbox 事件；事件写入失败时状态转换回滚 | P0 |
| BR-011 | Outbox 覆盖边界 | 每个直接管理 SQLAlchemy 事务的控制面模块必须登记为已覆盖、轮询合同、门前延期、仅内部状态或基础设施；新增/删除模块造成清单漂移时测试失败；清单不得把未实现能力表述为“全系统完成” | P0 |
| BR-012 | 私密启动资料工作区 | 提供一个默认位于 Git 忽略目录的模板副本；公开模板保持只读基线；重复准备只补充新增的缺失模板，已存在私密文件不得被静默覆盖；校验不晋升证据或正式事实 | P0 |
| BR-013 | SKU 图片素材证据入口 | 每次只接收一个真实原图和一份独立授权/权属文件；校验文件类型和内容签名后分别哈希固化、绑定 SKU/变体/图片角色并追加 Quality Passport 草稿；七类素材全部经人工批准进入最新 Passport 后，才可进入图片 Brief，上传本身不得触发生成 | P0 |
| BR-014 | 图片 QA 与 Listing 草稿交接 | 图片 QA 必须一次提交该内容类型的完整检查集，每项包含明确结论与人工判断依据，并由服务端记录审核身份和时间；任一项失败即退回。Ozon Listing 草稿只能引用同一 SKU 已人工批准且具有不可变产物证据的图片资产，创建草稿只产生待审批请求，不发布到平台 | P0 |
| BR-015 | Listing 审批快照 | `listing.publish` 审批必须绑定完整草稿的确定性 SHA-256，并向审批人展示草稿 ID、商品、供应商报价、利润场景、标题、类目、图片资产与产物证据；草稿内容改变时摘要必须改变。审批仍不等于平台执行，且申请人与批准人必须分离 | P0 |
| BR-016 | Listing 决定时复验 | 独立审批人批准 `listing.publish` 前，服务端必须重新读取草稿并计算摘要，与审批请求中的摘要进行常量时间比较；缺失或不一致时拒绝批准。审批账是决定状态的唯一事实源，不在 Listing 表复制第二份决定状态 | P0 |
| BR-017 | Web 独立审批身份 | 浏览器运营会话默认只能使用 `operator` 身份；批准、风险与紧急管理必须来自另一个已认证主体和独立服务端会话。API 密钥不得进入浏览器，不得通过前端角色切换或同一服务端密钥伪造双人审批 | P0 |
| BR-018 | 容器运行时资源一致性 | API 导入或启动依赖的仓库内机器真源必须显式进入生产镜像；构建上下文只对白名单资源开放；G-1 必须从生产镜像执行 API 导入，防止本地工作区成功而容器启动失败 | P0 |
| BR-019 | Web 交付镜像一致性 | Web 必须使用 Next.js 原生 standalone 形成非 root 生产镜像；Compose 只在 API healthy 后启动 Web；G-1 必须真实启动该镜像并检查 KJDS 首页，不能用本地 dev server 代替交付验证 | P0 |
| BR-020 | Ozon 单 SKU 只读目标绑定 | `ozon.product.read` 必须使用固定版本的产品信息与属性只读合同；两个响应都必须恰好返回一个与请求 `offer_id` 匹配的对象。空结果、多个对象、缺失目标字段或目标不一致均失败关闭；失败摘要不得包含原始 offer、商品正文或凭证；成功摘要必须记录合同版本、两个记录数、状态摘要和不可变原始响应 Evidence | P0 |
| BR-021 | Ozon Pilot 执行前离线预检 | 单 SKU Pilot 的默认操作入口必须只做本地配置预检，不连接控制平面或 Ozon；预检验证唯一目标、幂等键、官方 HTTPS 主机、固定属性端点、所需凭证存在且专用 Worker Key 不与平台 Key、通用 API Key 或执行 Worker Key复用。控制平面在本机或 Compose 内网之外必须使用 HTTPS。输出只允许合同版本、计数、布尔检查与目标/ Pilot 哈希；任何密钥、原始 ID、URL 查询或商品正文不得输出。只有显式 `Execute` 才能在预检通过后启动隔离 Worker | P0 |
| BR-022 | Ozon Worker 执行意图与执行时复验 | Worker CLI 必须且只能显式选择 `preflight` 或 `execute`；未选择、同时选择或依赖旧默认行为必须在构造网络客户端前失败。`execute` 必须在当前进程、当前环境中重新执行连接环境校验；首次单 SKU Pilot 还须完整重跑 BR-021 预检，防止包装脚本绕过或预检后配置变化 | P0 |
| BR-023 | Ozon 只读运行一次性执行授权 | 控制面创建新的只读 run 时才可返回 `execution_granted=true`；同一幂等键命中任何既有 `started/completed/expired` run 时只能返回历史结果并明确 `execution_granted=false`。Worker 必须在任何 Ozon 请求之前检查该字段；未获得执行权时不得访问平台、重复采集证据或重复完成 run。该安全边界采用 at-most-once：控制面响应丢失时不自动重授执行权，需等待租约回收并使用新的人工可追踪幂等键重试 | P0 |
| BR-024 | Ozon 响应检查点与无平台重放恢复 | Worker 一旦拿到成功的 Ozon 原始响应，必须先用同一 run、同一响应哈希和脱敏完成载荷写入不可变 Evidence，并把 run 持久化为 `response_captured`，再执行完成确认。检查点与完成确认必须幂等；控制面超时/5xx 可有界重试，但不得重新调用 Ozon。`response_captured` 租约到期时只能从已存 Evidence 和完成载荷恢复为 `completed`，不得误记为 `RUN_LEASE_EXPIRED`；内容哈希、字节数、合同摘要或 Worker 身份不一致必须失败关闭 | P0 |
| BR-025 | Ozon 响应 Evidence 完整性恢复 | `response_captured` 完成或租约恢复前，控制面必须重新读取原始 Blob、逐字节计算 SHA-256，并复验唯一血缘、来源、run 引用、类型、等级、元数据和字节数；不得只相信 Evidence 记录中的声明哈希。缺失、重复、损坏或不匹配时 run 必须保持 `response_captured`、返回机器可读的非敏感阻塞码且不得产生完成摘要；批量回收必须隔离坏 run 并继续恢复其他健康 run | P0 |
| BR-026 | Evidence 持续完整性巡检与事件升级 | 控制平面必须能够在不读取外部平台、不修改原证据的前提下，对 Evidence 记录和 Blob 做有界批量巡检；巡检必须覆盖 Blob 缺失、实际 SHA-256 不符和实际字节数不符。异常必须先形成新的可验证巡检报告，再以稳定指纹幂等创建运维事件；重复巡检不得制造重复事件。巡检只负责发现、固证和升级，不自动修复、删除、覆盖证据或释放 Kill Switch | P0 |
| BR-027 | 24×7 Evidence 巡检接入 | 既有本机健康循环必须使用独立 `monitor` 身份分页调用 Evidence 完整性巡检，且不得复用浏览器、operator、approver、executor 或 Ozon 平台凭证。控制平面被声明为必需时，专用身份缺失、API/巡检失败、分页未完成或发现任一异常都必须产生脱敏非零退出；输出只保留范围计数、扫描报告 ID 和 Incident 数，不输出原始正文、实际哈希或凭证。该接入只复用现有 Task/OpenClaw 失败信号，不等同于托管 24×7 或外部通知送达证明 | P0 |
| BR-028 | Evidence 健康循环调度部署 | 调度管理入口默认不得修改系统状态；只有显式安装模式且健康脚本 `ControlPlaneOnly` 预检返回 0 时，才可用 Windows Task Scheduler 注册固定脚本、固定工作目录、无密钥命令行和有界执行时限。安装预检必须使用调度任务实际可见的持久配置源；v1 只支持 Git 忽略的项目 `.env`，不得把当前终端的临时环境误判为任务配置。审计必须复验任务启用状态、Action/参数、重复间隔、最近结果和原生 Task Scheduler 完成历史；至少连续三次结果 0 才可声明调度已验收。缺任务、缺历史、配置/预检失败或定义漂移均保持非零与脱敏输出 | P0 |
| BR-029 | 候选观测不可变证据 | 五类候选观测必须绑定可逐字节复验的 Evidence；来源、时效和商品边界不一致时失败关闭 | P0 |
| BR-030 | 候选研究原子入口 | 五类固定指标必须完整、无重复并在同一事务写入；来源由 Evidence 派生，重试幂等且不得自动建商品或上架 | P0 |
| BR-031 | 候选到三报价人工交接 | 仅通过复验的 RU/Ozon 候选可由人工确认建立 candidate Product；同 SKU 冲突失败关闭 | P0 |
| BR-032 | 三报价前置门不可绕过 | 三报价写入前必须存在内部候选交接事件和有效 `candidate_basis` 血缘；缺失或损坏时不得捕获报价内容 | P0 |
| BR-033 | 候选测量合同与报价筛选策略 | 五类候选指标必须使用服务端固定的版本化测量合同，连续指标必须记录观察窗口和样本量；需求强度、竞争缺口和预期 30 日退货率必须按可信度加权后实际参与报价筛选。Ozon RU v1 仅在需求百分位 ≥50、供需缺口百分位 ≥50、预期退货率 ≤30%、已确认供货、无合规红线、双独立来源且全部原件通过复验时允许请求三报价。阈值只分配低风险询价精力，不批准采购、Listing 或平台写入；合同不匹配或样本不足必须补证，阈值未达必须淘汰。 | P0 |
| BR-034 | 三候选离线证据包合同 | 私密启动资料包必须为恰好三个稳定候选各提供五类固定指标，锁定 RU/OZON、测量窗口、样本量、原件引用、来源族、带时区观察时间、Owner 与状态；缺候选、缺指标、重复指标、指标越界、非有限值、测量合同不符或单一来源必须失败关闭。公开模板只收集占位结构，本地预检不得读取引用、自动导入、晋升事实或解除 Gate。 | P0 |
| BR-035 | 动作作用域需求证据与候选资格门 | 保留唯一任务 `SKU-000` 和一个服务端授权入口，Readiness 在该任务内分别计算 `research` 与 `real_execution`。至少 28 天、原件可逐字节复验、带来源/抓取时间/哈希且经不同身份接受的 Ozon 官方类目分析、趋势、“卖什么”、搜索词、竞品/类目比较，以及明确脱敏的历史样本或固定测试数据，可满足 `research`；研究产物必须固化 `decision_scope=research`、`fact_status=simulation`、`cost_status=estimate`、`external_side_effect_allowed=false`。`real_execution` 只由已接受的 Ozon Data 正式报告，或至少两个彼此独立的 Ozon 官方分析入口组合满足；测试数据、第三方数据、公开示例、空模板、页面读数或仅接受法律条款均不能满足。`SKU-001` 及下游研究 readiness 只统计同时具备候选交接事件、有效 `candidate_basis` 和当前有效研究依据的 Product。 | P0 |
| BR-036 | 单任务双作用域独立复核 | `SKU-000` 原件上传只能形成待复核 Evidence，不得直接满足任一作用域；必须由不同身份读取原件，核对来源、至少 28 天窗口、完整性、用途范围及是否为公开示例，并以不可变复核 Evidence 接受或拒绝。上传者不得自审；同一复核者不得改写结论；任一有效拒绝、原件损坏或缺少有效接受均失败关闭。同一原件可按来源资质参与一个或两个作用域，但不得复制任务、Evidence 或复核体系。 | P0 |
| BR-037 | 统一动作授权与执行时复验 | 所有研究动作、内部正式事实晋升及外部副作用统一调用 `authorize_action(action, subject_id, actor, occurred_at)`；不得实现 `check_research_gate`、`check_real_gate` 或各模块自有 Gate。候选分析、模拟利润、报价收集、图片/视频生成、Listing 草稿、审批演练及财务原件上传/预检/暂存/复核可在相应研究或完整性门下继续；样品付款、正式采购、Listing 发布、广告、补货、`actual` 晋升与自动入账必须在请求时和 Worker 实际执行时复验 `real_execution`。研究记录不得原地改标为真实事实；晋升必须创建新的不可变决定与血缘。ComfyUI 继续作为既有受控媒体执行器，生成产物必须回到 KJDS 的 Blob/Evidence/Lineage/QA/Approval；n8n 只可调用受控 API 做定时、通知和催办，不拥有 Gate、事实或平台写权限。 | P0 |
| BR-038 | 逐项成本权威来源与跨境巴士只读边界 | 采购、头程、仓储、国际物流、尾程、平台佣金、广告、退款、税费和汇率必须按 `docs/project/registries/cost_authority_sources.json` 分别绑定实际承担方的一手原件；跨境巴士只可作为其实际经办订单、仓库与物流费用及计费重量的来源，不得替代 Ozon 结算、税单或银行成交汇率。公开规则和报价只能形成 scenario；公开字段先按原样固化，未经真实样本和财务批准不得猜测字段语义；未知费用必须隔离复核。 | P0 |
| BR-039 | 全成本利润与证据门禁 | 利润场景必须显式计算采购、国内头程、国际物流、包装、仓储、关税、税费、尾程、平台佣金、广告、退款/退货、汇兑、资金占用、售后和损耗；已知成本不得藏入 `other_cost`。每个成本项（包括明确为零或不适用的项）必须绑定可复验 Evidence。系统可以保存证据不完整的测算草稿，但采购评审、样品下单和 Listing 草稿必须在决策时与执行时同时拒绝成本证据不完整或 `other_cost` 非零的场景。 | P0 |
| BR-040 | Ozon 官方财务只读证据采集 | `ozon.finance.read` 只能调用官方 Seller API `POST /v3/finance/transaction/list`；查询必须是带时区、起止有序且不超过 31 天的明确期间，分页从 1 开始且每页不超过 1000。运行前必须通过只读 Pilot、凭证隔离和显式执行门；原始响应必须先作为不可变 Evidence 完整固化并复验哈希，控制面只保存合同版本、查询哈希、页码和条数等脱敏摘要。v1 不得根据字段名自动映射平台佣金、物流、退款或其他会计科目，必须等待真实账户样本和财务批准的费用代码映射。 | P0 |
| BR-041 | Ozon 财务报表独立复核门 | Ozon 导入端点必须为每份时段型账户导出接收明确的查询起止日期；费用、计提、退货和结算导出上传后只能进入暂存区，交接必须将该期间固化在原件 Evidence，日期缺失、无效、倒置或超过 31 天时不得建立导入。相同文件重复提交时，声明期间必须与原 Evidence 完全一致；旧导入缺少期间、Evidence 缺失或期间冲突时不得静默复用。待复核状态必须提供只读聚合核验包：原文件名、哈希、字节数、上传者、捕获时间，导入类型/状态/解析行数/映射字段，Evidence、哈希、血缘和行号连续性，以及逐币种精确合计、生效日期范围；计提还需列出原件实际出现的组/类型及其逐币种合计。核验包不得暴露商品、订单、客户等原始行，也不得自动接受、分类或入账。晋升正式事实前，必须由非上传者以不可变 Evidence 确认原件来自真实账户、报告期间与该结构化交接期间一致、不是公开样例且导出完整；聚合核验包只协助比对，不能自行证明原件真实性。任一有效拒绝、缺少接受、原件哈希/导入类型/期间/血缘不一致或复核来源被通用 Evidence 接口伪造时必须失败关闭。订单导入仍不进入财务复核门，但保留其查询期间作为来源上下文；复核不批准费用字段的会计映射。 | P0 |
| BR-042 | Ozon 财务导入 Web 交接 | Web 上传费用、计提、退货或结算文件后必须显示 `import_id`、导入类型、暂存结果和复核状态，并明确提示“未入账”；提交复核结论前必须展示 BR-041 的只读聚合核验包，并对任一完整性异常显著告警。上传人与复核人必须使用不同身份会话。只有 Reviewer/Compliance/Admin 身份可提交四项来源检查和接受/拒绝结论；页面不得因复核通过而自动晋升事实、批准会计映射或启动对账。订单文件继续按普通导入结果展示，不进入该财务复核界面。 | P0 |
| BR-043 | Ozon 费用代码映射批准门 | `ozon_fee` 导入通过独立来源复核后，只能由非上传者通过该导入的专用流程批准实际出现过的原始费用代码；服务端固定 `provider=ozon`，将批准结论、会计类型、符号规则、生效区间、理由、原始报告与导入血缘固化为不可变 Evidence，再复用现有版本化映射。通用费用映射接口必须拒绝 Ozon，避免绕过真实报告与双人控制。正式事实晋升前，每个无错误暂存费用行在其 `effective_at` 上都必须命中一条具备有效批准证据的映射；缺失、过期或证据失配时整体失败关闭。批准映射不得自动晋升事实、生成财务分录或启动对账。 | P0 |
| BR-044 | Ozon 原始导入只读预检 | 正式上传前必须用同一解析合同对原文件做无状态预检，返回文件哈希、识别类型、行数、已识别字段和缺失必需字段，但不得写数据库、Evidence、事实或费用映射。Web 只能在预检 `ready=true` 后调用既有正式导入；预检失败必须保留原文件不变并显示缺失字段，不得要求运营人员手工改列名或另存一份伪原件。正式导入仍须重新校验文件大小、期间、哈希和解析合同，不能信任浏览器提交的预检结论。 | P0 |
| BR-045 | 候选证据权威等级门 | C/D 级第三方选品、ERP、计算器和探索资料允许固化并保留为辅助知识，但不得单独满足候选指标或进入来源族计数。需求、竞争、供货和退货指标至少需要 A/B 级原件；合规红线必须由 A 级官方原件支撑。等级不足必须返回独立阻塞原因，不得伪装成坏文件、不得删除探索证据，也不得进入三报价、采购或 Listing。 | P0 |
| BR-046 | 候选证据独立权威复核 | 候选原件上传时声明的 A/B/C/D 等级只作为录入信息，不得直接成为候选放行等级。需求、竞争、供货、合规和退货五类指标必须分别由非上传者的 Reviewer/Compliance/Admin 核对原件真实性与完整性、来源范围和 A/B 权威依据，并以不可变、指标级 Evidence 记录接受或拒绝；接受必须三项检查全部通过。决定时必须复验原件哈希、上传/复核身份、指标、批准等级、检查项、理由和血缘；任一有效拒绝、缺少接受、原件损坏或复核证明失配均失败关闭。复核不得改写原件自报等级，不得通过通用 Evidence 或 Lineage 接口伪造，也不得复核复核证明本身。 | P0 |
| BR-047 | 竞品模式借鉴与受控批量工作台 | 系统可以借鉴第三方跨境 SaaS 的成本模板、趋势/关键词/竞品监控、采集箱、批量编辑、订单异常队列和库存物流协同，但所有外部观察先进入带来源、捕获时间、原始字段和 Evidence 的研究收集箱。场景测算必须显示估算/实际、公式版本和逐项来源；批量动作必须先生成差异预览、风险分组、预算/数量上限和可回滚计划，经过既有审批后才交给受限执行器。任何第三方 ERP/API 不得拥有 KJDS Canonical Product、利润、证据、审批或审计唯一真源，也不得绕过独立复核、Passport、CM3 和 Listing 门。 | P1 |
| BR-048 | 第三方研究信号专用收件箱 | 外部选品、关键词、竞品、计算器或 ERP 导出必须经 `/v1/market/research-signals` 进入不可变 Evidence，保存提供方、稳定记录 ID、原始 URL、观察/捕获时间、原始标量字段、许可状态和候选关联；精确重试去重、内容变化追加历史，一条信号最多关联 20 个稳定候选。通用 Evidence/Lineage 入口不得伪造该角色。收件箱输出必须明确 `auxiliary_only`，不得自动创建 Product、采购或 Listing；只有既有独立指标级权威复核才能让原件在适用指标上成为 A/B 依据。v1 手工导出优先，任何 Open API 适配必须先通过协议、许可、身份、字段、速率、撤销和真实样本对账。 | P0 |
| BR-049 | 版本化全成本场景模板 | Ozon/RU 场景必须绑定服务端模板 `ozon-ru-full-cost-v1` 和公式版本；采购、国内物流、头程、包装、仓储、关税、税费、尾程、佣金、广告、退款退货、汇兑、资金占用、售后和损耗逐项标记 `estimate/actual/unknown` 并回到 Evidence。`unknown`、缺证据或非零未分类成本均阻断采购与 Listing；解释视图必须返回逐项金额/状态/来源、CM3、保本价、安全边际和售价 ±10% 敏感性。模板只生成决策场景，不自动定价；旧场景必须无迁移可读。 | P0 |
| BR-050 | 三候选组合决策视图 | 经营工作台必须只聚合通过候选交接、候选原件复验及已接受需求报告门的 Product；每个候选使用当前每家供应商的最新报价及其最新利润场景，显示三报价、Passport、完整正 CM3、最佳供应商、未知成本和明确阻断原因，并按“可进入人工选择优先、CM3 其次、SKU 稳定排序”形成只读组合。历史或未合格 Product、旧报价上的过期正利润不得误入组合或满足 readiness；视图不得自动选品、采购、定价、上架或写平台。 | P0 |
| BR-051 | 证据支撑的经营异常工作台 | 经营工作台必须把当前 Gate 阻断与已有事故、受限执行命令和观察窗口放在同一异常中心，但不得混淆两类语义：Gate 阻断按 Gate、来源对象、当前/目标数量、责任角色和下一动作展示，不伪造 SLA 或发生时间；运行事项继续使用既有风险等级、Owner、截止时间和升级账。每项 Gate 阻断必须回到服务端 readiness 事实及稳定 requirement ID，页面不得自行重算放行规则。该工作台只负责解释、排序和人工导航，不自动补证、关闭事故、释放熔断、批准采购、修改价格、上架或写平台。 | P0 |
| BR-052 | Ozon 官方计提报表原样暂存 | 官方 `Отчет по начислениям` XLSX 必须按独立 `ozon_accrual` 合同识别，跳过只含报告期间的标题行，保留服务组、计提类型、原始计提 ID、SKU、金额和计提日期；金额列明确标注 `руб.` 时只能派生 `RUB`，不得从数值或账号地区猜币种。缺失官方计提 ID 的总账调整行使用“文件哈希 + 原始行序号”生成仅供内部幂等的来源行 ID，原始空值仍保留在 payload。日期型单元格只作为 UTC 会计日边界规范化，不能宣称为平台事件时刻。预检和导入必须覆盖全部数据行并可复算报表总额；该合同只能进入既有财务原件独立复核门，不得套用费用映射、自动生成 Finance Entry、自动分类收入/成本或解除利润未知项。 | P0 |
| BR-053 | Ozon 计提分类与防重复确认 | `ozon_accrual` 通过独立来源复核后，系统只能展示该原件真实出现的“服务组 + 计提类型”，由非上传者逐对批准收入、折扣、平台费用、物流、补偿或待复核类别、预期符号和生效区间。展示与核验必须逐币种汇总，禁止跨币种相加；正、负、零实际符号必须可见。预期正数只覆盖金额大于零的行，预期负数只覆盖金额小于零的行，零值或混合符号必须显式选择允许正负；批准时与每次解析状态时均须复验，旧的失配批准不得满足完整分类。批准必须形成不可变、版本化 Evidence，并同时绑定原报告和 import；虚构组合、未覆盖报告行、符号不符、上传者自批、证据或血缘失配均失败关闭。全部行命中分类后只允许晋升为平台侧控制事实，不得自动生成 Finance Entry、替代订单收入、复用费用代码映射或直接写入利润；实际 CM3 仍需订单、费用、结算、银行与 FX 各自一手证据完成多腿对账。 | P0 |
| BR-059 | Ozon 财务报告日期版本路由 | 不得删除或覆盖旧商品报告解析历史。声明报告结束日期早于 `2026-08-03` 时允许旧商品报告合同；开始日期不早于该日时使用应计费用报告合同；跨越切换日、内容与声明类型矛盾或无法识别时进入差异队列而非猜测。两种格式都必须记录报告类型、合同版本和路由依据，先进入不可变原始暂存，再经过费用分类、差异处理、独立复核才可晋升统一内部费用控制事实；历史行不因新合同上线而重写。该能力属于 `OZN-002`、`FIN-001`、`BAS-058`，不作为 `SKU-000` 授权条件。 | P0 |
| BR-054 | 最佳方案选择合同 | 所有重大产品、架构、数据源、供应商、自动化和经营方案必须通过版本化 `best_solution` 决策合同：先以安全、证据、权限、合规、预算、验收、回滚和事实真源硬约束淘汰不可行方案，再比较有证据支撑的长期风险调整价值、总拥有成本、最大损失、可逆性、价值实现时间、运维适配、维护和替换成本。可行时必须包含不行动/延期方案；禁止把最新、最复杂、功能最多或代码最少自动视为最佳，也禁止对不可公度维度生成等权伪总分。分析必须按“每个方案 × 每条硬约束”完整保存布尔结论与理由，并为每个方案保存证据等级及六项经营评估；被选方案任一硬约束失败、缺少任一方案评估、非选方案缺淘汰理由、缺敏感因素/失效条件/复审时间/审批要求，均失败关闭。接受结论的独立复核必须至少记录一个反方解释；合同、分析和正式决定始终无经营执行权。 | P0 |
| BR-055 | 开源 ERP / Commerce 内核准入 | KJDS 不自研通用采购、库存、供应商、应收应付和总账，也不把未经验证的 ERP 变成第二事实库。当前 Ozon 竖切仍由 KJDS 控制面持有 Evidence、Canonical Product、CM3、决策、实验、审批和审计；ERPNext 只作为首选隔离侧车 PoC，Odoo Community/Dolibarr 为备选，Medusa/Saleor/Vendure 延期到自有商城立项。任何 ERP 晋升必须证明同一可写对象唯一 Owner、稳定外部 ID、幂等同步、原件血缘、最小权限、Webhook 验签、双向对账、备份恢复和完整卸载。合同阶段只允许 `poc_dry_run` 离线投影：目标单据固定草稿、禁止远程写和自动提交；金额必须是十进制字符串，跨币种必须绑定正汇率、带时区生效时间和汇率 Evidence；同一幂等键出现不同 payload 必须失败关闭，对账差额不得自动过账或吞入“其他”。 | P1 |
| BR-056 | 财务三方对账双人控制与原件独立 | 订单应收、平台结算和银行到账齐备后，`matched` 仍必须同时满足两项治理不变量：执行对账的复核人不得是任一相关原件上传者、Finance Entry 创建者、费用映射批准者或实际采用 FX 的创建者；银行到账原件与平台侧订单、费用、退货或结算原件的 Blob SHA-256 必须不同，即使同一文件被换来源或重新存证也不得冒充独立资金腿。任一自审依赖返回 `blocked_self_review`，任一原件哈希冲突返回 `blocked_evidence_independence`；快照必须列出依赖类型/ID或冲突哈希及两侧 Evidence ID。缺 FX、未知费用、待复核和缺资金腿仍按原有更早优先级阻断。该规则不自动批准分录、不解析银行文件、不创建会计凭证。 | P0 |
| BR-057 | 实际成本权威证明与执行前复验 | 利润场景中的 `actual` 不能由调用方自行声明。每项实际成本必须引用完整性通过的原件，并由非上传者针对同一原件哈希、精确成本项和允许的实际权威类型固化不可变证明；复核必须确认原件真实性、成本范围、计费/责任主体以及金额—币种—期间匹配，任一拒绝优先阻断。`estimate` 可继续使用报价、规则或预算依据，但不得显示为已实现利润。利润场景创建、候选 readiness、采购评审、样品订单和 Listing 草稿生成时都必须重新验证场景全部原件以及每项 `actual` 的当前证明；坏原件、证明失配、自审或缺证明均失败关闭。该能力复用 Evidence/Lineage 和现有 JSONB，不新建成本账、自动改写状态、自动入账或把估算利润冒充到账利润。 | P0 |
| BR-058 | 实际成本权威复核工作台 | Web 必须为非技术 Reviewer/Compliance/Admin 提供 BR-057 的人工复核入口：从服务端只读目录选择精确成本项及其唯一允许的实际权威类型，选择现有 Evidence，查看当前 pending/accepted/rejected 状态，并提交接受或拒绝、四项核验和理由。成本项、显示名和允许权威类型只能由后端单一合同下发，页面不得复制一份可漂移的权威映射；Operator 只可查状态，上传者仍不得自审。页面必须明确复核不会自动改写场景、入账、采购、定价或上架；任一失败保留原状态并显示后端原因。该能力复用既有财务复核表单、身份会话和 Evidence 列表，不新增数据库、依赖、状态管理框架或通用规则引擎。 | P0 |
| BR-060 | 风险分级动作政策与单次执行许可 | `research/real_execution` 继续表示事实和经营作用域；L0-L4 只表示动作风险，不创建第二套 Gate。每个受控动作必须由唯一机器注册表声明风险等级、作用域、副作用类别、审批/MFA、幂等、请求时与执行时复验、回读、回滚、许可和爆炸半径要求。L3/L4 必须使用与精确动作、主体、操作者、策略/决定摘要、端点及额度绑定的短期单次许可；许可缺失、过期、已消费、参数或额度不匹配均失败关闭。第一阶段复用 `LimitedExecutionCommand` 的一次性命令、租约、回执和回滚合同，不新建平行执行系统；运行时 `authorize_action()` 尚未接入全部写路径前，任何新增真实写动作保持关闭。 | P0 |
| BR-061 | 决策包投影与能力经济晋升 | 重要决定必须能从既有 Decision Contract、Analysis、Review、Resolution、Evidence、Approval、Passport、Profit 和版本快照确定性投影为不可变 `DecisionPacket`，回答当时事实、备选方案、理由、模型/工作流/Skill 版本、预期价值、最大损失、审批、失效条件和决定摘要；第一阶段不得为该投影新建表。每个受控执行计划必须在申请时把支撑各 Readiness requirement 的精确 Evidence ID、当时阻断码及规范化快照哈希冻结进现有 Approval payload 和计划请求摘要，并把这些 Evidence 自动并入计划血缘；后续只允许另行显示当前 Readiness，不得用今天的新证据改写当时依据，冻结证据失效时旧计划必须失败关闭。新模型、Prompt、ComfyUI workflow 或 Skill 先作为 challenger 进入既有 Shadow/Observation 链，与 champion 比较正确性、安全性、经济性、第二/第三 SKU 可迁移性和可撤销性。晋升必须引用既有 Capability Economics 的真实增量价值、避免损失、模型/计算、人工复核、事故和维护成本；技术成功不得自动增加经营权限。 | P0 |
| BR-062 | 组合风险、事实成熟度与抗失控顺序 | 经营事实区分 `forecast`（预测）、`commitment`（已承诺未结算）和 `actual`（权威原件已发生），但第一阶段复用既有场景、现金计划、采购/广告承诺和财务事实，不建立通用新账。L3/L4 放行最终必须同时满足单动作限制与 SKU、类目、店铺、法人、币种及 13 周最低现金的组合风险预算；在真实先锋 SKU 形成承诺和到账样本前，只实现保守硬上限与 Base/Downside/Severe 影子场景，不建设 ML 数字孪生或资本优化器。灰度、分层 Kill Switch、失效、异常预算、灾备和退出条件复用现有 Policy Shadow、Security、Incident、Evidence 与恢复链扩展，不建设第二套控制面。 | P0 |
| BR-063 | 外部合同回放与漂移门 | Ozon、ComfyUI 和财务文件适配必须以版本化、脱敏、无凭证的固定样本在 CI 中回放；每个样本声明外部系统、合同版本、预期结果和 SHA-256，样本缺失、哈希变化或预期行为漂移均失败。第一阶段只复用现有客户端、导入器、MockTransport 和测试运行器，不建设生产回放服务或通用录制框架。回放至少覆盖成功响应、结构漂移和失败关闭；限流、超时、写入结果不确定、幂等重放与回读不一致继续由现有专项测试验证，获得真实脱敏响应后再替换对应合成样本。生产流量、密钥、个人信息和原始商户数据禁止写入仓库。 | P0 |
| BR-064 | Champion/Challenger 影子对照账 | 既有 Policy Shadow 的每个可用于阶段结果或激活的 Evaluation 必须冻结一个由不同身份产生的 `champion` 或 `human` 基线结果、其 Evidence、基线/挑战者摘要哈希、精确差异路径和是否完全一致；基线与业务上下文使用相同的敏感字段、大小和不可变幂等限制。零暴露批次可以先采集无基线评估用于诊断，但缺少完整独立对照的批次不得记录可晋升阶段结果，也不得申请有限激活；激活时必须重新验证全部 Evaluation Evidence。第一阶段把对照投影保存在现有 Evaluation `result_json`，不新增表、服务、依赖或第二套 Shadow；真实增量价值、人工成本和利润仍由 Observation Window 与 Capability Economics 在有限执行后记录，影子一致率不得冒充经营收益。 | P0 |
| BR-065 | 唯一经营工作台与 Agent 只读简报 | KJDS 必须把既有 Gate readiness、候选组合、运行异常队列和已存证建议通过单一版本化只读接口投影为经营简报；页面不得自行重算 Gate、优先级或 Agent 责任。每项简报必须保留来源类型/ID、下一动作、责任 Agent、风险和人工要求；Gate 阻断不得伪造截止时间或 SLA，运行异常继续保留原 SLA。Agent 只允许解释、排序和提出下一步，固定 `automatic_execution=false`、`platform_write_allowed=false`，不得直接写 Repository、创建 Product/采购/Listing、调用外部平台或把第三方工具信号晋升为正式事实。荔枝、毛子 ERP 等第三方产品只作为功能模式与 C/D 级辅助信号参考；无兼容许可证的二进制、扩展或压缩源码不得复制进仓库。 | P0 |
| BR-066 | 现有 Ozon SKU 组合增长规划 | 现有商品增长必须通过一个服务端深模块，把版本化全成本场景与不超过七天的店铺/同行 Evidence 快照计算为价格四分位、目标 CM3 底价、最大 ACOS/CPC、内容七角色、合规/库存/评价/转化门禁和组合优先级。1688 展示价不得冒充实际落地成本；同行少于三条、成本未通过独立权威复核、无真实转化率或任一安全门失败时不得解锁广告。输出只作可解释建议，禁止自动改价、上架、采购或花费广告预算；真实动作继续使用既有 Approval、一次性许可、回读、止损和补偿合同。 | P0 |
| BR-067 | 统一经营前台与任务型导航 | Web 必须把登录、经营总览、数据与 Evidence、候选研究、商品/Listing、1688 与供应链、现有 Ozon SKU 增长、内容素材、财务利润、实验策略、审批执行和系统运行收敛到同一认证平台。导航按经营任务切换工作区，首页只聚合服务端简报、真实计数、阻断、下一动作和能力入口；不得硬编码店铺动态事实、在浏览器重算 Gate/利润/权限，或把推荐按钮包装成平台写入。每个工作区必须显示其作用域、事实成熟度和副作用边界，并保留 loading、empty、error、forbidden、success 状态。现有增长规划必须有非技术表单入口，使用有 Evidence 的同行快照和已存在利润场景，结果显式保持 `recommendation_only`，改价、广告和发布继续进入既有审批与一次性执行链。登录继续遵守 BR-017 与 ADR-0012：浏览器不接触 API key，不提供角色切换，审批身份需要独立会话和 AAL2。 | P0 |
| BR-070 | 供应商报价独立权威门 | 公开展示价、聊天与上传文件先进入 B 级线索；只有非上传者逐项确认供应商、冻结规格、金额币种 MOQ、有效期和交付条件后，才形成 A 级复核凭证。公开展示价永不晋升，三份不同供应商的当前已接受原件才允许生成 SupplierOffer 与 CM3；报价在付款前仍为 estimate | P0 |
| BR-071 | 已有 Listing 受控建档 | 经完整性复验的最新 Ozon Catalog 条目可由人工确认绑定为 active Canonical Product；绑定必须锁定店铺、offer ID、item hash 与源 Evidence，且不得伪造候选交接或计入 SKU-001。绑定只开放 Passport、确认报价、CM3 与增长诊断入口，不授予媒体权利或任何平台写权限 | P0 |
| BR-072 | 供应商 RFQ 冻结包与回复交接 | 已绑定 Listing 只有在当前 Catalog Evidence、精确 item hash、Product 身份和人工确认同时通过时，才可生成店铺作用域的不可变 RFQ 草稿。RFQ 必须区分“目录观察”与“买方要求”，冻结数量阶梯、逐项规格、包装、文件、目的地、回复期限和供应商回复清单，并提供可复制正文；它不得自动联系供应商、冒充询价已发送、供应商已回复或正式报价。后续报价原件可引用 RFQ Evidence 形成血缘，但仍须通过 BR-070 的独立原件复核 | P0 |
| BR-073 | RFQ 发送证明与供应商回复归因 | “已复制”不得晋升为“已发送”。每次人工供应商外联必须引用不可变 RFQ，冻结供应商主体、平台、店铺/联系人定位、会话或消息编号、发送时间、完整 RFQ 文本哈希和原始截图/导出；上传者只能形成 B 级待核验发送证明。只有不同身份逐项确认平台原件、供应商身份、RFQ 全文、时间与会话一致后，才形成 A 级发送证明复核。发送证明不等于送达、回复、报价或采购；后续报价引用发送证明时必须复验同一 Product、RFQ 与供应商，并保留完整 lineage | P0 |
| BR-068 | 店铺事实快照与多模式增长工作区 | 现有 Ozon 店铺事实必须先以不可变、幂等快照进入服务端，再由同一深模块按 SKU 读取最新有效观测并生成全店组合计划；快照必须记录来源、操作者、采集时间、观测时间、Evidence、内容/库存/订单/评价/转化和同行价摘要哈希，同一来源与幂等键出现不同载荷必须失败关闭。店群、铺货、精品/精细化和品牌运营只能是同一事实与治理内核上的工作区策略：店群按店铺隔离、额度和组合风险汇总，铺货强调批量去重、上新门禁和淘汰，精细化强调 CM3、内容、转化和有上限实验，品牌运营强调资产一致性与团队审批；任何模式都不得降低 Evidence、成本权威、权限、审批、回读或止损要求。第一阶段只保存经 Operator 明确确认的 Ozon/API、Ozon 导出或人工核验快照并生成建议，不因“批量”或“店群”自动写平台。 | P0 |
| BR-069 | 商业数据中枢与商品目录同步 | 购买平台、Ozon、竞品/行情、物流与利润数据必须先保留不可变原始 Evidence，再由来源专用解析适配器进入统一读模型。Ozon 商品同步必须只接受已完成且逐字节复验的 `ozon-product-read-v1` 原始响应，按店铺范围不可变、幂等地保存 offer、SKU、名称、价格、库存、状态、尺寸重量、属性、图片、视频和文档引用；合同漂移、响应哈希、目标或 Evidence 血缘不一致均失败关闭。外部媒体默认标记为未核权引用，不得自动下载、生成、发布或冒充自有素材；目录导入不得自动创建 Canonical Product、采购、改价、上架或投放。1688/采购必须区分展示价、阶梯价、MOQ、已确认报价与实际落地成本；竞品和行业动态只作为带来源、时间、许可、样本和置信度的研究信号；物流必须版本化线路、计费重量、体积重规则、币种、时效、有效期和费用分项，并仅通过 BR-038/BR-039 的逐项权威门进入 CM3。SaaS 前必须补齐 tenant/store 行级隔离、连接凭证托管、来源条款和删除/导出合同。 | P0 |
| BR-074 | 经营流转分析快照与可视化驾驶舱 | 服务端必须用一个版本化只读投影聚合 Gate readiness、Ozon 商品目录、现有 SKU 增长快照、RFQ/发送证明、样品采购、受控执行计划和财务正式事实，返回稳定 `stage/funnel/coverage/focal_listing` 合同与快照哈希。每个阶段必须保留来源 requirement 或对象 ID、当前/目标、状态、下一动作和工作区导航；缺失历史序列、竞品价格、真实 CM3、订单或结算时必须显示 `no_data/blocked`，不得用演示数、插值或静态图冒充经营事实。Web 必须用真实商品图引用、价格带、库存、媒体构成、经营漏斗和证据覆盖图形成可下钻 HTML 驾驶舱；外部图片继续标记未核权引用，不下载、不取得媒体权利。AI 只能按服务端阻断给出下一步和模式建议；店群、铺货、精细化、品牌和新手模式共用同一事实、权限、审批、回读和止损内核。该快照不新建分析事实库、不改变任何 Gate、不获得 Ozon/供应商写权限。 | P0 |
| BR-075 | EvidenceOps Copilot 目标到证据任务合同 | 提供独立认证产品入口，把一个明确经营目标编译成版本化、带哈希的只读任务合同。服务端深模块只能组合 BR-065 经营简报和 BR-074 经营分析快照，必须区分已验证事实、未知项、推断意图、任务、验证条件和禁止动作；每个任务保留来源、责任 Agent、工作区、当前/目标和人工要求。目标文本不得成为事实或执行许可，客户端不得自行重算任务优先级、Gate 或风险。首版不调用外部模型、不保存会话、不自动选品、联系供应商、采购、改价、发布、投放、付款或写平台；未来模型只能作为可替换规划适配器，其输出仍须通过同一 Evidence、评测、影子、审批和回读链。独立入口共享 KJDS 身份和业务真源，不建立第二数据库、第二权限面或通用 Agent 市场。 | P0 |
| BR-076 | 俄罗斯优先的全球跨境能力运行图谱 | KJDS 必须用一个服务端版本化、机器可读的合同同时表达三层结构：①“点”逐项拆解 LinkFox 公开原子功能、KJDS 经营原子能力和控制原子能力，每点声明业务对象、操作类型、输入输出、Evidence、责任人、失败队列、回读、KPI、状态与不可越权边界；②“线”把点按对象状态变化串成从趋势、选品、供应商、CM3、商品档案、内容、Listing、审批发布、广告、库存订单、履约退货、结算对账到实验复盘的端到端价值流，并明确入口/出口门、事件、异常和人工接管；③“面”把跨店铺、商品、内容、执行、供应利润、售后、Agent/Skill 和全球扩展组织为经营控制面，明确维度、真源、决策、预警和写权限。LinkFox 只作为 C 级公开营销工作流参考，页面观察不得冒充已验证 API、Ozon 接入、模型效果或经营事实；“同功能覆盖”表示产品/合同设计覆盖，不得把 `ready`、`research_only` 或 `gated` 展示为已运行。Web 必须从认证只读接口呈现可搜索、可筛选、可下钻的 HTML/SVG 点—线—面图谱与逐节点合同，客户端不得重算状态、路径或编造能力。图谱第一市场为 Russia/Ozon，并把平台、国家、语言、税务、合规、物流、支付和模型提供方隔离为适配器；扩展 Amazon、Wildberries、Yandex Market、AliExpress、TikTok Shop、Shopify、eBay、Shopee、Lazada、Temu、SHEIN、Etsy 等平台时继续复用同一 Canonical Product、Evidence、Passport、CM3、Approval、Execution 和 Reconciliation 内核。任何生成式模型、Skill、Agent、浏览器或第三方 API 只有通过许可、数据合同、最小权限、评测、影子、成本、审计、回滚和真实样本对账后才能晋级，技术新颖性不构成准入理由。 | P0 |
| BR-077 | 点线面到真实业务工作区穿透 | 图谱中的每个原子点、每条价值流和每个经营控制面必须解析到独立、可分享、可回退的认证工作区路由，不能跳回图谱自身或只落到无上下文菜单锚点。服务端 `OperatingWorkspace` 深模块以 `kind + item_id + store_ref` 为唯一外部接口，组合 BR-076 图谱合同与 BR-074 真实经营分析，返回节点上下文、阶段顺序、运行状态、事实、Evidence 引用、数据缺口、下一动作、责任人、异常、回读、相关价值流和现有领域工作区导航；客户端不得重新映射阶段或编造业务状态。14 条价值流必须逐条具有完整阶段穿透，8 个经营面必须可下钻到关联价值流和核心点，143 个点必须可回到所属线和真实领域工作区。缺少真实订单、结算、供应商、CM3、媒体权利或平台权限时必须显示 `no_data/blocked/contract_only`，不得用 `ready/implemented` 冒充正在运行。工作区首版只读，不新增数据库、外部写权限或自动执行；任何高风险动作继续回到既有 Evidence、Approval、Permit、Readback、Kill Switch 和 Compensation 链。 | P0 |
| BR-078 | SKU/订单/日期实际利润账 | 服务端必须只读组合正式 FactRecord、Finance Entry、FX、Evidence、逐项成本权威证明及 Supplier Offer/Profit Scenario/Listing/Product 绑定，以 `store_ref + product/SKU + order + accounting_date + currency` 输出可复算利润账。只允许明确自然键、source fact 或人工绑定归集；无法映射进入 `unallocated/blocked`，禁止按销售额、数量或比例猜分摊。场景 CM3、应计贡献、结算贡献、到账贡献必须分别报告；证据不完整时不得显示实际利润。侵蚀桥覆盖采购、物流、仓储/库龄、佣金、广告、退货退款、折扣、税费、FX、损耗和未分摊，使用 Decimal、显式币种和 FX 日期并严格守恒。 | P0 |
| BR-079 | 数据异常到统一运营任务 | 服务端版本化指标注册表首批覆盖利润覆盖率、负 CM3、退货率突增、库龄/仓储侵蚀、广告上限、结算差异、内容 QA 失败和媒体执行失败，并固定基线、最小样本、严重度、冷却期、Owner 与 Evidence 条件。认证规范入口为 `GET /v1/operating-intelligence/metrics` 与 `POST /v1/operating-intelligence/anomaly-scans`；既有 `/v1/metrics` 与 `POST /v1/anomaly-scans` 作为同一服务端 endpoint 的兼容别名保留，客户端不得重算指标或扫描结果。异常以稳定指纹去重，只创建内部 OperatingTask 和不可变事件，投影进入既有 OperationsQueue，不建立第二队列或工作流引擎。状态为 `open → acknowledged → in_progress → resolved|dismissed`；解决/驳回必须理由与有效 Evidence。扫描不得触发任何平台、供应商、广告、采购、付款或媒体副作用。 | P0 |
| BR-080 | 证据化图片与视频运营工作台 | 复用 ContentAsset、Evidence、Lineage、QA 与 Approval 提供受控模板、批量任务、变体、成本、延迟、部分失败、幂等重试与 Delivery Manifest。ComfyUI 只运行固定准入工作流，未准入保持 blocked。视频首版不接外部生成 Provider，只使用已批准商品图、人工确认俄语脚本/字幕和有权利音频，经固定 FFmpeg 链生成 9:16/1:1/16:9 MP4、封面、字幕、关键帧、编码报告与 Manifest；PostgreSQL 租约和独立媒体 Worker 支持恢复，不引入 Redis/Kafka/Temporal。所有产物进入 Blob/Evidence 并记录输入哈希、模板/编码器版本、耗时和成本；只有 QA 全过后才可被 Listing 草稿引用。 | P0 |
| BR-081 | Marketplace Observation 与组合 Pilot | Ozon/1688 页面、卖家工具和插件导出必须通过来源专用只读 Adapter，以不可变 C 级 Evidence、稳定自然键、URL、观察时间、操作者、币种、价格语义、变体、规格与 SHA-256 进入统一 Marketplace Observation 读模型；不得复制 Cookie/localStorage/CSP 绕过、宽域权限或未经准入的内部端点。公开展示价、新人价、区间最低价和工具估价只可计算可解释 `observed_spread` 与版本化悲观/基准 `screening_contribution`，不得创建 Supplier Offer、十五项 CM3 或实际利润。服务端 `PortfolioPilotWorkspace.prepare()` 必须组合当前 Ozon Catalog、目标规格、最新观察、既有报价/利润/Listing readiness 和 OperatingTask，按规格匹配、悲观筛选贡献、来源质量、Evidence 覆盖、风险和稳定 fingerprint 排序；缺平台费、物流、退货、税费、FX、内容权利或精确规格时保持 `partial/blocked`，客户端不得重算或把候选冒充可发布。外部验证码/登录/联系人阻断只进入既有 OperatingTask/OperationsQueue；所有真实发布继续使用既有冻结计划、批次批准、一次性 Permit、Readback 与止损。 | P0 |
| BR-082 | 批量市场扫描、观察成本 Pilot 与内容工厂 | KJDS 必须在 BR-081 上提供一个小接口、深实现的批量经营模块族：`BatchMarketScanner` 只从带来源、时间、Evidence、置信度和明确价格语义的 Ozon/1688 观察读取需求、竞品、价格带、评价/销量代理、促销、季节、缺货、产业带、供应商密度、精确变体、MOQ、交期、包装重量体积和集运距离；缺失销量不得推算成销量。漏斗必须分别报告 `exact_identity_matched`、`checkout_cost_eligible` 与 `fully_costed_candidates`，不得因下单页或成本 Evidence 缺失而把已连接的同一精确身份误报为未匹配。`OpportunityScorer` 只对服务端精确身份匹配且可复核的 `observed_checkout_price` 计算十五项 baseline/downside 筛选 CM3、现金占用、周转和风险，观察成本不得晋升 Supplier Offer、actual 或正式 CM3。`StrategyClassifier` 只能输出淘汰、探索、受控铺货、精品精细化、套装、配件、真实属性变体或店群复制建议，70%/20%/10% 仅为资源政策目标；`VariantExpansionPlanner` 只有在真实父 SKU、真实属性及 24h/72h/7d 回读满足时才能提出裂变，禁止虚假属性、重复商品和类目污染。状态固定为 `observe→match→evaluate→content_ready→pilot→scale|stop→reconcile`，复用 OperatingTask/OperationsQueue、Owner、Evidence、预算和稳定 fingerprint。内容工厂只生成可追溯俄语文案/属性/卖点/详情结构和媒体 Brief；未取得权利、Passport 或媒体 QA 时 `content_ready=false`。任何候选只有 downside CM3>0、数据时效/身份/规格/可采购性/媒体权利/Passport、独立批准、一次性 Permit、Readback 与止损全部满足时才可进入 1–3 件小流量 Pilot；本模块不创建 Permit、不写 Ozon、不承诺盈利。首发采购模式固定为 `sale_triggered_jit`：真实 Ozon 出单前不得创建购物车、供应商订单或付款；只有有效 Evidence 支撑、解析到同一 Product/SKU、`store_ref` 与授权店铺一致且状态为 `awaiting_packaging` 的正式 `ozon_order` FactRecord，结合重新核验的当前库存、checkout 成本和悲观 CM3，才可形成内部 `eligible_for_procurement_review`，仍不得自动采购或付款。状态未知、取消、退货、跨店、坏 Evidence 或手工 Order 均不能触发。Web 必须以真实 HTML/SVG 显示全国供应分布、市场价格带、候选漏斗、策略、CM3/现金/风险、变体树、采购触发状态和 24h/72h/7d 回读，并报告实际观察数、精确身份匹配数、checkout 成本候选数、完整成本数、downside 正数、内容就绪数和 Pilot 数，缺数据明确 `no_data/blocked`。 | P0 |
| BR-083 | 利润款到 ERP Item 的证据化同步 | 服务端 `ProfitQualifiedErpSync` 只能从授权店铺的不可变 Batch Opportunity run/candidate 重新读取精确身份、十五项成本 Evidence、悲观 CM3 与守恒结果；不接受客户端自报利润。只有成本完整、悲观 CM3 大于冻结门槛且守恒为零的候选可生成 ERPNext `Item` 草稿与 PostgreSQL 幂等 outbox；Item 初始库存为 0，KJDS 继续拥有 Product/Evidence/利润真相。同步只允许最小权限 Item create/read，写后必须回读稳定外部 ID、`item_code`、`docstatus=0` 与 KJDS Product 引用；未配置连接器、坏 Evidence、跨店、同键异 payload 或回读差异全部失败关闭。该接口不创建采购单、收货、库存调整、付款、广告、Permit 或 Ozon 写入；真实出单后的采购仍遵守 BR-082 `sale_triggered_jit`。操作体验可参考批量 ERP 工具，但不得复制 Cookie、内部接口、客户端利润算法或宽权限。详见 ADR-0033。 | P0 |
| BR-084 | 可审计 tenant/entity/store 授权权威 | `Principal` 只提供认证 tenant/store 边界，禁止把 tenant 猜成 entity。主体权威只能由 append-only `grant|revoke` 事件在显式 `as_of` 下派生；事件冻结 tenant/entity/store/subject actor、accepted A 级 review Evidence ID/hash、独立记录人、理由、有效时间、幂等键和请求哈希。授权 Evidence 必须是认证 owner 创建的 B 级 source 与另一认证 reviewer 创建的 A 级 review，通过 immutable source ID/hash Lineage 连接；owner/reviewer/recorder/subject 四方分离，上传者自报 `reviewed_by` 不构成权威。自授权、自审、跨店授权、弱或损坏 Evidence、同 actor/store 多个活动主体及幂等载荷漂移均失败关闭。Truth/Governance 动态读取该 authority/hash；缺失或撤销时保持 `entity_ref=null`。任意经营 Evidence 还必须通过 `ScopedEvidenceAuthority` 证明属于当前 tenant/entity/store：新记录可带不可变直接作用域，旧记录只能由独立 A 级绑定 Evidence 按目标 ID/hash 补作用域，不得改写原件；缺失为 unbound/partial，跨作用域、错 hash、自审或损坏绑定均 blocked。Approval/Permit/Readback/Compensation 只能由 `GovernanceScopeAuthority` 通过完整 scoped Evidence 与精确 plan→command→window 父子关系投影；禁止递归搜索任意 JSON 中的 `store_ref` 作为授权，孤儿、跨店或未绑定记录不得影响治理状态。只读研究可继续，candidate scoring/Pilot 必须要求作用域 ready。授权管理是内部治理写，不开放任何平台、供应商、采购、付款或广告写权限。详见 ADR-0034、ADR-0054。 | P0 |
| BR-085 | Commerce OS 与可审计 Agent Team | KJDS 必须把无忧易售、妙手、芒果店长、Maozi ERP、荔枝 ERP/助手以及 LinkFox 的商品素材/生图/视频/Agent 工作流作为产品与运营流程基准，原生建设并拥有市场采集、商品/变体 PIM、供应、十五项利润、商品库、AI 内容媒体、Listing、订单售后 OMS、采购、库存/WMS、物流履约、广告促销、结算到账、BI、异常任务、团队权限和审计能力族；这些工具不是 KJDS 的运行依赖、数据源或同步目标，不得把 C/D 级模式登记或本地静态样本表述成已覆盖。唯一 `CommerceOperatingSystem` 深模块组合现有事实权威，经营状态固定为 `observe→identity→qualify→item_draft→content→listing_approval→publish→order→procurement_review→fulfill→settle→reconcile→learn`，每级返回服务端事实、readiness、阻断、Owner、SLA、下一工作区和稳定哈希。AI 内容工厂只从三类 Passport、已核权真实素材和类目 schema 生成批量图片/视频草稿，记录输入哈希、模板/模型/编码器版本、成本、延迟、部分失败、幂等重试、Lineage、QA、Delivery Manifest，并以转化和结算后 CM3 验证 A/B；竞品只作结构观察，不能复制标题/图片。Adapter seam 只用于 Ozon、1688 允许的数据路径、物流商、仓库、支付/银行等真正外部系统；Canonical Product、Evidence、三本利润账、审批与审计始终由 KJDS 拥有。十二责任 Agent 只能从权威快照生成内部 artifact、差异、任务或建议，不得直接写仓库、自批、自发 Permit、绕过验证码/条款或自动采购付款；任何外部写继续要求独立批准、一次性 Permit、Readback、Kill Switch 与 Compensation。首个切片交付认证 `/v1/commerce-os/workspace` 与 `/commerce-os`，动态展示 KJDS 相对业务基准的原生覆盖差距、状态机、媒体工厂和 Agent handoff，不用静态“功能数量”冒充完成度。非差异化能力按许可证、版本、真相源冲突、总成本和可回滚性复用成熟开源组件；不得以堆叠 ERP/commerce/Agent 框架制造第二套经营真相。详见 ADR-0035、ADR-0036 和 `evidence/20260728_BAS_107_COMMERCE_OS_AGENT_TEAM.md`。 | P0 |
| BR-086 | tenant/entity/store 经营事实隔离 | 任何 Profit、Order、Fact、Finance、OperatingTask、Observation、Inventory 或媒体事实不得因调用方传入 `store_ref` 就被重新标记到该店铺。运行 API 必须先验证 Principal 店铺权限和 append-only entity grant，再由深模块通过完整 scoped Evidence 或显式不可变资源绑定投影；旧全局表只可作为受控 raw authority，不能直接对外。`ScopedProfitLedgerAuthority` 首先收口利润账：无 entity 时不调用 raw ledger；有 entity 时逐行复验订单、成本、场景、结算和银行 Evidence，excluded 只报数量/原因不泄露金额或标识，重新计算 Decimal 覆盖率、侵蚀守恒和稳定 hash。显式 `as_of` 必须排除之后记录、未来/过期 Evidence 并可确定性重放。路由缺 store 授权返回 403，缺 scope 返回 no_data；禁止 SKU/订单文本猜归属、按比例分摊或 default-store 回填。后续任务、库存、媒体与数据库 RLS 必须复用同一语义，不能各造一套。详见 ADR-0037。 | P0 |
| BR-087 | OperatingTask 与统一队列作用域权威 | 每个新 AnomalyScan/OperatingTask 必须冻结认证 `tenant_ref`、正式 `entity_ref`、授权 `store_ref` 与 ScopeGrant authority hash；指标维度只能作为从属字段。任务列表、事件读写、队列与升级扫描均按完整元组授权，禁止把 task ID 当权限。`OperationsQueueService` 在 API scoped mode 下只组合该作用域任务和 `GovernanceScopeAuthority` 已验证的 command/readback；无作用域 legacy scan/task/incident/escalation 只保留审计，不进入运行投影，不默认回填。缺主体返回显式 no_data/空队列且零写入；跨店 403，跨主体资源不可见。迁移 0057 的原生 scan/escalation 作用域列允许 legacy 全空但拒绝部分元组；升级事件必须冻结同一 authority，外部写恒为 false。PostgreSQL RLS 仍是后续独立 Gate，不能用本切片冒充数据库全隔离。详见 ADR-0037。 | P0 |
| BR-088 | 组合读模型失败关闭 | OperatingWorkbench、OperatingAnalytics、OperatingWorkspace 与 EvidenceOps 不是事实权威；认证路由必须显式传递 Principal、当前 entity grant、store 与 `as_of`，不得调用 legacy 无参数全局 loader。Workbench scoped mode 只消费 scoped OperationsQueue；尚无作用域的 Gate readiness/Automation 明确排除。Analytics 在 catalog/growth/RFQ/procurement/finance/execution/media 尚未逐一作用域化前返回结构完整的 no_data/partial 图表合同和 source gaps，不得把全局计数重标为请求店铺。缺主体时不读取任何这些原始源，跨店 403；旧内部接口只保留兼容测试/迁移用途。下游 composer 只有所有子源均采用同一 scope 才能声称已隔离。详见 ADR-0037。 | P0 |
| BR-089 | Marketplace Observation 作用域读权威与 RLS 包络 | 认证 Observation 列表/分页必须先校验 Principal 店铺并在同一 `as_of` 解析唯一 entity grant；无主体时不得调用 raw workspace。查询必须在数据库去重前限定精确 store 与 cutoff，禁止把 legacy `external` 并入任一租户。只有完整性/current 通过且经独立 direct scope 或 A 级 target ID/hash binding 的 Evidence 才可返回明细；其余只报排除数量/原因，不泄露商品、供应商、价格、链接或 Evidence ID。响应使用统一版本化 envelope，包含 scope/Evidence authority hash、Owner/SLA/next、稳定 hash 与 `external_write_allowed=false`；Web 不再把未绑定数组称为可用事实。现有 `ENABLE RLS` 不等于数据库隔离；后续 forward-only RLS 必须先建立完整或全空原生 tuple、非 owner/non-BYPASSRLS 应用角色、deny-by-default policy、pool reset/跨请求测试和 FORCE 验收，禁止默认回填。详见 [ADR-0038](../adr/ADR-0038-postgresql-rls-and-scoped-read-model-envelope.md) 与 [BAS-113 Evidence](evidence/20260728_BAS_113_SCOPED_MARKETPLACE_OBSERVATION.md)。 | P0 |
| BR-090 | Marketplace Catalog 作用域事实权威 | 认证目录读取必须先验证 Principal 店铺并在同一 `as_of` 解析唯一 entity grant；缺主体时不得读取 raw Catalog。数据库和内存适配器均须在 offer 最新事实去重之前应用 exact store、snapshot imported time 与 item observed time，并只投影 cutoff 前已存在的 canonical binding，禁止未来快照或未来绑定污染历史决策。每个返回商品必须具有 current/intact 且经 independent direct scope 或 A 级 target ID/hash binding 的目录原件 Evidence；未绑定、跨作用域或损坏行仅报计数/原因，不泄露 offer、价格、媒体或 Evidence ID。导入 Evidence、绑定既有 Listing 和从目录创建 RFQ 前必须重复执行相同作用域预检；经营分析/Commerce OS 只能消费 `ScopedMarketplaceCatalogAuthority`，不得回退到全局目录。该切片仍为只读治理和内部目录写，`candidate_scoring/content/Pilot/external_write` 均保持关闭；PostgreSQL 原生 tenant/entity tuple、非 owner role、policy 与 FORCE RLS 继续按 ADR-0038 独立验收。详见 [BAS-114 Evidence](evidence/20260728_BAS_114_SCOPED_MARKETPLACE_CATALOG.md)。 | P0 |
| BR-091 | Batch Opportunity 与经济测算作用域权威 | 认证批量机会扫描只能由 `ScopedBatchOpportunityAuthority` 组合同一 tenant/entity/store/as_of 的 scoped Observation、scoped Catalog、current/intact scoped component Evidence 与冻结 FX；缺 entity 时零子源读取，legacy `external` 不得重标到租户。非 CNY 币种必须选择 effective/recorded 均不晚于 cutoff 的 FX 行并把其 Evidence 纳入 authority hash，scoped 评估禁止回退全局 FX。run 冻结 grant、Observation、Catalog、economics 与 Evidence hash；同 scope 幂等 payload/authority 漂移冲突，跨 tenant 可独立使用同 key。成功仅为 `ready_with_constraints` 内部研究：可生成 exact identity+variant cohort、风险调整供应商比较与十五项 downside CM3 screen，但 Supplier Offer、actual cost、formal CM3、Approval、Permit、Pilot、采购/付款/广告/Ozon 写全部为 false。迁移 0058 保留 legacy 全空 tuple、拒绝部分 scope，提供 scoped partial unique/index；旧行不回填。详见 [ADR-0039](../adr/ADR-0039-scoped-batch-opportunity-and-economics.md)。 | P0 |
| BR-092 | Product、Passport、内容与 Listing 审批计划作用域权威 | 认证 Product/Passport/ContentAsset 读取及其内部草稿写必须先校验 Principal、当前 entity grant、精确 store 与 `as_of`，再由 `ScopedProductContentAuthority` 读取原始仓库；调用方传入 Product/Asset ID、SKU 或 JSON 内 store 不构成授权。新 Product 冻结完整 tenant/entity/store/grant/as-of tuple；legacy Product 只可由同 scope 的 current/intact Catalog canonical binding 派生，禁止猜回填。三类 Passport、素材权利、内容来源/产物/QA、Supplier Offer 与十五项利润 Evidence 必须逐项通过 `ScopedEvidenceAuthority`。Scoped Batch 的内容阶段只消费冻结 Product/content projection，不得回退全局 Passport/ContentAsset 查询。Listing `approval plan` 是确定性内部预检 artifact，不是 Approval/Permit；只有同 scope Product、已批准 Passport/图片 QA、完整正 CM3 场景和 Listing payload 全部匹配时才可创建冻结 scope 的 ListingDraft 与既有独立 `listing.publish` Approval 请求。发布仍须独立执行 Approval、一次性 Permit、Readback、Kill Switch 与 Compensation；BAS-116 的所有外部写为 false。详见 [ADR-0040](../adr/ADR-0040-scoped-product-content-and-listing-plan.md)。 | P0 |
| BR-093 | 原生情报采集与来源适配器权威 | 所有认证市场/供应情报采集必须在读取载荷前解析唯一 tenant/entity/store grant，并由版本化 `IntelligenceSourceAdapterRegistry` 唯一匹配 source profile、marketplace、来源级别上限、语义权威、原件要求及采集政策。新 Observation 冻结完整 scope+grant+as-of 与 adapter/version/contract hash；迁移保留 legacy 全空行，不猜回填。数据库查询须在 current-fact fingerprint 去重前过滤 native tenant/entity/store，防止另一租户较新行压掉本租户事实。`seller_tool_export` 在没有 provider-specific 许可证、原始 Evidence 与 parser contract 时保持 `contract_only`；公开 Ozon/1688 观察不晋升销量、Supplier Offer、actual cost 或正式利润，来源等级不升级业务语义。Cookie/localStorage、内部 API、验证码/限流绕过和个人数据扩收均禁止；受限源返回 no_data。Commerce OS 与认证适配器接口显示服务端状态/hash/gaps，客户端不重算；所有 Ozon、供应商、采购、付款、价格、库存和广告写为 false。详见 [ADR-0041](../adr/ADR-0041-native-intelligence-ingestion-and-source-adapters.md)。 | P0 |
| BR-094 | 范围化 Market Radar 与 exact identity/variant 候选归一化 | Market Radar 必须复用 scoped Observation、Catalog 和 Batch Opportunity 的同一真相内核，在读取前冻结 tenant/entity/store/as-of、timezone、display currency、source grade、freshness、target purchase quantity 与扫描边界。服务端按 canonical exact product identity + exact variant 聚合 seller/listing cohort，分离 own Listing、external competitor 与 supplier option；分别报告 observed listings、unique exact identities、unique sellers/suppliers、unresolved、checkout-comparable 与按币种 p25/p50/p75，禁止把 listing 数当 SKU、跨币种混算、评论/页面信号冒充销量或公开 1688 价冒充 Offer/actual cost。目标采购量来自请求/政策，100 件阶梯价不得筛选 3 件首 Pilot。缺主体、坏 Evidence、来源等级/时效不符或截断必须 no_data/partial/blocked 并给 Owner/SLA/next；客户端只投影服务端合同，所有外部写 false。详见 [ADR-0042](../adr/ADR-0042-scoped-market-radar-and-candidate-normalization.md)。 | P0 |
| BR-095 | 原生范围化 Ozon Seller API Catalog 接入 | Ozon Catalog Evidence import 必须在持久化前解析当前 tenant/entity/store grant、独立 scoped Evidence authority 与当期 `ozon-seller-api-product-read` adapter contract，并将 grant/Evidence/adapter hash 连同 as-of、grade 与 semantic authority 纳入 Catalog snapshot hash。新 Catalog snapshot 使用 complete-or-empty native tuple；legacy 行全空保留且不猜回填。数据库查询在 latest-offer 选择前过滤 native tenant/entity/store，跨租户较新行不得压掉本租户事实；同作用域 idempotency 冲突 fail-closed。只接受官方两响应 bundle、原件/正文 hash、路径与 offer identity 一致；缺主体、坏/跨域 Evidence、非 implemented adapter 或合同漂移零写入。导入不发 Ozon 网络请求、不自动绑定 Product、不升级媒体权利、不创建 Offer/库存/Listing/Approval/Permit，所有外部写 false。详见 [ADR-0043](../adr/ADR-0043-native-scoped-ozon-catalog-ingestion.md) 与 [BAS-119 Evidence](evidence/20260728_BAS_119_NATIVE_SCOPED_OZON_CATALOG.md)。 | P0 |
| BR-096 | Ozon 只读 run 到 Catalog 的可恢复 handoff | 复用 `OzonReadOnlyWorker`、`PilotRunService`、scoped Evidence、adapter registry 与 Marketplace Catalog，新增轻量 native-only handoff ledger。只允许 completed+succeeded 的 `ozon.product.read` 且唯一 raw response Evidence；服务端冻结 tenant/entity/store/grant/Evidence/adapter/request hash 后进入 prepared，再以 handoff 派生幂等键导入 Catalog 并记录 snapshot ID/hash。中断可恢复，并发收敛；同 key 漂移冲突。缺主体、未绑定/坏 Evidence、finance/失败 run 或合同漂移不得创建 Catalog snapshot。列表/详情 SQL 先按 scope 过滤，匿名 401、越权 403。handoff 不读取 Ozon、不绑定 Product、不产生 Offer/actual/Listing/Approval/Permit 或任何外部写。详见 [ADR-0044](../adr/ADR-0044-ozon-read-run-catalog-handoff.md)；[工程证据](evidence/20260728_BAS_120_OZON_READ_RUN_CATALOG_HANDOFF.md)。 | P0 |
| BR-097 | Ozon 只读 Pilot/Run 原生作用域权威 | 新建 Pilot 必须由认证 Principal、current entity grant、exact store 与 independently scoped Evidence 共同冻结 tenant/entity/store/grant/Evidence authority/as-of；legacy Pilot 全空保留但不得从 tenant API 推断或返回。Pilot/attestation/review/activate/run start/checkpoint/finalize/list/get/usage 先按授权 scope 解析，run 通过其 Pilot FK 在 SQL 中 join-filter；知道 pilot/run ID 不授予访问权。原始 worker 仍只执行已实现的 product/finance read，且无 Listing/采购/付款/广告写权限。迁移拆分 legacy/native 幂等并保持既有 Pilot/Run/Evidence 哈希；详见 [ADR-0045](../adr/ADR-0045-native-scoped-ozon-read-pilots.md)；[工程证据](evidence/20260728_BAS_121_NATIVE_SCOPED_READ_PILOTS.md)。 | P0 |
| BR-098 | Ozon 只读 Claim 原生作用域与复核权威 | `ReadOnlyClaim` 只是成功 Run 的 Evidence-bound 可复核解释，不是正式 Product/库存/价格事实或执行批准。新 Claim 必须从 scoped Run 与 independently scoped current Run Evidence 冻结 tenant/entity/store/grant/Evidence authority/as-of；legacy 全空保留且 tenant API 不推断。propose/list/get/review 统一经 `ScopedReadOnlyClaimAuthority`，Claim→Run→Pilot 在 SQL 中同 scope join-filter，review 重验 current grant、Run/Pilot、Evidence binding 与独立复核人。0064 拆 legacy/native 幂等；accepted 仍 `formal_fact_promoted=false`、`external_write_allowed=false`，且不得被 legacy global execution path 用作发布 before-state。详见 [ADR-0046](../adr/ADR-0046-native-scoped-read-only-claims.md)；[工程证据](evidence/20260728_BAS_122_NATIVE_SCOPED_READ_ONLY_CLAIMS.md)。 | P0 |
| BR-099 | Ozon 官方导入 staging 原生作用域 | 新 Ozon CSV/XLSX import 在解析/落库前必须由认证 Principal、current entity grant、exact store 与原始 grade-A 文件 Evidence 冻结 tenant/entity/store/grant/source hash/as-of；legacy import 全空保留且 tenant API 不推断。相同文件在不同 tenant 独立，同 scope 幂等，grant/Evidence 漂移冲突；detail 与 finance-control status 先 SQL scope-filter。BAS-123 仅建立 staging，原始上传者不冒充独立 Evidence review，`formal_fact_promotion_allowed=false`；正式 Fact、SKU→Product 和 accounting promotion 等待 BAS-124 的同作用域权威。详见 [ADR-0047](../adr/ADR-0047-native-scoped-ozon-import-staging.md) 与 [BAS-123 Evidence](project/evidence/20260728_BAS_123_NATIVE_SCOPED_OZON_IMPORT_STAGING.md)。 | P0 |
| BR-100 | 外部观测 Agent Harness 与七类 Graph | Agent 状态、目标 TODO 与 Project/Requirements/Engineering/Runtime/Evidence/Commerce/Authority 七类 Graph 必须由服务端 canonical node/edge 和 append-only 外部 verifier observation 投影，不得由模型自报或静态图冒充。每条 Observation 冻结 source/scope/observed_at/freshness/verifier version/input hash/result hash/authority/Evidence 或 artifact；上游 hash、环境或 verifier 变化后下游为 stale。TODO 只有其注册 Verifier 的 fresh success 可置 passed；inferred edge 不得满足 Gate、建立 Fact 或授权外部动作。所有读 API 认证并按 tenant、可选 entity/store 隔离；首个真实竖切贯通 BAS-123 requirement→ADR→code/test→0065 real DB→image/container→API→desktop/390 browser→Evidence→Plan。状态栏只显示 changed/failed/blocked/stale/next-critical，drilldown 返回精确不可变观测；无数据、错误、禁止和通过必须区分。详见 [ADR-0048](../adr/ADR-0048-agent-harness-and-canonical-graph.md) 与 [BAS-125 Evidence](project/evidence/20260728_BAS_125_AGENT_HARNESS_GRAPH.md)。 | P0 |
| BR-101 | 正式 Fact 与 PromotionRun 原生作用域 | 新正式 Fact/PromotionRun 必须冻结 tenant/entity/store/current grant/source Evidence hash/as-of，并只从 BAS-123 native scoped ImportJob 晋升；legacy Fact/Run 全空保留且 tenant API 不推断。晋升时重新复验原始 Evidence 的精确独立 scope binding、来源复核和财务类型既有 review/mapping/classification；SKU 只能映射到同 tenant/entity/store/grant/as-of 的唯一 Product，裸 SKU、global Product、歧义或缺失映射失败关闭。同 scope payload 幂等、跨 tenant 独立；list/detail/promotion 认证并 SQL scope-filter，匿名401、越权403、缺 entity/bad Evidence/review/mapping 422。ReadOnly Claim 不得作为 Fact promotion 来源；晋升无外部写、Approval 或 Permit。详见 [ADR-0049](../adr/ADR-0049-native-scoped-formal-fact-promotion.md) 与 [BAS-124 Evidence](evidence/20260728_BAS_124_NATIVE_SCOPED_FORMAL_FACTS.md)。 | P0 |
| BR-102 | 动态范围化 M0→M4 Verifier | M0→M4 状态必须由一个纯、版本化的 `OperatingStageVerifier` 同时复验认证 Commerce OS 的 current tenant/entity/store 投影、13 段服务端 stage 完成态、正式 Fact/真实利润闭环声明、只读控制包络和真实 PostgreSQL 支持计数；`ready_for_internal_action`、模型文本、静态 Evidence 或单表存在均不得置 `passed`。M0 缺 current grant 与真实候选时为 `no_data`；其余未满足为 `blocked`；合同漂移、缺/重复 stage、非法计数或任何外部写开关为 `failed`。后段不得跳过未通过前段。每次观测冻结小时 bucket、workspace/source hash、逐 Gate input hash、Owner/下一动作和 Evidence，交给注册 runtime Verifier 追加记录；同一输入重放幂等，真实输入或 bucket 变化产生新 Observation。模块不读库、不写业务事实、不创建 Approval/Permit、不允许模型自证。详见 [ADR-0050](../adr/ADR-0050-dynamic-scoped-operating-gate-verifier.md) 与 [BAS-126 Evidence](evidence/20260728_BAS_126_DYNAMIC_SCOPED_OPERATING_GATE_VERIFIER.md)。 | P0 |
| BR-103 | Monitor-owned 经营 Gate freshness 观察闭环 | freshness 必须由专用 monitor 身份通过真实运行入口刷新，而不是手工 seed、模型声明或静态 Evidence。`POST /v1/agent-control/projects/{project_id}/observe` 只允许 exact tenant/store 的 monitor/admin，读取真实 PostgreSQL 0070 聚合、append-only project operating subject、exact current scope authority 和认证 Commerce OS 后调用纯 Verifier，追加 subject、scope-authority 与五个 Gate Observation；同输入/身份/小时幂等，变化追加。24×7 health、Windows Task preflight 与 G-1 Gate 必须检查 revision、合同、recorder/subject 分离、身份、外部写关闭和模型自证关闭；缺专用 monitor key 或 Task 时失败关闭且不得借用 admin/operator。详见 [ADR-0051](../adr/ADR-0051-monitor-owned-operating-gate-observation-loop.md)、[ADR-0055](../adr/ADR-0055-graph-project-operating-subject-binding.md)、[BAS-127 Evidence](evidence/20260728_BAS_127_OPERATING_GATE_OBSERVATION_LOOP.md) 与 [BAS-131 Evidence](evidence/20260728_BAS_131_OPERATING_SUBJECT_BINDING.md)。 | P0 |
| BR-104 | Verifier-owned Project/Engineering Graph 运行内核 | Graph 不只是可视化：Program/Project/Workstream/Release/Milestone/Requirement/ADR/Change/Code/Test/Build/Deploy/Observation/Evidence/Risk/Decision/Owner/SLA/Dependency/Authority 必须使用 stable node/edge/hash，并通过不可变、同项目 Node→GoalTask `status_source` binding 取得运行状态。节点只能投影注册 Verifier 的 append-only Observation，在 tenant/store/as_of 下继承 fresh/stale、上游变化阻断与幂等；未绑定节点不得显示运行状态。每个 Observation input 必须确定性绑定完整 GoalTask DAG 的直接依赖输入；上游变化先使旧下游 stale，同轮真实重验必须因依赖哈希变化追加新的下游 Observation 并恢复 fresh，不能因重放幂等错误永久 stale。drilldown 必须返回 why/next/owner/SLA/dependencies/verifier/Observation/artifact/Evidence/binding hash。Program/Project/Release 绑定 M4，M0→M4 Milestone/Gate 绑定各自任务，因此真实经营闭环未完成时 Release 必须 blocked/REJECTED。详见 [ADR-0052](../adr/ADR-0052-verifier-owned-project-engineering-graph-kernel.md)、[BAS-128 Evidence](evidence/20260728_BAS_128_PROJECT_ENGINEERING_GRAPH_KERNEL.md) 与 [BAS-135 Evidence](evidence/20260729_BAS_135_GRAPH_DEPENDENCY_REVERIFICATION.md)。 | P0 |
| BR-105 | Scope authority admission 与动态 Authority Graph | 正式 scope grant 之前必须有一个不落库的 admission preflight，冻结与最终事件完全相同的 tenant/entity/store/subject/decision/effective-at/Evidence/reason/idempotency 输入，并与 `record()` 共用 owner source→accepted independent review Lineage、exact metadata/hash、owner/reviewer/recorder/subject 四方分离和幂等冲突校验；preflight 只返回 verifier/hash/blocker/why/next/Owner/SLA，不创建 grant、Approval、Permit 或外部写。Monitor 观察循环必须按 exact principal/store/as_of 读取 `ScopeGrantAuthority.current`，为稳定 `task-m0-scope-authority-admission` 追加观测，并通过 Node→Task binding 驱动 `authority:current-scope-grant`；只有一个当前、完整、独立证明的 grant 可 passed，缺失 no_data，歧义、拒绝或坏 Evidence blocked。详见 [ADR-0053](../adr/ADR-0053-scope-authority-admission-and-graph-observation.md)、[ADR-0054](../adr/ADR-0054-authenticated-scope-authority-review-lineage.md)、[BAS-129 Evidence](evidence/20260728_BAS_129_SCOPE_AUTHORITY_ADMISSION.md) 与 [BAS-130 Evidence](evidence/20260728_BAS_130_AUTHENTICATED_SCOPE_AUTHORITY_REVIEW.md)。 | P0 |
| BR-106 | 认证 Scope Authority source/review 追加链 | 通用 Evidence 上传不得伪造 `scope_authority_source|review` 或对应合同 metadata。专用 source route 只能由 owner-capable reviewer/admin 在 exact store 下创建 B 级原件；专用 review route 必须由另一认证 reviewer/risk/compliance/admin 创建 A 级 accepted/rejected 决定和 source ID/hash Lineage，accepted 时三项来源/权威/作用域检查必须全过。0069 必须以局部唯一 source-ref 索引保证 exact replay 幂等、payload drift 冲突；`as_of` 必须同时限制 source/review/lineage，任一独立拒绝阻断。前台 Authority Graph/TODO 必须显示真实的 source→review→preflight next action；真实 owner 输入缺失时保持 fresh/no_data，禁止为验收伪造数据。详见 [ADR-0054](../adr/ADR-0054-authenticated-scope-authority-review-lineage.md) 与 [BAS-130 Evidence](evidence/20260728_BAS_130_AUTHENTICATED_SCOPE_AUTHORITY_REVIEW.md)。 | P0 |
| BR-107 | Project Graph 经营主体绑定与记录者分离 | Project/Engineering Graph 的运行状态必须属于被验证的经营主体，不能属于触发观测的 monitor/admin 记录者。每个 project+tenant+store 通过 append-only `bind/revoke` 事件在 `as_of` 下解析唯一 registered operator subject；目标必须与 exact tenant/store 匹配，且不得是 admin、monitor 或 recorder。Monitor 只负责读取真实外部状态并追加 Observation；Commerce OS、ScopeGrant 和 M0→M4 Verifier 必须全部以绑定 subject 求值。绑定事件须具备稳定 authority hash、幂等 replay、payload-drift/重叠/乱序/未来时间拒绝；subject/hash 进入全部下游 input hash，变化时自动产生新 Observation 并使旧投影 stale/阻断。`GET/POST /v1/agent-control/projects/{project_id}/operating-subject...`、Authority/Project/Engineering Graph、status rail 与 Verifier-owned TODO 必须可钻取到 subject、binding、verifier、Observation 和真实 artifact；绑定本身不创建 entity grant、Approval、Permit 或外部写。详见 [ADR-0055](../adr/ADR-0055-graph-project-operating-subject-binding.md) 与 [BAS-131 Evidence](evidence/20260728_BAS_131_OPERATING_SUBJECT_BINDING.md)。 | P0 |
| BR-108 | 外部 health scheduler 部署状态的 Verifier-owned Graph 观测 | BAS-040 不能只作为 Markdown `BLOCKED_CONFIG` 或脚本退出码存在。一个纯版本化 verifier 必须同时消费 `manage-evidence-health-task.ps1 -Mode Audit` 与 `run-24x7-health.ps1 -ControlPlaneOnly` 的真实 JSON，严格复验固定 Task 名称/路径、15 分钟触发、5 分钟上限、`IgnoreNew`、唯一无密钥 Action、工作目录、当前 result、七日完成历史和至少连续三次 result 0，以及 control plane/readiness/Evidence/Agent Gate 的当前健康。合同漂移或 accepted 自报不一致为 failed；Task/凭证/历史/健康缺失为 fresh blocked；只有全部外部条件同时满足才 passed。每次审计必须冻结原始输出、进程退出码、observed_at、input/result hash 到追加式 artifact/Observation，并以稳定 Task/Node/Edge 在 Project/Requirements/Engineering/Runtime/Evidence/Authority Graph、status rail 与 TODO 中投影 why/next/Owner/SLA。观察命令不得安装 Task、泄露或借用密钥、创建业务事实、Approval、Permit 或外部写。详见 [ADR-0056](../adr/ADR-0056-verifier-owned-health-scheduler-deployment.md) 与 [BAS-132 Evidence](evidence/20260728_BAS_132_HEALTH_SCHEDULER_GRAPH_OBSERVATION.md)。 | P0 |
| BR-109 | Exact-scope Authority Intake 动态工作台 | Scope Authority 的 owner source→独立 review→零写 preflight 必须成为真实 Project/Engineering 运行工作流，而不是 Graph 文案或静态表单。唯一服务端 intake 投影必须按认证 requester/目标 subject、tenant/entity/store/decision/as_of 选择保留合同 Evidence，并复验 hash、effective/recorded 双时间、owner/reviewer/subject 分离、三项 review checks、source ID/hash Lineage；缺 entity 为 input_required，缺源 no_data，拒绝/无 review/坏 Evidence blocked，只有当前 accepted review 为 ready_for_preflight。响应冻结 verifier/freshness、真实角色能力、candidate/count/hash、why/next/Owner/SLA；Web 从真实 session 和 endpoint 启用 source/review/preflight，API 再次执法，支持 artifact/Lineage 钻取。工作台不得引用正式 grant event route，外部观察只比较 API/Web 与读前读后 DB 计数并追加 content-addressed artifact/Observation；不得为验收伪造 source/review、创建 grant/Approval/Permit 或开放外部写。详见 [ADR-0057](../adr/ADR-0057-exact-scope-authority-intake-workbench.md) 与 [BAS-133 Evidence](evidence/20260728_BAS_133_SCOPE_AUTHORITY_INTAKE_WORKBENCH.md)。 | P0 |
| BR-110 | Authority 工作流真实身份拓扑观测 | Scope Authority 的四方分离不能由角色文案、API key 数量或前端 role switch 证明。纯版本化 verifier 必须从运行中 Web 进程的脱敏配置投影，在 exact tenant/store 下确定性复验四个不同 actor：非 admin/monitor operator subject、reviewer/admin owner、reviewer/risk/compliance/admin independent reviewer、compliance/admin recorder/preflight；重复/歧义 actor、跨 scope、未知用户绑定、角色冲突或外部写开启为 failed。API chain 与 Web chain 分开报告；Web 只有在 Supabase 模式且四个不同哈希用户引用分别绑定四个 actor 时才 passed，legacy 单身份必须 blocked。认证 endpoint 返回 as_of、freshness、input/result hash、候选链、why/next/Owner/SLA，不泄露 key 或原始 user ID。外部 observer 冻结 live Web 响应为 content-addressed artifact 并追加 Agent Harness Observation，稳定 Project/Requirements/Engineering/Runtime/Evidence/Authority Node 只通过 Node→GoalTask binding 取状态；配置变化使旧观测 stale。不得创建 Evidence/grant/Approval/Permit、不得加入角色切换、外部写保持 false。详见 [ADR-0058](../adr/ADR-0058-verifier-owned-authority-workflow-topology.md) 与 [BAS-134 Evidence](evidence/20260729_BAS_134_AUTHORITY_WORKFLOW_TOPOLOGY.md)。 | P0 |
| BR-111 | 浏览器可见 Origin 与 scoped collection 前台合同 | Supabase Web 的 CSRF 校验和登录/MFA/callback/logout redirect 必须使用同一浏览器可见 Origin 权威，不能把容器 bind address 当公开地址；生产可配置 `KJDS_WEB_PUBLIC_ORIGIN`，本地按真实 Host 校验。可信同源登录可 303，跨站和 originless POST 必须 403。前台读取 scoped Catalog/Product/OperationsQueue/ReadOnlyPilot 时必须消费服务端 canonical `items/products` envelope，并只为迁移期保留 legacy array 兼容；未知成功响应必须显式报合同漂移，不得把对象当数组触发运行时异常或静默伪装空数据。认证主页与 Project/Engineering/Authority Graph 必须在桌面和 390 CSS content viewport 展示 server-derived 状态、无页面级横向溢出，外部写保持 false。详见 [BAS-137 Evidence](evidence/20260729_BAS_137_AUTHENTICATED_WEB_RUNTIME_ACCEPTANCE.md)。 | P0 |
| BR-112 | 浏览器采集隔离收件箱与最小权限扩展 | 用户在允许的 1688/Ozon 当前标签页显式触发后，KJDS 必须通过单一版本化 Browser Capture Inbox 深模块冻结 visible-DOM/结构化数据投影、精确商品与变体、数量/MOQ、unit/checkout-total 价义、来源/时间/adapter/hash 和不可变 C 级 Evidence。当前 Principal 没有 entity authority 时必须保留真实 tenant/store、返回 `entity_ref=null`、`quarantined` 和 `entity_scope_authority_missing`，禁止把 tenant 代理为 entity；有 grant 也仅为 `pending_independent_binding`。浏览器助手只能使用 `activeTab+scripting+storage(session)` 和显式 KJDS handshake，不得读/传 cookies、localStorage、内部 API，不得用 webRequest、广域 host、`<all_urls>` 或绕过 CAPTCHA。公开页价格不得升格 Supplier Offer/actual cost，媒体不得升格权利资产；收件箱不得创建 Product/Listing/Approval/Permit 或任何平台写。详见 [ADR-0059](../adr/ADR-0059-browser-capture-inbox.md)。 | P0 |
| BR-113 | 竞争 ERP 全能力基准与 KJDS 原生吸收 | 无忧易售、妙手、芒果店长、Maozi、荔枝、LinkFox 等只能作为能力与工作流基准，不能成为 KJDS 事实源或运行时依赖。每份可访问资料中的能力必须逐项进入版本化 benchmark registry，冻结来源、观察时间、C/D 级 Evidence、KJDS 原生目标深模块、实施波次、当前状态、安全边界与采用/深化/替换/拒绝决定；`mapped` 不得解释为 `implemented`。`CommerceOperatingSystem` 必须从该机器真源动态投影逐项映射、汇总、源哈希和实现状态，前台可钻取且明确显示“映射 ≠ 实现”；注册表计数或采用汇总漂移必须失败关闭。PIM、OMS、采购、库存、FBP/realFBS 履约、财务/结算、BI、内容媒体和 Agent Team 必须共用 KJDS Canonical Product、三本利润账、Evidence、OperationsQueue、Approval/Permit/Readback 与 Graph，不得复制 Cookie/session、宽域注入、内部接口、盗图、验证码绕过或无利润/治理门禁的批量写。Maozi 公开飞书文档当前 28 项能力映射见 [registry](registries/maozierp_feishu_capability_benchmark.json)。 | P0 |
| BR-114 | Exact-scope 真实订单触发采购审查 | 采购不得由页面观察、候选、Listing 草稿或历史订单状态触发。唯一 `SaleTriggeredProcurementPolicy` 必须按当前 tenant/entity/store/grant 读取已正式晋升的 Ozon Order Fact 和同 scope Canonical Product；同一 `external_id` 只取 as-of 下最新状态，后续取消/退货必须覆盖旧 `awaiting_packaging`，多个不同当前订单按整数数量守恒汇总。订单 Evidence、SKU、币种、收入、数量、时间或 scope 任一失配均失败关闭。当前供货 checkout 和完整正 downside CM3 仍有效时只创建既有 OperationsQueue 中的内部采购复核任务；成本/供货漂移创建内部 escalation。两者都必须返回 Fact/Evidence/order IDs、Owner、SLA、next 和稳定哈希，并固定 `supplier_order_created=false`、`payment_created=false`、`automatic_procurement=false`、`external_purchase_write=false`。真正采购仍需独立 Approval、一次性采购 Permit、结算页 Readback、Kill Switch 与 Compensation。详见 [ADR-0060](../adr/ADR-0060-scoped-sale-triggered-procurement-review.md) 与 [BAS-140 Evidence](evidence/20260729_BAS_140_SCOPED_SALE_TRIGGERED_PROCUREMENT.md)。 | P0 |
| BR-115 | Native scoped OMS 当前态与时间线 | AI ERP 的订单工作台不得把 legacy `orders` 表、页面观察或模型推断升格为真实 Ozon 订单。唯一 `ScopedOmsWorkspace` 必须只读 exact tenant/entity/store/grant 下已正式晋升的 `ozon_order/ozon_return` Fact，按 `scope_as_of/effective_at/recorded_at` 复验 cutoff 和不可变 Evidence，按 external order 输出有序时间线并由最新候选事实导出当前态；最新事实若 Evidence/hash/合同失败，该订单必须 blocked/unknown，旧有效状态只作历史，绝不复用为 current。取消/退货必须显式关联 Order/Product/SKU；未知状态保持 unknown/blocker，不得猜测。响应必须含 Fact/Evidence IDs、Decimal 字符串、币种、Owner/SLA/next、稳定 snapshot hash、完整排序键 opaque cursor 与 Agent decision-support artifact，并固定 legacy rows inferred=false、client recalculation=false、external write=false。详见 [ADR-0061](../adr/ADR-0061-native-scoped-oms-timeline.md)。 | P0 |
| BR-116 | Native scoped 库存、仓储与履约覆盖 | AI ERP 库存不得从商品页、竞品页、静态费用表或 Agent 推断。唯一 `ScopedInventoryFulfillmentWorkspace` 必须只读 exact tenant/entity/store/grant 下已正式晋升的 `ozon_inventory` 快照 Fact，并以 exact Product/SKU + warehouse + `FBP/realFBS` + cluster 作为库存单元；数量只允许非负整数，时间/Evidence/hash/Product/SKU/自然键必须复验。最新候选快照失败时该库存单元 blocked，旧有效库存仅为历史，绝不回退为 current。服务端可组合同一 `as_of` 的 Native OMS 当前态，计算待履约订单需求、正式可用库存和短缺建议；OMS 无数据时 coverage 必须 blocked/no_data，不得把需求当零。返回必须含 current/timeline、Fact/Evidence IDs、Owner/SLA/next、opaque cursor、稳定 snapshot hash 与 Agent decision-support artifact，并固定 legacy inventory inferred=false、marketplace observation inferred=false、client recalculation=false、inventory/reservation/fulfillment/procurement/payment/Approval/Permit/external write=false。退货导入可兼容缺少订单关联的旧数据，但 Native OMS 对缺少 `order_external_id` 的退货继续 fail-closed。详见 [ADR-0062](../adr/ADR-0062-native-scoped-inventory-fulfillment.md)。 | P0 |
| BR-117 | 市场验证 Must-have 原生覆盖与 AI Agent 化 | 毛子、荔枝、芒果店长、店小秘、妙手、无忧易售、Seerfar 与 LinkFox 已出现的安全经营能力必须作为 `must_have_native_parity` 基线进入版本化 Registry 和 M0→M4 交付图；任何安全能力不得因“AI 化”省略，Cookie/session 复用、宽域注入、验证码绕过、静态费率真源、无权利盗图或无门禁批量写必须改为完成同一 JTBD 的安全原生替代。覆盖率必须逐项由代码、迁移、API、Web、权限、真实回放和 Evidence 证明，`mapped`、菜单或模型自述不得升格为实现。基础覆盖与 AI 优势分开计分；12 个责任 Agent 共享 PIM/OMS/Inventory/Finance/Evidence/Rule 内核，输出版本化 artifact，由 Harness/Graph 外部观测 verifier 更新状态，不能自批、自发 Permit 或执行外部写。详见 [ADR-0063](../adr/ADR-0063-market-validated-native-parity-and-agentization.md)、[Ultimate Product Blueprint](ULTIMATE_PRODUCT_BLUEPRINT.md) 与 [Ultimate Requirements Architecture](ULTIMATE_REQUIREMENTS_ARCHITECTURE.md)。 | P0 |
| BR-118 | 原生 exact-scope PIM 商品主数据工作台 | 唯一 `ScopedPimWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合现有 `ScopedMarketplaceCatalogAuthority` 与 `ScopedProductContentAuthority`，不得建立第二套 Product/SKU/Listing 真源。服务端以 Canonical Product 归并 Product 主档、三类 Passport、ContentAsset/媒体 QA、Ozon Listing/offer 与 marketplace SKU 绑定、未绑定 Listing、身份及刊登前 readiness、source gaps、blockers、Owner/SLA/next、确定性筛选/游标、counts 与稳定 snapshot hash；客户端不得重算。缺 entity 时不得读取 raw；匿名为 401、越权为 403；坏 Evidence 或最新坏记录失败关闭。Agent 只能输出版本化建议/内部任务 artifact，不得创建 Product、Passport、Listing、Approval、Permit 或执行外部写。交付 `GET /v1/pim/workspace`、`/pim` 的真实列表、详情、空态、错误、重试、桌面与 390px 验证，并允许从 `/commerce-os` 下钻。详见 [ADR-0064](../adr/ADR-0064-native-exact-scope-pim-workspace.md)。 | P0 |
| BR-119 | 原生 exact-scope 供应智能工作台 | 唯一 `ScopedSourcingIntelligenceWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合现有 PIM、Market Radar、Scoped Batch Opportunity、Scoped Evidence、RFQ package/dispatch 与 Supplier Quote authority，不得建立第二套 Product、Supplier、Quote 或利润真源。服务端输出 exact identity 需求/竞品/供应 cohort、Canonical Product 关联、RFQ/三报价 readiness、供应商证据状态、原生候选、十五项 downside CM3、source gaps/blockers/Owner/SLA/next、确定性筛选/opaque cursor/counts 与稳定 snapshot/artifact hash；观察价、正式报价、screening CM3、formal CM3 和 Actual Cash CM3 必须分层。缺失/无效 entity 必须零 upstream/raw read；坏最新 Evidence、合同/scope/as_of/hash 漂移、未绑定 RFQ/quote 失败关闭且不泄露受影响业务载荷。Accio 仅为公开或正式授权 Adapter 与市场 JTBD 基准，不得依赖私有接口、Cookie、内部 Token 或验证码绕过。Agent 仅允许建议与内部任务，不得联系供应商、发送 RFQ、接受报价、创建 Supplier Offer/PO/Payment/Product/Listing/Approval/Permit 或执行外部写。交付 `GET /v1/sourcing-intelligence/workspace`、`/sourcing-intelligence` 的 ready/no_data/blocked/error/retry、桌面与 390px 验证及 Commerce OS/PIM 下钻。详见 [ADR-0065](../adr/ADR-0065-native-exact-scope-sourcing-intelligence-workspace.md)。 | P0 |
| BR-120 | 授权 Seller ERP Bridge 与 Canonical Diff | 唯一 `ScopedSellerErpBridge.reconcile(...)` 必须在同一 tenant/entity/store/as_of 下，把平台官方导出、Seller ERP 正式导出或书面授权 Adapter snapshot 作为 Observation 与现有 `ScopedPimWorkspace`、`ScopedOmsWorkspace`、`ScopedInventoryFulfillmentWorkspace` 权威对账；不得建立第二套 Product、SKU、Listing、Order 或 Inventory 真源。导入必须冻结原始文件哈希、provider/source kind/domain/schema/列映射/exported_at/authorization mode，提交者、独立 Reviewer、Compliance binding recorder 三者分离；仅 exact-scope、current、完整性通过、accepted review 且 A 级 target ID/hash binding 的源可进入 Diff。服务端输出 `matched / source_only / canonical_only / conflict / blocked`、逐字段差异、source gaps/blockers/Owner/SLA/next、稳定 counts/snapshot/artifact hash；缺 entity 或 source ID 时不得读取原件/上游，坏 Evidence、最新拒绝/撤销、schema drift、scope/as_of/hash 冲突必须失败关闭且不泄露业务行。店小秘等第三方仅可通过正式导出、公开/签约 API 或明确授权 Adapter 接入；禁止私有接口、Cookie、内部 Token、验证码绕过和伪造授权。Agent 只可建议/内部任务，不得导入正式 Fact、创建/修改 Product/Listing/Order/Inventory/Approval/Permit 或执行外部写。交付 dedicated source/review/binding/revoke workflow、`GET /v1/seller-erp-bridge/reconcile`、`/seller-erp-bridge` 的 ready/no_data/blocked/error/retry、桌面与 390px 验证及 Commerce OS 下钻。详见 [ADR-0066](../adr/ADR-0066-authorized-seller-erp-bridge-canonical-diff.md)。 | P0 |
| BR-121 | 原生 exact-scope Listing 变更与刊登生命周期 | 唯一 `ScopedListingLifecycleWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合现有 `ScopedPimWorkspace`、scoped Listing Draft、Listing Russian-native Evidence review、独立 Approval 与 governed Execution Plan/Dry Run 权威；不得建立第二套 Product、Listing、Approval、Permit 或平台状态真源。服务端以 Canonical Product + offer 为中心输出 observed platform Listing、desired frozen draft、`same / changed / source_missing / desired_missing` 字段 Diff、draft/review/approval/plan/dry-run/readback 阶段、authority drift、source gaps/blockers/Owner/SLA/next、确定性筛选/opaque cursor/counts 与稳定 snapshot/artifact hash。缺失/无效 entity 必须零 Listing/PIM/Approval/Plan read；坏最新 Evidence、跨 scope、未来记录、product/approval/snapshot/hash 漂移、未核权媒体或 PIM 截断必须失败关闭且不泄露受影响载荷。Read-only workspace 不创建 Draft、Review、Approval、ExecutionPlan、Permit 或平台任务；Agent 只能建议/内部任务，不得自批、自发 Permit、发布、改价、改库存或执行外部写。Observed、desired、approved 与 readback 必须分层，缺平台字段显示 `source_missing`，不得把未知当相同。交付 `GET /v1/listing-lifecycle/workspace`、`/listings` 的 ready/no_data/partial/blocked/error/retry、桌面与 390px 验证及 PIM/Commerce OS 下钻。详见 [ADR-0067](../adr/ADR-0067-native-exact-scope-listing-lifecycle.md)。 | P0 |
| BR-122 | 原生 exact-scope 内容媒体工厂 | 唯一 `ScopedContentMediaFactoryWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合现有 `ScopedProductContentAuthority`、ContentAsset、固定准入模板、PostgreSQL media execution/event ledger 与 Delivery Manifest，不得建立第二套 Product、ContentAsset、QA、Execution、Manifest、Listing、Approval 或 Permit 真源。服务端按 Canonical Product + ContentAsset 输出来源/权利/产物/QA、图片与视频角色/比例覆盖、模板准入、latest execution 与 append-only timeline、attempt/lease/cost/latency/error/retry、Manifest 完整性/Listing eligibility、`brief/source_rights_ready/queued/executing/generated/qa_pending/qa_failed/delivery_ready/blocked` 阶段、source gaps/blockers/Owner/SLA/next、服务端 counts、确定性筛选/opaque cursor 与稳定 snapshot/artifact hash。缺失/无效 entity 必须零 Product/Asset/Execution/Event/Manifest raw read；坏最新 Evidence、跨 scope、未来可变状态、input/template/hash 漂移、事件 sequence/transition/time 断裂、Manifest asset/execution/state/hash/time 不一致或上游截断必须失败关闭且不泄露受影响载荷。Projection 和 Agent 只可建议/创建内部任务，不得创建或修改 Asset/Job/QA/Manifest/Listing/Approval/Permit，不得调用外部媒体提供方或平台写。既有 mutation API 继续执行独立 scoped preflight；准入模板仅允许固定 ComfyUI retouch 和批准图片+人工确认俄语脚本/字幕+权利音频的固定 FFmpeg 链。交付 `GET /v1/media-factory/workspace`，兼容 `/v1/media/workbench` 但由同一深模块投影，以及 `/media-factory` 的 ready/no_data/partial/blocked/error/retry、桌面与 390px 验证和 Commerce OS/PIM/Listing 下钻。详见 [ADR-0068](../adr/ADR-0068-native-exact-scope-content-media-factory.md)。 | P0 |
| BR-123 | 原生 exact-scope 结算与现金对账工作台 | 唯一 `ScopedSettlementCashWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合原生 scoped Order/Accrual/Settlement Fact、原生 scoped FinanceEntry/ReconciliationRun 和现有 `ScopedProfitLedgerAuthority`，不得建立第二套订单、计提、结算、银行现金或利润真源。服务端按显式 reconciliation key 输出 Order/Accrual、Platform Settlement、Bank Cash 三本账、逐腿 Evidence、unknown fee/review 隔离、settlement/cash variance、最新独立 reconcile observation、Actual Cash CM3 eligibility、`fact_pending/accrual_pending/settlement_pending/cash_pending/reconcile_pending/variance/unknown_fee/reconciled/blocked` 阶段、Owner/SLA/next、服务端 counts、确定性筛选/opaque cursor 与稳定 snapshot/artifact hash。缺失/无效 entity 必须零 Fact/Finance/Reconciliation/Profit raw read；legacy 无 scope 行不得猜测回填或参与原生账；坏最新 Evidence、跨 scope、未来记录、scope-grant/source hash 漂移、重复冲突、最新 reconcile 输入/状态漂移、未知费用或账腿不守恒必须失败关闭且不泄露受影响业务金额/标识。Actual Cash CM3 只有在同 scope/as_of 的 scoped profit ledger 已 `reconciled`、三本账守恒且所有费用已分类时才可显示，否则必须为 `no_data`。Projection 与 Agent 只可建议/创建内部任务，不得创建 FinanceEntry/ReconciliationRun/Fact/Approval/Permit，不得发起收款、付款、退款、争议或任何外部写。交付 forward-only scoped finance authority 迁移、`GET /v1/finance-control/workspace`、`/finance-control` 的 ready/no_data/partial/blocked/error/retry、桌面与 390px 验证及 Commerce OS/OMS/Inventory 下钻。详见 [ADR-0069](../adr/ADR-0069-native-exact-scope-settlement-cash-control.md)。 | P0 |
| BR-124 | 原生 exact-scope 十五项实际利润与 Actual Cash CM3 | 唯一 `ScopedProfitLedgerAuthority.snapshot(...)` 必须在同一 tenant/entity/store/as_of 下直接组合原生 scoped Order Fact、Canonical Product、FinanceEntry、FeeMapping、FX 与最新独立 ReconciliationRun，不得再读取 legacy `orders/charges` 后按 Evidence 过滤，也不得建立第二套订单、成本或利润真源。服务端必须逐订单输出采购、国内物流、头程、包装、仓储、关税、税费、尾程、佣金、广告、退款退货、汇兑、资金占用、售后和损耗十五项 `actual/zero/unknown` 成本、CM1/CM2/CM3、Bank Cash conservation、Evidence、Owner/SLA/next、服务端 counts、确定性筛选/opaque cursor 与稳定 snapshot/artifact hash；费用映射与 FX 必须是 exact-scope、as-of、完整性通过的原生权威。Order Fact 必须绑定同 scope Product 和独立复核的 Order Receivable；平台扣费只由当前 scoped FeeMapping 分类，非平台实际成本只由逐订单显式 Bank Payment 分类，禁止 SKU 猜配、跨订单净额、店铺均摊或比例分摊。十五项任一缺失、unknown fee、未复核、坏/未来 Evidence、scope/source/hash 漂移、当前 Order/Product 冲突、最新 reconcile 非 matched/损坏或 `gross + platform adjustments + bank payments != bank receipt + bank payments` 时 Actual Cash CM3 必须 `no_data/blocked` 并隐藏受影响金额与标识；显式零也必须有独立 Evidence。缺失/无效 entity 必须零 raw read；legacy FeeMapping/FX/FinanceEntry 保持隔离且不猜回填。Projection 与 Agent 只可建议/创建内部任务，不得创建或修改 Fact、Product、FeeMapping、FX、FinanceEntry、Reconciliation、Approval、Permit，不得付款、退款、调价、投放或外写。交付 forward-only 原生利润权威迁移、升级 `GET /v1/profit-ledger` 与 `/erosion`、新增 `/profit-ledger` 的 ready/no_data/partial/blocked/error/retry、桌面与 390px 验证及 Finance Control/OMS/Commerce OS 下钻。详见 [ADR-0070](../adr/ADR-0070-native-exact-scope-actual-profit-ledger.md)。 | P0 |
| BR-125 | 原生 exact-scope 采购与收货控制 | 唯一 `ScopedProcurementReceivingWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下直接组合既有 SamplePurchaseOrder、ProcurementEvent、Canonical Product、SupplierOffer、ProfitScenario、独立采购 Approval 与 Evidence，不得建立第二套 Product、Supplier、Offer、Scenario、Approval、采购单或收货真源，也不得把缺失的应付/付款权威伪装成完整 P2P。服务端按采购单输出 exact Product/SKU、供应商、批准依据、报价/场景版本、数量/单价/服务端订单值、`approved_to_order/order_confirmed/shipped/received/inspected/golden_sample_approved/sample_rejected/rework_required/cancelled/blocked` 阶段、顺序事件、收货/损坏/质检事实、Evidence、Owner/SLA/next、服务端 counts、确定性筛选/opaque cursor 与稳定 snapshot/artifact hash。0077 只为既有 sample purchase order/event 增加 complete-or-empty tenant/entity/store/grant/source/as-of authority，并为采购单增加唯一 authority Evidence；legacy 行保持隔离且不猜回填。缺失/无效 entity 必须零 raw read；坏/未来 Evidence、跨 scope、Product/Offer/Scenario/Approval 绑定漂移、非独立/非 approved 决定、十五项场景不完整或非正 CM3、事件 sequence/transition/time/facts/hash 漂移、重复冲突、收货或质检数量不守恒必须失败关闭并隐藏受影响金额与标识，坏最新事件不得回退旧阶段。Projection 与 Agent 只可建议/创建内部任务，不得创建或修改采购单、事件、Product、Offer、Scenario、Approval、Permit、库存、应付或付款，不得联系供应商、下单、收货确认、退款或外写。应付发票与付款保持明确 `no_data/gated`，后续必须由独立权威切片实现。交付 `GET /v1/procurement/workspace`、`/procurement` 的 ready/no_data/partial/blocked/error/retry、桌面与 390px 验证及 Sourcing/OMS/Inventory/Commerce OS 下钻。详见 [ADR-0071](../adr/ADR-0071-native-exact-scope-procurement-receiving-control.md)。 | P0 |
| BR-126 | 原生 exact-scope 应付发票、三方匹配与供应商付款控制 | 唯一 `ScopedAccountsPayableWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合新建但唯一的不可变 Supplier Invoice header/line 权威、既有 `ScopedProcurementReceivingWorkspace`、Canonical Product、独立 Invoice Review Evidence、采购/付款 Approval、一次性 `LimitedExecutionCommand` Permit 与原生 scoped `FinanceEntry.BANK_PAYMENT` 银行 Readback，不得建立第二套 Product、采购单、收货、Approval、Permit、Bank Payment 或利润真源，也不得继续把 `supplier_invoice_payment` 成本复核 attestation 当作 AP 子账。0078 新建 exact-scope invoice header/line，并仅为现有 FinanceEntry 增加可空但 complete-or-empty 的 supplier invoice/supplier/payment Approval/command 绑定；历史 Bank Payment 保持隔离且不猜回填。服务端按 Invoice 输出 header/line、PO/receipt/inspection 三方匹配、税额与总额守恒、付款决定/Permit/银行回读链、未付/部分/已付/差异、Owner/SLA/next、服务端筛选/opaque cursor/counts 与稳定 snapshot/artifact hash。状态至少为 `invoice_captured/review_pending/rejected/three_way_match_pending/matched/payment_approval_pending/payment_permit_pending/payment_readback_pending/partially_paid/settled/variance/blocked`。缺/坏 entity 必须零 Invoice/Procurement/Finance/Approval/Command raw read；坏/未来 Evidence、跨 scope、重复当前发票、header/line/hash/金额/币种/供应商漂移、非独立 review、PO/收货/验货数量或单价不匹配、自批付款、过期/重复 Permit、非 bank Readback、正号付款、重复/超额/跨发票支付及账款不守恒必须失败关闭并隐藏受影响金额与标识，坏最新记录不得回退旧成功态。Projection 与 Agent 只可建议/创建内部任务，不得创建/修改 Invoice、Review、FinanceEntry、Approval、Permit，不得发起付款、退款、供应商联系或外写；BAS-152 只验证观测到的受控付款链，不启用支付 Adapter。交付 capture/review intake、`GET /v1/accounts-payable/workspace`、`/accounts-payable` 的 ready/no_data/partial/blocked/error/retry、桌面与 390px 验证及 Procurement/Finance/Profit/Commerce OS 下钻。详见 [ADR-0072](../adr/ADR-0072-native-exact-scope-accounts-payable-control.md)。 | P0 |
| BR-127 | 原生 exact-scope 退货、退款与售后财务控制 | 唯一 `ScopedReturnsAfterSalesWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合既有 `ScopedOmsWorkspace` 正式 `ozon_order/ozon_return` Fact 时间线与 `ScopedSettlementCashWorkspace` 三本账，不得建立第二套 Order、Return、Product、FinanceEntry、Reconciliation、退款或客服真源。服务端按 Order/Return 输出 exact Product/SKU、Return Fact/Evidence、原因、数量/金额/币种、退货阶段、订单与退货数量守恒、退款/结算/银行回读状态、Owner/SLA/next、服务端筛选/opaque cursor/counts 与稳定 snapshot/artifact hash；同一 return ID 重复、退货量超过订单量、跨订单/Product/SKU/币种、未来/坏 Evidence、OMS/Finance 合同/scope/as_of/hash 漂移、截断或财务周期歧义必须失败关闭且隐藏受影响业务值，坏最新 Fact/Reconciliation 不得回退。缺/坏 entity 必须零 OMS/Finance raw read；OMS 无 Order/Return 时不得读取 Finance 并保持真实 `no_data`。当前没有权威客户消息、客服工单、平台争议或 RMA 子账，必须显式返回 `customer_service_case_authority_available=false` 与 `gated`，不得用第三方 ERP 页面/私有接口、Agent 对话或客服草稿冒充。Projection 与 Agent 只可建议内部任务，不得创建/修改 Fact、退款、工单、消息、Reconciliation、Approval、Permit，不得联系客户、发起退款/争议或外写。交付 `GET /v1/returns/workspace`、`/returns` 的 ready/no_data/partial/blocked/error/retry、桌面与 390px 验证及 OMS/Finance/Profit/Commerce OS 下钻；纯读组合无 schema 变化，Alembic 保持单一 0078。详见 [ADR-0073](../adr/ADR-0073-native-exact-scope-returns-aftersales-control.md)。 | P0 |
| BR-128 | 原生 exact-scope 客服 Case、Message、Dispute 与 RMA 权威 | 唯一 `ScopedCustomerServiceWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合唯一不可变 CustomerServiceCase/Event 权威、BAS-153 Return/Finance 投影、Canonical Product、Evidence、独立回复 Approval、一次性 LimitedExecutionCommand 与发送 Readback，不得建立第二套 Order、Return、Product、Approval、Permit、退款或消息真源。0079 新建 exact-scope `customer_service_cases/events`；正文、客户姓名、地址、电话、邮箱、平台账号等敏感内容只保存在受治理 Evidence Blob，业务表仅保存 channel、方向、locale、分类、非敏感摘要、正文 SHA-256、权威引用和时间，不得将 PII 复制到 Agent artifact、Graph、日志、游标或列表。服务端输出 Case、不可变事件时间线、Order/Product/Return 绑定、SLA/情绪/风险分类、draft/approval/permit/readback 阶段、Dispute/RMA 状态、Owner/next、服务端筛选/opaque cursor/counts 与稳定 snapshot/artifact hash。缺/坏 entity 必须零 Case/Event/Return/Approval/Command raw read；坏/未来/撤销 Evidence、跨 scope、Case/Event/hash/sequence/time/order/Product/SKU 漂移、重复 source event、非法状态转换、self approval、过期/重复 Permit、缺/坏发送 Readback、最新坏事件或 PII 泄漏必须失败关闭且不得回退旧成功态。Agent 仅可基于脱敏结构化上下文生成版本化回复草稿和内部任务，不得读取未授权 PII、自批、发 Permit、标记 sent、退款、争议、联系客户或外写；真实消息发送继续要求注册表允许、独立 Approval、一次性 Permit、Readback、Kill Switch 与 Compensation，本切片不启用消息 Adapter。交付 Case/Event intake、`GET /v1/customer-service/workspace`、`/customer-service` 全状态、桌面与 390px、0079 回放、真实 no_data、API/OpenAPI、Graph/Harness Evidence 及 OMS/Returns/Commerce OS 下钻。详见 [ADR-0074](../adr/ADR-0074-native-exact-scope-customer-service-authority.md)。 | P0 |
| BR-129 | 原生 exact-scope 增长实验权威 | 唯一 `ScopedGrowthExperimentWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下，以 Canonical Product/Listing 归并正式市场观测、PIM/内容、库存/订单、Actual CM3、评价/客服脱敏信号以及价格、促销、广告实验 readiness；服务端拥有 counts、筛选、opaque cursor、稳定 snapshot 与版本化 Agent artifact。缺 entity 零上游 raw read；跨 scope、坏 Evidence/hash/as_of/绑定或最新权威失败必须关闭且不得回退。旧 `/v1/marketplace-growth/*` 与 0042 非 exact-scope 事实保持 legacy 隔离，不猜测回填。Agent 只可建议、形成 shadow experiment 或内部任务，不得改价、建促销、投广告、联系客户、自批或签发 Permit；所有外部写及私有 ERP interface 默认 false。交付 `GET /v1/growth-experiments/workspace`、独立 `/growth-experiments` 全状态 Web、API/OpenAPI、PostgreSQL/runtime、Evidence 与 Graph/Harness；详见 [ADR-0075](../adr/ADR-0075-native-exact-scope-growth-experiment-authority.md)。 | P0 |
| BR-130 | 原生 exact-scope 物流交付与异常权威 | 唯一 `ScopedDeliveryExceptionWorkspace.project(...)` 必须在同一 tenant/entity/store/as_of 下组合 OMS Order、正式物流 Event/Tracking Evidence、Inventory fulfillment、Return/Customer Service 与费用影响，输出 Shipment timeline、承运商/服务/区域、handover/in-transit/delivery/exception/return 状态、SLA、Owner/next、counts/filter/opaque cursor/snapshot/artifact。缺 entity 零 raw read；跨 scope、坏最新 Evidence/hash/as_of/Order/Product/Tracking 绑定、倒序/重复事件和非法转换失败关闭不回退。不得把 legacy logistics quote、网页轨迹或 ERP 私有接口当交付事实；Agent 只建议异常分诊和内部任务，不联系承运商/客户、不改 Order/Inventory/Return、不自批/发 Permit/外写。详见 [ADR-0076](../adr/ADR-0076-native-exact-scope-delivery-exception-authority.md)。 | P0 |
| BR-131 | 原生 exact-scope 仓库波次、拣配与扫码称重权威 | 唯一 `ScopedWarehouseFulfillmentWorkspace.project(...)` 在同一 tenant/entity/store/warehouse/order/as_of 下组合既有 Canonical Product/SKU、OMS Order、Inventory、采购收货、BAS-156 Delivery 与 append-only 0080 warehouse execution authority，不建立第二套 Product、Order、Inventory、Shipment、Return、Approval 或 Permit 真源。缺 entity 零 raw read，无正式 Order 在所有其他上游前短路。正式事件只接纳官方公开 API、授权正式导出或明确授权仓库系统，绑定 adapter identity/version、独立 authorization Evidence、immutable payload/hash、revocation/as_of；坏最新 Evidence、跨 scope、重复/超额预留、负库存、lot-bin drift、pick-pack 数量不守恒、未知重量来源、乱序/重复扫码、label-order 冲突失败关闭不回退。库存调整、出库确认、买面单与交接为 L4 `policy_only`，正式 Readback 还必须绑定独立 Approval、版本化一次性 Permit、成功 Readback、Kill Switch 与 Compensation Evidence；Agent 仅建议与内部任务，所有外写、联系、自批、发 Permit 和私有 ERP interface 均 false。API/OpenAPI、独立 Web 全状态、PostgreSQL/runtime/browser/Graph Evidence 已交付；真实 Order/Inventory/warehouse event 仍 `0/no_data`。详见 [ADR-0077](../adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md)。 | P0 |
| BR-132 | 原生 exact-scope 渠道账户、店铺授权与运行身份权威 | 唯一 `ScopedChannelAccountAuthorityWorkspace.project(...)` 已在 deep module 内组合 authenticated Principal、canonical Store Matrix、Scope Grant、严格用途型 Evidence、append-only authorization/review/Kill 权威与不可伪造的 managed credential lease admission。缺 entity 零读；Store Matrix/Scope Grant/adapter/account/epoch/sequence/Evidence/hash/as-of/health/readback/双 active/分页全量状态漂移失败关闭不回退。公开 API 仅 GET；grant/refresh/rotate/revoke、secret read、自批、Permit、provider contact 与全部外写保持 `mutation_gated/policy_only`。生产 resolver、官方 provider readback、外部 verifier 与真实授权均未绑定，因此运行态为 `no_data/blocked`、`implemented_unverified` 且 `verified_native=false`。详见 [ADR-0078](../adr/ADR-0078-native-exact-scope-channel-account-authority.md) 与 [Evidence](evidence/20260731_BAS_158_NATIVE_EXACT_SCOPE_CHANNEL_ACCOUNT_AUTHORITY.md)。 | P0 |
| BR-133 | Capability-granular 原生同等能力验收权威 | 唯一 `NativeParityAcceptanceWorkspace.project(...)` 已按 exact tenant/entity/store/provider/capability/version/as_of 组合 code、migration、API/OpenAPI、Web、permission/write-path、authenticated runtime replay、immutable Evidence 与 fresh external Graph verifier 八维验收；`SqlNativeParityAcceptanceRecords` 只从 canonical Graph/Harness 完整 bundle 生成候选记录。Commerce OS 不再由硬编码 `implementation_status="implemented"`、菜单、benchmark mapping 或共享 stage Evidence 将整族能力升级。服务端输出 `mapped/implemented_unverified/gated/verified_native/blocked/stale`、全量 counts、筛选、opaque cursor、稳定 snapshot 与版本化 acceptance artifact；任一维缺失、坏最新、stale、cross-scope/hash/version 或 provider-specific verifier 缺失均失败关闭。八类 provider-specific C 级能力继续 gated；真实 scope 为 `no_data/items=0/verified_native=0`。该 seam GET-only，Agent/模块不得自证或创建业务 Fact、Approval、Permit、凭据及外写。详见 [ADR-0079](../adr/ADR-0079-native-parity-acceptance-verifier.md) 与 [Evidence](evidence/20260801_BAS_159_NATIVE_PARITY_ACCEPTANCE.md)。 | P0 |
| BR-134 | 单链接单 SKU 受治理 AI 上架与内部 Dry-run | 唯一 `AgentInferenceService.infer(AgentTaskSpec) -> AgentArtifact` 是业务 Agent 的模型调用边界；六类准入任务、最小字段、JSON Schema、Prompt、模型能力、数据策略和质量阈值由版本化 `agent_task_registry` 决定。每次推理必须绑定 exact tenant/entity/store/as_of、输入快照哈希、不可变 Evidence、任务合同和 AI Listing run；本地 Ollama 最多一次，只有任务允许且本地不可用、超时、结构失败或质量未达时才最多一次回退 OpenAI-compatible 网关，策略/Evidence/作用域/预算失败不得换模型绕过。模型输出只能形成不可变 proposal Artifact 和原始响应 Evidence，固定 `proposal_only=true/formal_fact=false/external_write_allowed=false`，不得直接写 Product、Passport、SupplierOffer、ProfitScenario、Listing、Approval、Permit 或平台。唯一 `AiListingPipeline` 只处理一个已显式采集的真实 1688 链接与一个选中变体，复用既有商品/Passport、官方 Ozon 类目合同、十五项 Decimal 成本、ComfyUI 准入模板、素材权利、俄语母语复核、Listing Approval、Governed Execution Plan 与 Dry-run；页面展示价永不自动成为 SupplierOffer/actual cost，AI 不得创造类目 ID、枚举、成本或硬事实。流水线可恢复、幂等、租约化并逐阶段失败关闭；缺 scope/Evidence/报价/成本/正 CM3/素材权利/人工 QA/俄语复核/独立审批/平台 before-state 时返回稳定 blocker。首期终点严格为 `dry_run_passed`，不得创建 Execution Approval、Permit、Worker command、Ozon write、采购单或付款；由 `KJDS_AI_LISTING_ENABLED=false` 默认关闭。交付 forward-only `ai_listing_runs/agent_runs/agent_artifacts/agent_run_events`、六个 API、`/ai-listing` 全状态 Web、390px 无横溢出、浏览器采集合约 1.1 向后兼容、Provider/推理/流水线/安全/迁移/OpenAPI/真实浏览器验收。详见 [ADR-0080](../adr/ADR-0080-governed-agent-inference-and-ai-listing-dry-run.md)。 | P0 |
| BR-135 | Canonical 渠道账户治理状态机与 worker exact-scope lease | 唯一 `ChannelAccountGovernanceStateMachine.advance(...)` 必须把 BAS-158 已有 SoD Evidence、Review、Approval、ExecutionPlan、authorization event、Kill、Permit、Readback、Compensation 与 managed credential lease 组合成生产 API 可达而不可绕过的状态机，不另建渠道账户、Approval、Permit 或凭据真源。正常路径必须经 authenticated exact tenant/entity/store submit→独立 review→approved internal plan；测试不得以 direct `Session.add()` 代替生产接口完成性。Ozon read/write worker 只能由 server-issued exact-scope lease handle 获得短期 credential material，并交叉验证 platform/account/adapter/version/capability/epoch/fingerprint/purpose/expiry 与 fresh official readback；全局环境凭据只能是 legacy implemented_unverified，不能生成 verified native/write-ready。Agent 不得提交为人类、自审、自批、发 Permit、取 secret、联系 provider 或外写；外部 mutation 继续 policy-only。`CanonicalWorkerCredentialGrantIssuer` 已在 Pilot Allocation 与 post-`begin_write_attempt` 两个 canonical 事务内派生并签名一次性 grant（仅 source id 由调用方提供，scope/account/fingerprint/capability/hash 全部服务端派生），未绑定 managed lease source 时 fail-closed 且零 grant 落库。0084 + `SqlManagedCredentialLeaseStore`/`SqlManagedCredentialLeaseBindingSource` 提供受管 store 权威，`build_channel_worker_runtime` managed 组合把 server-bound resolver + workload identity + worker client builder 绑给 read/write Ozon worker（缺配置 fail-closed、不读 OZON_*），真实 Postgres 回放通过但 live store 仍 0 行；`test_worker_grant_negative_proofs.py` 已在 worker 工厂边界证明伪造/重放/跨 scope/过期/吊销/漂移/stale grant 全部 fail-closed（builder 零调用、`httpx.Client` 零构造、失败 grant 不被部分消费）。`ProviderReadbackVerifier`（kjds-provider-readback-verifier-v1）校验官方只读回读的 origin/完整性/身份指纹/scope/新鲜度/独立身份并输出 content-addressed observation；`scripts/capture_ozon_readback.py` 以显式意图执行有界官方探测（probe 凭据非 runtime-attested、永不能过 worker 工厂）。真实 product-read 回读成功（offer `2105343364UB`，bundle sha256 `67b473fb…`，verifier passed）、finance-read 回读 403（身份无 finance 权限）。`LeaseProvisioningSeam` + `scripts/provision_channel_lease.py` 完成把 verified readback 固化为权威 lease 的供给工作流（重验 verifier、冻结观测时间、防指纹/摘要/观测哈希漂移、拒绝覆盖）。`SqlManagedStoreRuntimeIdentityVerifier` 已把 live 0084 managed lease store 接入 API runtime identity 投影（0 行 no_data、stale/blocked fail-closed），API 容器重建至 0084 head 且 healthy，Graph/Harness 真实观测 `133 tasks / 266 nodes / 259 edges / 489 observations`（`task-bas160-managed-store` passed、`task-bas160-production-binding` failed）；真实渠道账户授权/实体绑定/finance 权限仍缺失、live store 0 行，故 lease 无法供给、worker 生产执行继续关闭。详见 [ADR-0081](../adr/ADR-0081-canonical-channel-account-governance-state-machine.md) 与 [BAS-160 Evidence](evidence/20260801_BAS_160_CHANNEL_ACCOUNT_GOVERNANCE.md)。 | P0 |
| BR-136 | 币种安全的利润真相、全量侦察 Bundle 入库与利润指挥中心 | 新利润链路中的每个金额必须使用 `MoneyAmount(amount/currency/occurred_at/evidence_id)`，任何跨币种计算必须绑定可回查 `FxBasis`；商品、市场、采购、物流、佣金、应计、结算和银行金额保留原币种，`scenario/accrual/settlement/cash` 利润永久分离。已发现的 CNY/RUB 混算报告必须标记 invalidated 并退出所有决策输入。唯一 `MarketReconBundleIngestion` 复用现有 Evidence/Observation/Catalog/Fact/Import 权威，全量保存 Ozon Catalog/Product/Analytics/Finance、1688 品类和 Browser Capture；质量不足不删除而进入带原始位置与稳定错误码的 quarantine，且 `accepted + quarantined = source_total`、exact scope、幂等、同键内容漂移冲突、预检零写入。唯一 `ProfitCommandWorkspace` 组合既有 Batch Opportunity、Actual Profit、Settlement、OMS、Inventory、Sourcing 与 Growth 权威，严格分开实际/预测/风险利润，输出 SKU 动作、阻断、FX/Evidence 下钻和不可变 `ProfitDecisionSnapshot`；只有证据齐全且 downside CM3 为正才允许 proposal-only Pilot，Agent/UI 不得晋升 Fact、自批、发 Permit 或外写。详见 [ADR-0084](../adr/ADR-0084-profit-truth-bundle-ingestion-and-command-center.md) 与 [当日决策记录](20260802_PROFIT_FIRST_COMMERCE_OS_DECISION_RECORD.md)。 | P0 |
| BR-137 | 全量级卖家利润增长 OS、店铺属性与多级类目路由 | 唯一 `StoreCategoryStrategyWorkspace` 必须在 exact tenant/entity/store/Scope Grant 下保存证据化、append-only 店铺经营属性，组合 Profit Command 候选而不复制 Product、Category、Profit 或 Listing 真源。店铺定位、铺货/精铺模式、价格带、区域、履约、渠道与能力必须和 Ozon 官方 L1/L2/L3/叶子类目、product type 分层保存；季节、重货、配件、内容型等衍生标签只选择打法与门禁，不能成为官方类目。路由优先级固定为 exclusion→exact leaf→product type→official hierarchy→needs data，输出 core/adjacent/experimental 角色、research/pilot/growth/exit 生命周期、商品/流量/库存打法、预算/止损和跨店交接建议，全部 proposal-only。服务端扩展候选分页、分析、血缘和多店组合投影，同利润口径/币种/Evidence 齐全才聚合，跨店现金不猜加、无历史不造趋势。Web 交付利润总览、商品列表、SKU 详情、店铺类目路由和 Evidence 血缘五页，前端不计算利润。个人至集团共享真相与利润内核，只由配额、自动化、审批和 SLA 区分。详见 [ADR-0085](../adr/ADR-0085-store-category-profit-growth-operating-system.md)。 | P0 |
| BR-138 | 全量社媒卖家情报、用户分析与 campaign 运营 | 唯一 `SocialCommerceIntelligenceWorkspace` 必须在 exact tenant/entity/store/account/as-of 下组合官方授权 API/导出、经营者选择的 CLI、专用浏览器公开或可见页与人工 Evidence，并按来源阶梯降级而不猜造字段。对选定来源默认获取全部可用页、字段和时间窗口，保存 checkpoint、覆盖率、失败页与 `accepted + quarantined = source_total` 守恒；原始、规范、分析、实验、动作和经营结果分层，按 actor/content/comment/product/time 建时序关系并支持卖家分群、公开或获授权用户分析、主题/钩子/评论意图/节奏/漏斗与变化检测。发布、更新、删除、评论、回复、点赞、收藏、关注、私信、获授权下载和账号操作不得被产品全局移除，必须由带账号、动作集、预算、有效期、停止条件、幂等与回读的 `CampaignGrant` 批量授权；验证码交给经营者处理，凭据不进入 Agent、Git 或 Evidence，跨客户原始数据不混用，互动不冒充销量。Adapter 失败必须依次检索官方文档、源码、Issue、Release、Fork 和替代实现，并把修复形成 Eval/SkillCandidate。详见 [ADR-0090](../adr/ADR-0090-governed-social-commerce-intelligence-and-platform-operations.md) 与 [社媒运营系统](15_SOCIAL_COMMERCE_INTELLIGENCE_AND_OPERATIONS.md)。 | P0 |
| BR-139 | 俄罗斯市场需求与热点事件全量雷达 | 唯一 `RussiaMarketIntelligenceWorkspace` 必须组合 Ozon/Wildberries/Yandex Market 授权站内数据、Yandex Wordstat 地区/时间搜索需求、Telegram/VK 公开或授权讨论、平台官方变更及俄罗斯宏观/贸易/物流事件，不复制 Product、Order、Finance、Profit、Campaign 或 Fact 真源。每个来源必须全分页、全字段、请求时间窗历史回补、checkpoint/resume、失败页和 `accepted + quarantined = source_total`，记录来源自身的条数/订阅/权限上限而不增加内部抽样上限。需求、价格促销库存评价、社媒传播、平台规则、汇率通胀与供应事件分维度保存；热点评分必须分解权威、时效、速度、跨源数、实体相关度、利润/供应暴露与真实市场响应。单条帖子、搜索激增或新闻不得直接成为销量、利润、采购、广告或发布事实；商品、内容、软件 JTBD 和风险机会分别引用各自 owner。详见 [ADR-0091](../adr/ADR-0091-russia-market-demand-and-event-radar.md) 与 [俄罗斯雷达](16_RUSSIA_MARKET_DEMAND_AND_EVENT_RADAR.md)。 | P0 |

| BR-140 | 全球跨境专家委员会与首席组合调度 | 唯一 `GlobalPortfolioOrchestrator` 必须从版本化专家注册表编译团队快照与 `ExpertTaskContract`，不得建立第二套 Task、Fact、Finance、Evidence、Approval、Permit 或审计真源。团队固定采用 AI 核心+真人专业复核、全球研究+俄罗斯/Ozon 首战区、一名总负责人业务拍板+L3/L4 高风险双签；总负责人可定目标、优先级、内部预算、WIP、继续/暂停/退出并随时 Stop，但不得自审自批、替代法务/财务/合规/发布 Gate、签发 Permit、持有平台凭证或强制失败 Gate 放行。十二个有界专家席位必须有唯一责任、作用域、SLA、工具/数据白名单、Evidence handoff、独立 Reviewer、真人复核条件和替补人；未绑定当前真人 Owner 时只能 proposal/shadow。全球非 RU/Ozon 任务保持 research-only；俄罗斯/Ozon 的 L3 也只能返回双签与执行路线，本模块永远不直接外写。详见 [ADR-0095](../adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md) 与 [运行合同](17_GLOBAL_CROSS_BORDER_EXPERT_TEAM.md)。 | P0 |
| BR-141 | Exact-scope 团队总控塔与唯一下一动作 | 唯一 `TeamControlTower` 必须把“项目总控与商业化、SKU 闭环、双轮商业化、LG-001 Exact-scope”四条用户主线编译为当前 authenticated tenant/entity/store/authority hash 下的领导者 `brief`，且任何时刻最多公开一个状态绑定的下一动作。`advance` 只接受 opaque continuation、有限结果、理由、Evidence IDs 与幂等键；过期 continuation、跨 scope、同键内容漂移、无 Evidence 的完成/停止、角色越权和注册表/泳道漂移全部失败关闭。运行写入只复用既有 OperatingTask/Event 权威，不创建第二任务、Fact、Finance、Approval、Permit 或审计账，不持有凭据或外写；Kill Switch 生效时推进接口必须关闭。总负责人可领取、开始、完成、阻断、升级或停止内部协作，但真人任命、高风险双签、硬 Gate 和外部 Executor 权威不被替代。详见 [团队总控运行手册](18_TEAM_CONTROL_TOWER.md) 与 [ADR-0095](../adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md)。 | P0 |
| BR-142 | 90 天 Top1 大型团队总控与五类权威投影 | `TeamControlTower` v1.1 必须在保留唯一 `brief/advance` Interface、A–M 泳道及 OperatingTask/Event 真源的前提下，把 18 个核心角色、12 个 AI 专家、20–40 人专家池容量与 5 个独立控制角色编译为机器可验证但不证明真人到岗的组织合同。`brief` 必须只在 exact scope 通过后读取并投影 `organization_readiness`、四阶段 `critical_path`、12 维 `top1_scorecard`、`cash_at_risk` 与五个 `delivery_gate`；统一使用 `VERIFIED/PARTIAL/BLOCKED/STALE/CONFLICTED/UNKNOWN`、reason code、source ref、as-of 与投影哈希。Top1 只能只读映射最新同 scope `StrategicBenchmark` 既有比较组，不重排；少于 5 个合格 peer、数据过期、重复最新组或 authority drift 必须失败关闭，且 `global_top1_claim=false`。期初余额、CashPlan、FX、现金底线或最大损失缺失时不得猜测 13 周现金。日历、泳道或任务完成不得替代正式 Gate PASS。五类投影共同进入 `decision_basis_sha256`，任一人员、现金、Benchmark、Gate 或泳道变化必须使旧 continuation 失效。当前切片不得新增数据库迁移，BAS-204 继续独占 `0096`；工程交付只能标记 `DONE_ENGINEERING`，真人、现金、SKU、客户和 Top1 保持外部 Evidence Gate。详见 [ADR-0095](../adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md)、[运行手册](18_TEAM_CONTROL_TOWER.md) 与 [LG-002 Evidence](evidence/20260807_LG_002_TOP1_TEAM_CONTROL.md)。 | P0 |
| BR-143 | 90 天 Campaign 运行调度与 SKU 现金归因投影 | `TeamControlTower` v1.2 必须在不增加外部 Interface、数据库表、迁移或平行任务账的前提下，把四阶段 Campaign 运行协调复用到 exact-scope `OperatingTask/Event`。首阶段 `start` Event 只有绑定当前 scope Evidence 时才形成不可变 kickoff；实际战役日从该 Event 计算，不能从计划日期、任务状态或系统时钟倒推。阶段任务 `resolve` 只证明工作交接，不证明正式 Gate PASS；无匹配的 canonical Gate authority 时不得自动打开下一阶段。`brief` 只读消费现有 `ScopedSettlementCashWorkspace`；同一 cycle 除订单 Fact、平台结算、银行现金、`reconciled` 和 Actual Cash CM3 外，还必须由严格同 scope/current-authority 的 order-grain `ScopedProfitLedgerAuthority` 发行并独立回读验证 `canonical_order_sku_receipt_v1`，把唯一 Order Fact、canonical `product_id + sku`、稳定 Profit row basis 与现金守恒绑定，才可把独立的 `single_sku_attribution_status` 投影为 `VERIFIED`。语义 lineage 排除观测 `as_of` 与顶层 Profit snapshot；相同业务在 T/T+5 保持 continuation，相反任何 order/Product/SKU/row/authority 变化必须失效旧 continuation。只有 source=`ready`、完整单页、无 excluded/gap/blocker 且 `order_count=identity_count=1` 时验证计数才可非零。兼容既有老板页“真实 SKU 现金闭环”语义的外层 `actual_cash_truth.status` 与俄罗斯经营 readiness 必须保持 `PARTIAL/UNKNOWN`，直至 Ozon offer 映射和退货退款观察窗终结均由独立权威证明。普通 reconciled cycle、缺 SKU 的 adapter、混合 Product/SKU、自报 native capability 或弱/异常 Profit receipt authority 不得晋级。此归因不证明 13 周现金、现金底线、最大损失或正式 Gate；对应事实继续 `BLOCKED_EVIDENCE`。exact scope 失败时任务、Benchmark 和现金权威均不得读取。 | P0 |
| BR-144 | 全域 AI ERP 六投影与总控决定基线 | `TeamControlTower` v1.3 必须通过具名、只读 `EnterpriseAiErpProgram.project()` 依赖，在既有 `brief` 中增加 `squad_readiness`、`role_conflicts`、`parallel_execution`、`integration_queue`、`capacity_risk` 和 `next_release_train`；不得公开通用插件注册表、增加命令总线或改变 `advance`。六投影只能白名单编译 BAS-215A 已验证的结构合同，整体状态保持 `UNKNOWN`，不得把静态合同完整性、验收条件、并发上限、WBS DAG 或每周两次集成列车误报为真人到岗、运行容量、任务完成、Gate PASS 或发布排期。exact scope 失败时不得调用 Program；Program 缺失时显式 `UNKNOWN`，版本、source bundle、snapshot、动态真相或 authority envelope 漂移时失败关闭。Program registry/source bundle/snapshot 与六投影哈希必须进入 `decision_basis_sha256`，语义变化使旧 continuation 失效，单纯 `as_of` 变化不得失效。runtime 只实例化并注入，不新增 DB/migration/router/API/OpenAPI/Web/G1 或外写。详见 [ADR-0095](../adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md)、[运行手册](18_TEAM_CONTROL_TOWER.md) 与 [BAS-215B Evidence](evidence/20260808_BAS_215B_ENTERPRISE_AI_ERP_TEAM_CONTROL_PROJECTION.md)。 | P0 |
| BR-145 | 全域 AI ERP 六投影的严格 API 与老板工作台 | `GET /v1/team-control/brief` 必须以严格、禁止额外字段的完整响应模型公开现有摘要及 BAS-215B 六投影，保存的 OpenAPI 200 响应必须引用该模型并把六字段列为 required；不得继续以任意 object 隐藏契约漂移。scope-invalid、Program 缺失和未连接运行权威时仍返回结构化 `UNKNOWN`，不能因序列化默认值晋级状态。`/team-control` 必须逐一显示六个服务端投影、reason code、Program snapshot 与运行权威未连接声明；Web 只能格式化服务端顺序和值，不得计算 Owner、成熟度、容量、依赖、发布候选、Gate 或排期。页面必须支持键盘、语义标题、状态播报与 390px 无横向溢出。`advance` 输入、幂等、权限、决定哈希和外写边界保持不变；本切片不改 Tower/Program/runtime，不新增数据库、迁移、依赖、G-1 或外部权限。详见 [ADR-0095](../adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md)、[运行手册](18_TEAM_CONTROL_TOWER.md) 与 [BAS-215C Evidence](evidence/20260808_BAS_215C_ENTERPRISE_AI_ERP_TEAM_CONTROL_API_WEB.md)。 | P0 |

BR-082 精确身份补充门禁：任一身份字段或变体仍为
`unknown/unspecified/pending/未确认` 等占位值时，不得生成或复用匹配键；历史观察在
扫描时同样失败关闭为 `observe/no_match`，不得为扩大候选数而猜配。已冻结类别身份
schema 时必须满足全部必填维度；桌下理线架至少绑定数量、结构、安装方式、长宽高和颜色。

### 2.2 功能需求

#### A. 经营驾驶舱

- 展示现金安全线、贡献利润、库存覆盖、账号风险、证据缺口和待审批事项。
- 默认只推送“今天必须决定的事项、最大风险、最高价值机会”；低风险项进入日终汇总。
- 每个异常链接原始事件、证据、责任人、建议动作和回滚方案。

#### B. SKU Episode 与 Passport

- `Global Product ID` 连接供应商货号、Ozon offer、版本、包装、认证和生命周期。
- Product / Compliance / Quality 三类 Passport 只可追加版本，引用不可变证据和哈希。
- 缺失、过期、冲突或不可验证的硬事实标记 `UNKNOWN`，禁止模型补写。

#### C. 采购与供应链

- 报价、样品、包装测试、物流方案和备用供应商全部证据化。
- 报价、利润场景和采购申请具备幂等键、双人审批、风险预算和历史不可覆盖。
- 供应商绩效记录价格、交期、质量、履约和备用方案可用性。

#### D. Ozon 与平台接入

- 官方 API/报表优先，浏览器自动化只能受控兜底。
- 连接器输出 Canonical Product、Inventory、Order、Shipment、Settlement、Ad Campaign。
- 第一阶段 `ozon-product-read-v1` 只允许调用 `/v3/product/info/list` 与版本化商品属性端点；请求单个 offer 时，两个响应都必须恰好命中同一 offer，不能把空响应、批量串组或其他商品误记为本 SKU 事实。
- 只读 Worker 只向控制面回传脱敏计数、合同版本、状态 SHA-256 和错误码；完整响应只进入与 run 绑定的不可变 Evidence，Candidate Claim 仍需独立复核。
- 未经 G6 放行的写操作在连接器层和 API 层均拒绝。

#### E. 内容与 Listing

- Listing 草稿只能由已验证事实生成；语言、图片、属性、变体、版权和合规声明分别审核。
- 生成内容与事实来源建立血缘；不得凭空补重量、材质、认证、交期或功效。
- 商品图片不得由文本凭空重建商品本体。主图、细节图、场景合成和信息图必须引用已批准 Passport 中的真实样品图或已授权供应商原图，以及独立素材权利证据。
- 原图入口只接受 JPEG、PNG、WebP；权利文件只接受 PDF、TXT、JPEG、PNG。服务端必须校验声明类型与文件签名，记录 SKU、变体、七类图片角色、来源类型、权利证据 ID、SHA-256、`effective_at` 和上传人。
- 每次原图上传都追加 Quality Passport 草稿并继承已有证据；审核前状态为“已捕获待 Passport”，不能被 Content Agent 或图片工作流使用。七类角色为 `front_main`、`back`、`side`、`detail`、`accessories`、`packaging`、`scale_reference`。
- Content Service 创建任何图片 Brief 前必须同步读取商品图片 readiness；仅当七类角色均存在有效的原图—权利证据配对、且最新三类 Passport 全部获批时放行。Brief 引用的每张原图必须携带其精确配对的权利证据，不能用同一份无关授权替代。
- 图片 Brief 只允许 `retouch`、`composite`、`infographic` 三种受控模式并锁定商品事实；生成结果以不可变 Evidence 保存，记录来源图片、处理方式、生成时间和内容资产 ID。
- 首个自动执行模板固定为 `ozon-retouch-v1`：只使用官方核心节点载入已批准原图、按总像素等比缩放并保存，不运行生成模型、不改变商品结构、颜色、配件或文字。`composite` 与 `infographic` 在真实 SKU 模板复验前只允许建立 Brief，不允许自动执行。
- 图片执行状态持久化在 ContentAsset：`brief → queued → generated → approved/qa_failed`，执行错误进入 `execution_failed` 后才可重试。必须记录执行器、模板版本、外部 prompt ID、来源证据、请求人和时间；重复排队不得产生第二个 prompt。
- 图片批准除通用五项 QA 外，还必须通过商品外观/配件一致性、来源血缘和俄语文字/参数准确性检查；任何一项失败均退回，不得进入 Listing 草稿。
- QA 请求必须恰好覆盖适用检查项，拒绝缺项、重复项和未知项。每项必须包含 `passed` 与非空审核说明；可附加不可变 Evidence ID。审核人和审核时间由可信服务端身份与 UTC 时钟写入，客户端不得自报。
- Ozon Listing 草稿的 `images` 必须全部来自请求中明确列出的、同一商品且状态为 `approved` 的图片 ContentAsset 产物证据；草稿保存内容资产 ID 作为血缘。创建草稿仅建立 `listing.publish` 待审批对象。仓库已有 `apps.control_plane.ozon_worker.OzonExecutionWorker` 平台写执行器，并已完成批准草稿到受控执行计划的工程接线，但运行时受 Gate/Kill Switch/一次性许可约束且默认关闭，当前仅通过 mock/合同验收，尚未完成真实账户验收；不得把审批请求、执行计划或注册表 `availability=enabled`（仅表示工程能力存在）解释为已发布或可在真实账户运行。
- Listing 草稿审批摘要以 `product_id`、`offer_id`、`scenario_id`、`target_platform` 和完整 `listing_data` 的规范 JSON 计算 SHA-256；不得包含草稿 ID、审批 ID、请求时间等非内容字段。审批 payload 必须保存该摘要和可读的标题、类目、CM3、图片资产 ID、图片产物证据，供独立审批人确认“审批的是哪一版”。
- Listing 审批视图必须明确展示“平台未写入”，不得提供绕过独立身份、快照复核和后续执行门的快捷发布按钮。
- 批准 Listing 时必须从持久化存储重新加载草稿并复算 SHA-256；摘要缺失、草稿不存在、审批资源不匹配或摘要变化均失败关闭。拒绝请求不产生发布风险，可直接记入审批账。
- Listing 草稿只记录创建态与 `approval_id`；批准/拒绝结论读取 Approval 账，不在两个表之间维护易分叉的重复状态。后续执行必须另外建立受控执行对象、回读和回滚，不能直接消费草稿状态。

#### F. 财务

- 费用字典、FX 版本、结算周期、退款/补偿/广告分摊和银行到账均需来源和日期。
- 金额使用 Decimal/币种，不用浮点；无法解释的费用进入未知队列。
- 贡献利润覆盖售价、采购、平台、广告、履约、退款、损耗、税费、汇兑、资金和售后成本。

#### G. 因果实验与知识

- 实验注册先记录假设、随机单位、干扰、主指标、最小商业效果、预算和停止条件。
- 自动检查 A/A、SRM、埋点、样本污染、库存、时区、币种、退款滞后和多重检验。
- 结果同时记录短期、中期、长期指标，蚕食、现金、风险和外部有效性。

### 2.3 非功能需求

| 类别 | 要求 |
|---|---|
| 安全 | API 默认鉴权；写接口 endpoint 级最小角色；专用身份隔离；密钥不入库 |
| 一致性 | 命令幂等；事实、证据和审计 append-only；状态转换有合法图 |
| 可审计 | 每个动作可回到 actor、时间、输入哈希、证据、审批和结果 |
| 可恢复 | 备份、迁移回滚、事件重放、租约回收、写熔断和人工接管 |
| 性能 | 读操作有界；批量默认不超过 50 个目标；任务有超时与取消 |
| 可观测 | 健康、错误、延迟、成本、证据缺口和越权次数可查 |
| 可迁移 | PostgreSQL 为事实底座；模型、连接器、工作流可替换 |
| 隐私 | 候选 payload 禁止客户、地址、电话、邮箱、token 等敏感字段 |

---

## 3. 产品信息架构

```text
经营驾驶舱
├── 今日决策 / 异常 / 机会
├── 现金与贡献利润
├── SKU 与库存
└── Gate 状态
证据与事实
├── Evidence Ledger
├── Fact Promotion
├── Read-only Claims
└── Source / Unknown Register
商品与供应链
├── SKU Episode
├── Passport Review
├── Supplier Offers
├── Sample Procurement
└── Logistics / Backup
平台运营
├── Ozon Read-only Pilots
├── Listing Drafts
├── Orders / Returns
├── Advertising
└── Settlement
实验与策略
├── Decision Contracts
├── Causal Experiments
├── Knowledge Registry
├── Policy Shadow
└── Controlled Execution
治理与运行
├── Gate Reviews
├── Roles / API Identities
├── Kill Switch
├── Incidents / Recovery
└── Authority Radar / Health
```

页面只负责展示、路由、表单体验、loading/empty/error 状态和用户交互；业务规则、权限、持久化、证据和事务必须留在后端服务。

### 3.1 五条产品主旅程

当前产品范围按用户必须完成的经营任务验收，不按页面或模块数量验收：

1. 经营负责人查看今天必须决定的事项、风险、资金和阻塞原因。
2. 商品负责人从需求证据完成三候选比较并发起三报价。
3. 供应链与财务完成报价、样品、15 项成本、CM3 和下行情景判断。
4. 内容负责人从真实素材完成图片、视频、QA 和 Listing 草稿。
5. 财务负责人从订单、费用、结算、银行和 FX 追溯实际到账 CM3。

每条旅程必须展示当前状态、下一步、缺失证据、责任角色和 `loading/empty/error/retry`；必须显著区分 `research`、`forecast`、`commitment` 与 `actual`；重大决定必须能查看依据和不可变快照，任何真实副作用必须先获得审批和单次执行许可。页面不得重新计算服务端 Gate、利润、权限或 Evidence 有效性。

五条旅程先用当前 Web 控制台和真实角色演练验收；在形成可测的可用性瓶颈前，不引入第二套产品文档、Figma 设计系统或新的前端框架。

---

## 4. Architecture：系统边界与数据流

```text
经营负责人 / 复核人 / Worker
          ↓ API Key + endpoint role
Control Plane API + Web UI
          ↓
Application Services
  ├── Governance / Gate Review
  ├── Evidence / Facts / Imports
  ├── SKU / Passport / Sourcing / Procurement
  ├── Finance / Reconciliation / Cash Forecast
  ├── Decision / Experiment / Policy / Execution
  ├── Read-only Pilot / Claims / Recovery
  └── Authority Radar / Health
          ↓
PostgreSQL + Alembic + Evidence Blob Store
          ↓
Connector Layer（官方 API/报表优先；Playwright 仅兜底）
          ↓
Ozon（当前经营平台）与未来平台适配器
```

### 4.1 分层责任

| 层 | 负责 | 禁止 |
|---|---|---|
| Web/UI | 展示、交互、路由、表单状态 | 改写业务事实、直接访问数据库、保存密钥 |
| API/Router | HTTP 输入输出、鉴权、角色、错误边界 | 承载长业务编排和数据规则 |
| Service | 领域规则、状态机、事务、证据、审计 | 依赖具体页面或模型输出格式 |
| Repository | 查询、持久化、锁、分页 | 决定产品政策和审批结论 |
| Schema/DTO | 输入输出边界、类型、兼容字段 | 直接替代领域规则 |
| Connector | 外部协议、凭证隔离、Canonical 转换 | 未批准的业务写入 |
| Script/Worker | 有界、幂等、可重跑的任务 | 绕过 API/权限/证据链 |

### 4.2 当前技术基线

| 层 | 选择 | 说明 |
|---|---|---|
| API | FastAPI + Pydantic | 现有控制面、类型合同和鉴权入口 |
| DB | PostgreSQL 17 + SQLAlchemy + Alembic | 事务、约束、JSON、审计和迁移 |
| Web | Next.js | 现有控制台、standalone 非 root 镜像与 G-1 build/runtime 门 |
| AI | 本地模型/OpenClaw 先行；云模型可插拔 | 不让余额或单模型成为单点故障 |
| Image Executor | 官方 `Comfy-Org/ComfyUI` 本地 API | 仅监听 loopback；基线禁用第三方 custom nodes；KJDS 持有 Brief、事实、Evidence、QA 与审批，不向用户开放任意 workflow |
| Browser | Playwright 受控兜底 | API/报表优先，操作须回读 |
| Developer Harness | Codex 主执行；Grok Build 隔离试点 | 只用于工程任务基准、Worktree 和结构化结果，不进入生产控制面 |
| 暂缓 | Temporal、独立向量库、多租户 | G7 前缺乏实证规模或长事务压力 |

### 4.3 外部依赖边界

数据库、对象存储、Ozon、银行、供应商文件、模型、OpenClaw、通知渠道都是外部依赖。每个依赖必须有超时、错误码、降级、重试上限、证据记录和人工接管路径。

---

## 5. Patterns & Abstractions：前后端工程规范

### 5.1 前端目录与规则

```text
web/
├── app/              路由与页面组合
├── features/         业务功能（SKU、Finance、Governance）
├── components/       通用 UI 组件
├── hooks/            可复用交互和查询逻辑
├── services/         API client、query、mutation
├── models/           前端视图模型，不替代后端事实模型
├── utils/            无业务副作用的工具
└── tests/            组件、流程和页面验收
```

- 页面只组合 `features` 和 `components`，不堆积数据变换和权限判断。
- API 请求统一放在 `services`/query 层，禁止组件直接散落 `fetch`。
- 每个异步页面必须有 loading、empty、error、forbidden 和 success 状态。
- 前端只做体验校验；关键校验、权限、金额、日期、证据和状态转换由后端再次执行。
- 表单提交必须带幂等键并显示审批/回滚状态，避免重复点击造成重复命令。

### 5.2 后端目录与规则

```text
apps/control_plane/
├── api.py            Router、依赖、统一错误边界
├── domain.py         标识、值对象、领域枚举
├── <feature>.py      一个明确领域的 service + persistence contract
├── connectors/       外部平台适配器（如扩展后拆目录）
├── sql_repository.py Base、数据库连接和通用持久化
└── providers.py      外部模型/自动化提供方
```

- Router 只处理 HTTP 输入输出；Service 负责业务；Repository 负责数据。
- Schema/DTO 与 ORM Row 分开；禁止把数据库 Row 原样当公共 API 合同。
- 参数验证在 schema 层，领域约束在 service 层，数据库约束在 migration/DB 层。
- 事务边界由 service 控制；跨表写入必须明确 commit/rollback 和审计。
- 异常使用稳定错误码，敏感值不得进入错误消息和日志。
- 新字段、新状态、新索引必须有 Alembic migration 和回滚路径。

### 5.3 前后端 API 合同

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": {"request_id": "...", "schema_version": "v1"}
}
```

错误：

```json
{
  "success": false,
  "data": null,
  "error": {"code": "ROLE_REQUIRED", "message": "...", "details": {}},
  "meta": {"request_id": "...", "schema_version": "v1"}
}
```

分页统一使用 `items`、`page_size`、`next_cursor`、`has_more`；长任务返回 `run_id`/`command_id`，不阻塞 HTTP 请求等待外部平台完成。时间必须带时区；金额必须带币种；状态使用版本化枚举。

### 5.4 状态机原则

状态转换只能通过 service 方法完成，不能由页面或脚本直接更新字符串。每次转换写事件、actor、原因、证据、时间和幂等键；非法转换返回稳定错误码。

---

## 6. 数据模型与事实晋升

### 6.1 核心对象

| 对象 | 关键字段 | 不变量 |
|---|---|---|
| `GlobalProduct` | `product_id`、版本、属性、兼容关系 | 全局身份稳定；Listing 是平台投影 |
| `SkuEpisode` | SKU、生命周期、假设、Owner | 事件幂等；状态可追踪 |
| `Evidence` | 原件、SHA-256、来源、等级、有效期 | 原件不可变；引用可回溯 |
| `FactRecord` | 类型、值、effective/recorded 时间、证据 | 正式事实必须证据化 |
| `ReadOnlyPilotRun` | pilot、operation、target hash、租约、结果证据 | 只读、有界、可回收 |
| `ReadOnlyClaim` | run、payload、state hash、复核、状态 | 独立复核；不自动成为正式事实 |
| `Passport` | product/compliance/quality、版本、证据 | 版本只追加；哈希复验 |
| `SupplierOffer` | 供应商、报价、币种、交期、证据 | 外部报价不覆盖历史 |
| `FinanceFact` | 订单/费用/结算/银行、金额、FX | Decimal、币种、来源完整 |
| `DecisionContract` | 目标、假设、选项、预算、风险、回滚 | 可复盘；结论与证据分开 |
| `ExperimentProtocol` | 单位、处理、对照、主指标、停止条件 | 预注册后才能运行 |
| `GateReview` | owner、approver、风险、证据、决定 | 独立批准；结构化审计 |

### 6.2 事件账本

每个事件记录 `event_id`、`event_type`、`aggregate_id`、`payload_hash`、`occurred_at`、`recorded_at`、`actor_id`、`source_evidence_id`、`schema_version`。业务表只是查询投影，不能删除事件或覆盖原始事实。

### 6.3 事实晋升链

```text
原始文件/API响应
  → Evidence（原件+哈希+来源）
  → Staging Row（版本化校验）
  → Candidate Claim（受限、独立复核）
  → Formal Fact（正式映射+业务批准）
  → Profit / Policy / Listing 使用
```

---

## 7. 核心业务流程

### 7.1 商品准入

```text
提出候选 SKU
 → 建立 Global Product / SkuEpisode
 → 收集 Product、Compliance、Quality Passport 证据
 → 三家报价、样品实测、包装与物流
 → 供应链/合规/财务复核
 → G0/G1 Gate Review
 → 继续、条件继续或淘汰
```

### 7.2 Ozon 只读观察

```text
批准 pilot（operation/targets/limits/lease）
 → pilot_reader 启动 run
 → worker 分页读取官方允许状态
 → 写响应哈希、摘要和 B/C 级证据
 → 完成 run 或租约回收
 → 需要时提出受限 Claim
 → 独立 reviewer 接受/拒绝
 → 后续正式事实映射（不在 claim 接受时自动发生）
```

约束：单批最多 50 个目标；批次键 + 目标哈希幂等；默认租约 15 分钟；过期结果拒绝完成；输出不得泄露客户或原始敏感标识。

首次真实单 SKU Pilot 还必须先执行离线 preflight：它不打开 HTTP 客户端，不查询控制平面，不访问 Ozon，只检查本地运行合同并输出脱敏哈希。操作脚本默认停在 preflight；仅显式执行开关可在预检通过后启动 `pilot_reader` 容器。preflight 不能证明 Pilot 已批准、角色真实最小化或线上响应符合合同，这三项仍由控制平面、账户负责人和原始 Evidence 分别证明。

### 7.3 内容与 Listing

```text
已批准事实/Passport
 → 上传真实样品图/授权原图与独立权利文件
 → 文件签名校验、SHA-256 固化、SKU/变体/角色血缘
 → 追加 Quality Passport 草稿并由独立 reviewer 批准
 → Content Service 复验七类 readiness 与每组原图—权利配对
 → 锁定商品事实的内容 Brief
 → `ozon-retouch-v1` 受控排队、状态同步与输出回收
 → 后续经验证的场景合成/固定模板信息图
 → 输出 Evidence 与来源血缘复验
 → 俄语、商品一致性、事实、IP/素材和合规审核
 → 人工批准
 → Ozon 草稿/受控写入（G6 后）
 → 回读 Listing 与证据
```

### 7.4 订单、结算与现金

```text
Ozon 订单/报表 + 供应链成本 + 物流 + 银行
 → staging 校验
 → 正式事实晋升
 → 订单—费用—结算—银行三方对账
 → 贡献利润/CM3
 → 13 周现金预测
 → 异常队列与复核
```

### 7.5 因果实验

```text
异常/未知
 → 假设与因果图
 → 注册随机单位、主指标、最小效果、预算、停止条件
 → A/A、SRM、数据质量门
 → 影子/小范围实验
 → 增量利润、现金、蚕食、长期副作用
 → 独立复核、复现和适用边界
 → 条件策略/Skill
```

### 7.6 受控执行

```text
Decision Contract
 → Policy / Risk Check
 → Approval（单人或双控）
 → Execution Command（幂等/预算/超时）
 → External Write（仅 G6 允许）
 → Readback
 → Observation Window
 → Receipt / Rollback / Incident
```

Listing 发布的工程链必须以已批准草稿为不可变来源，服务端从草稿派生 Ozon `item`、目标 SKU、回滚补丁和前置状态，不接受 Web 自报适配器、目标或 patch。执行计划另行申请独立 Execution Approval，并冻结 Listing Approval、草稿摘要、当前 readiness、原件 Evidence 与组合风险。

`listing_publish` 在批准草稿来源下必须同时复验真实需求范围、Listing 摘要、三类 Passport、俄语母语复核、八项图片 QA、全成本完整性、正 CM3、实际成本权威证明、商品—报价—场景绑定、已接受的 Ozon 写前只读 Claim、专用最小权限执行身份和 Kill Switch。俄语复核与执行身份复核都必须由非提交者固化为不可变 Grade A Evidence；任何拒绝、过期、损坏、血缘缺失或内容变化均失败关闭。

Worker claim 和实际写入前必须重新运行同一授权与 readiness；一次性 permit 只允许一个写入尝试。Ozon 完整响应先以脱敏封装固化，再记录任务 ID、状态轮询和写后回读；租约过期、远端结果不明或证据不完整进入 `uncertain`/Incident，不得猜测成功。回滚必须建立独立命令、再次授权并回读，不得原地改写原命令或历史 receipt。

---

## 8. API、身份与安全

### 8.1 身份模型

`X-KJDS-API-Key` 由 `KJDS_API_KEYS_JSON` 或单键配置解析为 `actor_id + roles`。未配置时控制面 fail closed；密钥只进环境/密钥管理，不进源码、日志、证据或提交。

#### 8.1.1 交互式 Web 会话边界

- 当前单密钥 Web 代理仅可作为本地 `operator` 会话，不具备独立批准权限。
- 浏览器不得接收、选择或提交控制面 API 密钥；前端显示的角色也不得作为授权依据。
- 独立审批界面必须接入服务端验证的用户登录会话，由登录主体映射到单一 `actor_id` 和最小角色集。
- 运营人与审批人的认证主体、会话、审计 actor 和密钥材料必须独立；同一浏览器可重新登录，但不能在同一会话中自行切换到 `approver`。
- approver 会话必须由服务端复验为 Supabase AAL2；TOTP 因素的注册、challenge 和 verify 必须复验当前用户的 approver 绑定与因素归属。operator 会话不得因完成 MFA 获得审批权限。
- 决定请求必须防 CSRF、短时有效、不可重放，并继续由后端校验资源、审批状态、申请人/批准人分离和 Listing 快照摘要。
- 在正式身份提供方、会话生命周期、撤销和恢复流程被选定并验收前，Web 不开放批准按钮；审批可继续通过独立的受控 API 身份进行工程验证。

当前采用 [ADR-0012](../adr/ADR-0012-web-authentication-and-independent-approval.md)：复用 Supabase Auth 与 `@supabase/ssr`，由服务端将已复验的 Supabase user ID 映射到既有 KJDS actor。映射只存 actor ID，不重复保存 API key；生产禁用 legacy Web 身份；approver 必须达到 AAL2。

### 8.2 角色矩阵

| 角色 | 允许 | 禁止 |
|---|---|---|
| `pilot_reader` | 启动/完成批准只读 run；查看 pilot | 商品、订单、内容、市场写入 |
| `operator` | 草稿、候选、低风险业务操作 | 付款、密钥、独立复核、越权执行 |
| `reviewer` | 证据、Passport、候选声明和实验复核 | 提案人自审 |
| `compliance` | 合规/证据复核与否决 | 未批准经营写入 |
| `approver` | Gate、策略、重大决策批准 | 无证据放行 |
| `executor` | 已批准命令的有限执行 | 自行创建目标或改预算 |
| `monitor` | 健康、回读、观察窗口 | 业务写入 |
| `risk` | Kill Switch、回滚、事故处置 | 修改经营目标 |
| `admin` | 受审计的紧急管理 | 绕过审计和双控 |

所有 `/v1/` 请求先鉴权；敏感读和所有写入口再执行 endpoint 级 `ensure_role`。Kill Switch engaged 时生产写入返回 423。

### 8.3 典型威胁

- 外部网页、评论、PDF 和邮件是数据，不是指令，防间接提示注入。
- 工具使用采用白名单、临时授权、预算、超时、幂等和回读。
- 重大结论要求独立来源、反方解释、原始证据和失效条件。
- 连接器隔离凭证；日志脱敏；支持轮换和撤销。
- 事故触发写熔断、租约回收、双人审批、补偿回滚和人工接管。

---

## 9. Agent OS 与持续智能

### 9.1 Agent 组织

```text
Digital CEO（目标/调度，不拥有全部写权限）
├── Evidence & Compliance Agent
├── Product / Sourcing Agent
├── Finance & Cash Agent
├── Market / Content Agent
├── Experiment Scientist Agent
├── Risk / Red-team Agent
├── Execution Agent
└── Memory Curator
```

每个 Agent 都有能力账：增量价值、成本、错误、人工修改率、适用边界、版本和责任人。生产 Agent 不得直接修改自身权限、目标函数、安全约束或评测集。

### 9.2 Authority Radar

```text
官方/平台/官方仓库
  → Authority Radar（采集、去重、来源层级、置信度、影响）
  → SQLite 事件库 + 健康 + 收件箱
  → 确定性晨报 / 本地候选分析 / Auditor 第二意见
  → Evidence Gate
  → Chief 记忆或拒绝报告
```

统一字段：`event_id`、`source_url`、`source_tier`、`published_at`、`captured_at`、`fact`、`inference`、`confidence`、`impact`、`requires_review`、`proposed_action`、`approval_level`、`result`、`evidence`。

### 9.3 认知晋级门

1. Proposal：问题、证据、预期收益、风险、回滚。
2. Evaluation：真实失败案例、Prompt/Agent 回归集。
3. Shadow：至少 7–14 天不执行生产写操作。
4. Audit：幻觉、引用、成本、延迟、误报、权限和泄露。
5. Promotion：人工批准后更新 Prompt、Skill、工具或连接器。

---

## 10. Review 与 Verification 验收体系

### 10.1 三个审查层级

| 层级 | 时机 | 目标 |
|---|---|---|
| 本地变更审查 | 提交前 | 快速发现本次 diff 的明显错误和越权 |
| PR/团队审查 | 合并前 | 判断需求、架构、长期可维护性和模块影响 |
| 周期性健康审查 | 每周/月/Gate 前 | 发现技术债、重复实现、依赖漂移、监控缺口 |

### 10.2 七个审查维度

1. 需求与验收对齐：是否实现 Spec，而不是臆测需求。
2. 行为正确性：正常、失败、空值、边界、重试、幂等和恢复。
3. API/数据合同：字段、类型、状态、分页、时间、币种、向后兼容。
4. 权限、安全与隐私：身份、越权、注入、敏感数据和日志脱敏。
5. 架构与可维护性：模块职责、依赖方向、是否重复造轮子、复杂度税。
6. 可靠性与性能：事务、锁、并发、超时、降级、重试和资源清理。
7. 可测试与交付完整性：迁移、测试、监控、文档、回滚和部署是否同步。

### 10.3 Review 与 Verification 的区别

| 对比 | Review | Verification |
|---|---|---|
| 核心问题 | 设计和实现是否合理、安全、完整 | 代码是否通过明确检查和可重复测试 |
| 方式 | 人/Reviewer/Agent 的语义和工程判断 | 测试、Lint、Type Check、构建、脚本 |
| 结果 | 概率性、依赖上下文 | 确定性、可重复 |
| 典型发现 | 需求偏差、架构腐蚀、权限风险 | 测试失败、类型错误、构建失败 |

两者互补。测试通过不能证明做对了，Review 通过也不能替代可重复验证。

### 10.4 Finding 状态

| 严重度 | 含义 | 处理 |
|---|---|---|
| P0/Error | 严重缺陷或不可接受风险 | 必须修复，禁止放行 |
| P1/Warning | 重要风险 | 原则上修复，或明确批准和期限 |
| P2/Suggestion | 改进建议 | 可修复或转技术债 |
| Info | 背景信息 | 不影响放行 |

处理方式：`auto-fix`、`ask-user`、`defer`、`no-op`；每个 finding 记录文件、行、原因、证据、Owner、状态和复核结果。

---

## 11. Gate 路线与放行标准

| Gate | 目的 | 退出证据 | 状态来源 |
|---|---|---|---|
| G-1 | 可信工程基线 | 当前迁移 head 的升级/回放、隔离恢复、核心质量门、API/Web/PostgreSQL smoke | 动态状态只见任务真源 |
| G0 | 合法启动 | Owner/RACI、风险预算、Ozon 权限、3 SKU 红线 | 动态状态只见任务真源 |
| G1 | 商品与证据准入 | 3× Passport、报价、样品、包装、物流、合规人工批准 | 动态状态只见任务真源 |
| G2 | 内容与草稿 | 事实锁定、俄语/IP/素材审核、草稿回读 | 动态状态只见任务真源 |
| G3 | 小批量履约 | 采购、发货、签收、退货/异常证据 | 动态状态只见任务真源 |
| G4 | 到账与利润 | 订单—结算—银行对账、CM3、13 周现金 | 动态状态只见任务真源 |
| G5 | 影子实验 | 14 天影子、因果质量、建议质量和风险门 | 动态状态只见任务真源 |
| G6 | 低风险受控执行 | 命令、审批、执行、回读、回滚、故障注入 | 动态状态只见任务真源 |
| G7 | 三 SKU 可复制 | 三 SKU 同口径结果和复盘 | 动态状态只见任务真源 |
| G8 | 扩展 | Build/Buy/Partner、第二平台/国家和风险预算 | 动态状态只见任务真源 |

依赖：`G-1 → G0 → G1 → G2 → G3 → G4 → G5 → G6 → G7 → G8`。可以提前准备模板，不能提前宣告后续 Gate 通过。

每个 Gate Review 必须记录 `requirement_id`、owner、独立 approver、参与人、风险预算、最大损失、退出条件、回滚方案、证据 ID、决定、理由、时间和复审触发。

---

## 12. 部署、运行与恢复

### 12.1 本地开发

```text
PostgreSQL（Docker Compose）
API（uv run / FastAPI）
Web（Next.js）
Ozon read worker（独立身份）
Authority Radar / OpenClaw（本地运行）
```

### 12.2 质量门命令

```powershell
uv run ruff check apps migrations tests scripts
uv run pytest -q
uv run python -m alembic upgrade head
./scripts/verify-g1.ps1
docker compose config --quiet
git diff --check
```

### 12.3 24×7 真实含义

当前 Windows Task/OpenClaw 只能保证“本机开机且用户环境可用期间持续运行”，不是托管 24×7。M7 前必须补 VPS/NAS、备份、告警、SLO、故障演练和人工接管；不能把本机 Task 的 PASS 写成生产承诺。

### 12.4 恢复顺序

1. Engage Kill Switch，停止所有生产写入。
2. 保留事件、日志和原始证据，禁止清理事故证据。
3. 回收过期租约和未完成命令。
4. 校验备份、迁移 head、连接器版本和身份配置。
5. 用回读和对账确认外部平台状态。
6. 风险负责人和独立 approver 决定恢复或补偿回滚。
7. 记录事故原因、影响、责任、修复和复演结果。

---

## 13. 历史实现证据索引（非动态状态）

本节只保留当时版本的实现与经营阻塞背景，不维护当前迁移号、测试数量、任务状态或下一执行队列。当前状态、Owner、依赖和下一动作只见 [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md)；本地最新验证只见 `.runtime/G1_VERIFICATION.json`。

### 13.1 历史工程基线

- 当时的 Alembic head `20260720_0038` 已在真实 PostgreSQL 完成迁移回放和隔离恢复；此前 `20260718_0036 → 0035 → 0036` 回滚演练及受控 ComfyUI 队列/历史/下载烟测作为历史证据保留。ComfyUI Prompt `f0d6cec6-a436-456f-901b-d70363c4e28e` 成功产生 PNG，但只证明当时的技术合同，不代表任何 SKU 素材、商品视觉或 Listing 已获批准。
- 该次验证包含迁移回放、隔离备份恢复、Lint、当时的测试与构建、API/Web 镜像、健康检查、Kill Switch、Evidence、Outbox、连接器和受控执行链。精确数量与结果只属于对应证据版本，不作为当前状态来源。
- BAS-065 已将 Gate requirement 阻断与真实 SLA 运行工作同屏展示：资料/证据缺口直接复用服务端 readiness，提供稳定来源、当前/目标、责任角色与下一动作，但不伪造发生时间或截止时间；事故、受限执行与观察窗口继续使用既有运营队列。异常中心只读，不自动补证、关闭事故、释放 Kill Switch 或执行平台写入；验收见 `docs/project/evidence/20260720_BAS_065_EVIDENCE_BACKED_EXCEPTION_WORKSPACE.md`。
- BAS-058 已增加 Ozon 原始财务文件无状态预检：正式存证前返回文件哈希、类型、行数、字段映射和缺列，失败不写数据库/Evidence/事实/映射，也不要求操作员改动原件；正式导入重新执行全部校验。2025 年 10 月真实计提原件现已形成 Evidence `evd_902fe12a454e4703b88b6ad7314ed652` 和 import `imp_76eab9701e954896a6f67ccdbb845cb6`，15/15 行、Blob/哈希/血缘复验通过；但来源复核仍为 pending，正式事实与财务分录均为 0。验收见 `docs/project/evidence/20260720_BAS_058_OZON_IMPORT_PREFLIGHT.md`、`20260720_BAS_066_OZON_OFFICIAL_ACCRUAL_EXPORT.md` 与 `20260720_BAS_068_OZON_ACCRUAL_FORMAL_PENDING_REVIEW.md`。这不代表已批准来源、会计分类或完成结算对账。
- BAS-059 已把 Evidence 权威等级纳入候选询价门：C/D 级第三方选品、ERP、计算器和探索资料可以保留为观测，但不进入指标聚合、来源族或三报价放行；需求、竞争、供货和退货至少需要 A/B，合规红线需要 A。验收见 `docs/project/evidence/20260720_BAS_059_CANDIDATE_EVIDENCE_AUTHORITY_GATE.md`。这不代表第三方工具已正式接入，也不解除真实需求报告、候选、报价、合规和利润证据阻塞。
- BAS-043 已把候选研究预检开放为非技术操作界面和单次原子 API：五类指标的来源、引用和观测时间由 Evidence Ledger 派生；全部原件复验成功后才一次写入，重复提交复用稳定观测 ID，任一坏原件不留部分数据。结果只允许淘汰、补证或请求三家报价，不创建 Product、采购、Passport、Listing，也不调用 Ozon 写接口；验收见 `docs/project/evidence/20260719_BAS_043_CANDIDATE_RESEARCH_INTAKE.md`。
- BAS-044 补齐了预检与既有三报价入口之间的受控交接：只有当前预检仍为 `request_three_quotes`、证据再次有效、市场为 RU 且操作者明确确认时，才建立状态为 `candidate` 的 Ozon Product 报价工作区。确定性商品 ID 让重试幂等，同 SKU 指向其他商品时失败关闭；候选原件以 `candidate_basis` 血缘链接到 Product。该动作仍不创建 Passport、报价、采购、Listing 或 Ozon 写入；验收见 `docs/project/evidence/20260719_BAS_044_CANDIDATE_SOURCING_HANDOFF.md`。
- BAS-045 把上述交接变成三报价服务端的强制前置门：`comparison-intake` 在读取上传文件前，必须同时找到不可由业务 API 伪造的候选工作区事件与有效的 `candidate_basis` Evidence 血缘。普通 Product、只有事件或只有血缘均拒绝，不留下假设或报价 Evidence；G-1 已改为从五份候选原件、原子预检、人工交接到三报价走同一 API 链。验收见 `docs/project/evidence/20260719_BAS_045_SOURCING_GATE_INTEGRITY.md`。
- BAS-046 将五类指标升级为可复验测量：客户端补窗口与样本量，服务端锁定方法和单位，并按可信度聚合需求、缺口和退货风险后执行 50/50/30 询价筛选。低于阈值不再错误进入三报价；合同缺失或样本不足失败关闭。阈值是工程默认值，仍需经营负责人在 G0 前复核，且不批准采购、Listing 或平台写入。验收见 `docs/project/evidence/20260719_BAS_046_CANDIDATE_MEASUREMENT_POLICY.md`。
- BAS-047 把三个真实候选的准备工作纳入 `kjds-startup-package-v4`：新增 3×5 `candidate-research.csv`，离线校验候选/指标覆盖、RU/OZON 边界、运行时测量合同、值域、可信度、时间和双来源族；Web 启动路径同时提供候选研究和 Passport 模板。CSV 只减少资料收集摩擦，正式录入仍必须走 Evidence 上传、五指标原子预检和人工报价交接；验收见 `docs/project/evidence/20260719_BAS_047_CANDIDATE_PORTFOLIO_PACKAGE.md`。
- BAS-048 将真实需求数据设为候选研究前的独立 `SKU-000` 门，并让 readiness 复用候选交接事件与 `candidate_basis` 血缘判断。历史商品不再能够填满 `SKU-001`，也不能替新候选贡献 Passport 或三报价完成数；Web 启动路径先引导账户主体取得真实 Ozon 报告，并提供固定来源和窗口的专门存证入口，再进入三候选五指标研究。验收见 `docs/project/evidence/20260719_BAS_048_STARTUP_DEMAND_GATE_AND_CANDIDATE_READINESS.md`。
- BAS-049 将 `SKU-000` 从上传即放行收紧为双人不可变复核：原报告仅形成 `source_report` 待复核血缘，独立 approver 才能生成 `review_attestation`；上传者自审、缺少接受、任一拒绝、篡改或伪造通用 Evidence/Lineage 均保持阻断。Web 明示两步流程和上传者身份，API 保留复核来源与血缘命名空间。验收见 `docs/project/evidence/20260719_BAS_049_DEMAND_REPORT_DUAL_CONTROL.md`。
- BAS-050 将候选录入、复评、三报价人工交接和 `SKU-001` readiness 显式绑定到同一份当前已接受需求报告；五类观测存储报告 ID，缺失、混用、待复核、拒绝或损坏均失败关闭。候选商品只新增 `demand_report_basis` 血缘，不自动采购、不自动上架；报告后来失效时候选资格同步失效。验收见 `docs/project/evidence/20260719_BAS_050_CANDIDATE_DEMAND_REPORT_BINDING.md`。
- 图片 QA 已从无身份布尔数组收紧为完整八项人工审核合同：拒绝缺项、重复项和未知项，每项保存依据、可选 Evidence、服务端审核身份与 UTC 时间；任一失败退回。Listing 草稿只接受同 SKU 已批准图片 Evidence，并保存 ContentAsset 血缘；创建草稿只产生独立发布审批，不调用 Ozon 写接口。
- 时间/金额第一批已冻结：供应商报价时间必须带时区并规范化 UTC，金额/汇率/度量使用有限 Decimal，非法费率和负成本由领域与 PostgreSQL 双重拒绝；边界见 `docs/adr/ADR-0008-time-money-domain-semantics.md`。
- Repository 驱动的业务写入、自动化推荐及 Gate Review 创建/提交/决定已将业务对象与最小脱敏 Outbox 事件放入同一数据库事务；真实 PostgreSQL 已验证故障回滚、并发独占领取、租约过期接管、稳定 event ID、失败重试和至少一次发布。外部 sink 仍必须按 `event_id` 幂等，未迁移的直接 Session 领域不计入“全系统完成”。
- Web 首屏已有“真实业务启动路径”：直接读取 G0/G1 readiness，按 GOV/Ozon/候选/SKU/Passport 与真实素材/三报价/财务顺序给出下一动作，并提供八份可下载准备模板；标准库校验器同时检查三候选五指标、Ozon API 身份脱敏盘点、资料包结构、关键行、跨文件覆盖和图片素材元数据完整性，不读取原件或图片，不改变后端事实、权限或审批结论。
- Ozon worker 支持单次/批量只读、最多 50 个目标、确定性游标、租约回收和证据化结果；成功 run 必须先保存可复验原始响应包。
- 只读成功结果可提出受限候选声明；接受后仍为 `formal_fact_promoted=false`。
- 业务写入口和只读控制对象均执行 endpoint 级角色检查。
- API 已为每个请求生成或复用安全的 `X-Request-ID` 与 `X-Trace-ID`，认证/写安全失败也返回关联头；Ozon worker 的同一操作保持稳定 trace、每次 HTTP 调用生成独立 request，试运行与执行回执持久化并索引关联 ID。

### 13.2 历史业务阻塞记录

| 阻塞 | 所需输入 | 责任人 | 影响 |
|---|---|---|---|
| Ozon 真实需求证据 | 研究闭环可使用经独立复核的 28 天 Seller Analytics 店铺级原件、公开市场证据、第三方辅助信号或固定测试数据，但必须保持 `research_signal/estimate`；真实经营要求 Ozon Data 正式报告，或至少两个独立、可复验的 Ozon 官方类目级来源。Seller Analytics 店铺页和 `product-queries` 仅反映我方商品，单独不能放行付款、采购、发布、广告、补货或 actual 晋升 | 经营负责人 | G0 |
| 三个真实新上新候选 SKU | 基于上述报告和独立来源完成五指标研究，经人工交接形成带事件与 `candidate_basis` 血缘的三个候选；现有目录只作对照 | 经营/商品负责人 | G0/G1 |
| Ozon 权限与账户 | 已只读确认登录态、有效合同和 Seller API，并正式存证一份 2025-10 计提原件；仍需真实需求/订单/退货/结算等原件、收款路径证据及专用最小权限只读身份 | 经营负责人 | G0/G1/G4 |
| Ozon API 身份治理 | 盘点现有 7 个宽权限 Key 的调用方；经批准后新建专用只读 Key 并轮换/撤销闲置 Key | 账户/工程负责人 | G0/G1 |
| Passport 与样品 | 材质、尺寸、重量、认证、包装、质量证据 | 商品/合规负责人 | G1 |
| 真实报价/物流 | 至少三家报价、样品实测、主备物流 | 供应链负责人 | G1/G3 |
| 结算/银行/FX | 现有计提原件先由不同身份完成来源复核和 9 类会计分类；再补 Ozon 结算、银行到账与实际 FX 原件和口径 | 财务负责人 | G4 |

### 13.3 当时的执行队列

1. 先固化并独立复核现有 28 天研究原件，完成 3 个真实 SKU 的研究、五指标预检和人工报价交接；任何真实付款、采购、发布、广告、补货或 actual 晋升前，再补齐 Ozon Data 正式报告或至少两个独立 Ozon 官方类目级来源。Seller Analytics 与 `product-queries` 只用于店铺和现有 Listing 研究，不能单独解除真实经营 Gate。
2. 用真实 Ozon 结果验证字段映射、候选声明、独立复核和正式事实转换边界。
3. 导入第一份真实结算/银行样本，冻结费用字典、FX 和 CM3 口径。
4. 完成三个 SKU 的 Passport、供应商报价、样品、包装和物流 Episode Package。
5. 签署 G0/G1 结构化 Gate Review；在此之前不开放上架、广告、采购或平台写入。

---

## 14. 工程目录与文档目录

```text
D:\KJDS\kjds\
├── AGENTS.md                         Agent 执行规则与质量门
├── docs/project/MASTER_SPEC.md       本文件：需求→产品→架构→实现→验收总规
├── docs/project/                     专题附件、Gate、运行手册、注册表
├── apps/control_plane/               API、领域服务、连接器、治理与运行状态
├── web/                              Next.js 控制台
├── migrations/versions/               Alembic Schema 迁移
├── scripts/                          G-1、Ozon worker、Radar、健康检查
├── tests/                            单元、集成、安全、契约、Gate 回归
├── docs/planning/                     研究母稿与 Backlog（非当前执行真源）
└── .runtime/                         临时报告、健康状态和验证产物
```

专题附件：

- `00_PROJECT_CHARTER.md`：章程与边界。
- `01_LIVE_METHODOLOGY.md`：经营/工程方法。
- `02_ROADMAP_AND_GATES.md`：Gate 细则。
- `03_REMAINING_WORK_AND_PARALLEL_PLAN.md`：P0 工作簿。
- `04_SOURCE_DECISION_UNKNOWN_REGISTER.md`：来源、决策、未知项。
- `05_BUILD_BUY_REUSE.md`：选型与复用。
- `06_OPENCLAW_HERMES_RUNBOOK.md`：本机运行手册。
- `07_CONTINUOUS_INTELLIGENCE_AND_AGENT_OS.md`：情报、认知晋级与 Agent OS。

---

## 15. 变更控制与验收模板

任何新增模块、Agent、平台、字段或自动化必须先填写：

```text
变更目的：
影响 Gate：
解决的真实问题：
输入证据：
新增数据/权限：
风险与最大损失：
回滚方式：
验收测试：
Owner / Approver：
复杂度税：
冻结条件：
```

完成后同步更新本文件版本、专题附件、数据合同/迁移、测试、运行证据、未知项登记和下一执行队列。没有这些内容的“功能完成”不计入 Gate 交付。

## 16. 最终成功定义

KJDS 的成功不是拥有最多 Agent，而是在真实跨境经营中，用可验证证据把商品、现金、供应链、平台和客户决策连接起来；每次动作可审计、可回滚，每次失败沉淀为负知识，每个平台学习都能在受控边界内反哺下一次决策。

工程成功必须用真实 SKU、真实权限和真实结算文件，把 G0→G4 从工程骨架推进成可复核经营事实；具体执行顺序只在任务真源维护。

---

## 17. 技术与架构补充清单

本节是对现有架构的二次审计。它不是立即引入所有基础设施，而是明确哪些能力必须补、什么时候补、补到什么程度，防止“看到问题就加中间件”。

### 17.1 P0：进入 G0/G1 前必须补齐

| 能力 | 当前风险 | 最小实现 | 放行证据 |
|---|---|---|---|
| API 合同版本 | 前后端字段漂移、旧客户端被破坏 | `schema_version`、兼容字段策略、错误码表、OpenAPI 快照 | 合同测试 + 旧响应回放 |
| 幂等与重复投递 | 重复采购、重复声明、重复命令 | 所有写命令带 idempotency key；唯一约束；重复请求返回原结果 | 并发重复测试 |
| Outbox/事件发布 | DB 已提交但通知/审计未送达 | 先写事务 outbox，再由有界 worker 发布；失败可重放 | 断电/重启重放测试 |
| 事务与并发 | 两个审批/worker 同时修改状态 | service 事务边界、行锁、状态版本号、租约 | 并发竞态测试 |
| 时间与时区 | Ozon/银行/FX/退款跨时区错配 | 所有时间带时区；`effective_at` 与 `recorded_at` 分离；统一 UTC 存储 | 跨日/夏令时/延迟回传测试 |
| 金额与度量 | `NaN`、负成本、隐式换汇或非法比例污染利润 | Decimal/NUMERIC、有限值、币种/汇率/日期显式、领域与 DB 双重约束 | 非法领域输入 + 绕过服务层写入测试 |
| 证据保留策略 | 证据无限增长或过早删除 | 数据分级、保留期限、软删除禁用规则、归档索引 | 证据生命周期演练 |
| 备份与恢复 | PostgreSQL 损坏后无法证明状态 | 自动备份、恢复脚本、备份哈希、恢复后迁移校验 | 恢复演练报告；明确 RPO/RTO |
| 观测基线 | 只知道失败，不知道在哪一层失败 | `request_id`、`trace_id`、`run_id`、`command_id` 贯穿 API/服务/worker/证据 | 一次端到端 trace |
| 连接器安全 | 外部 API 失败、限流或响应漂移 | timeout、指数退避上限、熔断、响应 schema 校验、原始响应证据 | 429/5xx/字段漂移回放 |
| 密钥与配置 | 环境配置被误提交或身份混用 | 启动时配置校验、角色 profile、密钥轮换/撤销、日志脱敏 | secret scan + 身份越权测试 |

当前进度：API 合同版本的最小实现已完成，运行时声明 `schema_version=v1`，普通 HTTP/校验错误保留旧 `detail` 并增加稳定错误对象，响应携带请求与版本头；兼容策略见 `docs/adr/ADR-0004-api-v1-compatibility.md`，机器可比较快照见 `docs/project/contracts/openapi-v1.json`，由 `tests/test_api_contract.py` 验证。表内其余 P0 能力仍须逐项取得放行证据，不因本项完成而视为整体完成。

观测基线的最小闭环已完成：`20260717_0035` 为只读试运行和有限执行回执持久化 `request_id/trace_id` 并增加 trace 索引；API 过滤不安全关联头，Ozon worker 在一次操作内传播稳定 trace，试运行证据包含 `request_id + trace_id + run_id`，执行回执包含 `request_id + trace_id + command_id`。G-1 用同一 trace 串联两条链并验证证据 ID，最新完整回归为 136 passed；见 `docs/adr/ADR-0009-end-to-end-correlation.md` 与 `docs/project/evidence/2026-07-17-end-to-end-correlation-verification.md`。集中日志、跨服务 span、采样和告警聚合尚未引入，必须在服务数量或排障需求证明其必要时再增加。

连接器安全最小闭环已实现并通过 G-1：Ozon 读请求只对传输错误、429 和 5xx 做最多三次有界退避，连续故障触发 Worker 进程内熔断；写请求网络异常永不盲目重试；使用中的端点通过最小响应 schema；成功只读 run 必须先保存不含请求凭证的响应原件包并复验 SHA-256，摘要证据通过 lineage 引用原件。边界见 `docs/adr/ADR-0010-ozon-connector-reliability.md`，验证记录见 `docs/project/evidence/2026-07-17-ozon-connector-reliability-verification.md`。熔断仍是单 Worker 进程内状态，真实 Ozon 账户回放仍受 OZN-001 阻塞。

密钥与配置的最小闭环已实现并通过 G-1：空的多身份 JSON 不再遮蔽开发密钥；未知环境、未知角色、占位密钥、生产共享单密钥和未登记 Web 代理密钥均在启动时失败关闭；运行摘要只输出环境、身份数和角色组合。标准库扫描覆盖 Git 已跟踪及未忽略的新文件，只报告文件和规则，不回显秘密；当前 277 个文件通过。边界见 `docs/adr/ADR-0011-runtime-identity-and-secret-scan.md`，验证记录见 `docs/project/evidence/2026-07-17-runtime-identity-secret-scan-verification.md`。首次托管生产部署时仍须评审轮换、撤销和 KMS/Vault，而不是提前引入。

`BR-027/BAS-039` 已把 Evidence 完整性端点接入既有 `run-24x7-health.ps1`：脚本验证专用 key 在 `KJDS_API_KEYS_JSON` 中只拥有 `monitor` 角色，并拒绝与 operator、executor、pilot-reader 或 Ozon key 复用；扫描以 `limit/offset` 有界分页，排除 monitor 自身生成的报告，异常、身份/API 失败或分页未完成均在必需模式下非零退出。输出只保留扫描计数、最后报告 ID 与 Incident 数。完整 G-1 从脚本真实调用隔离 API 通过；证据见 `docs/project/evidence/20260719_BAS_039_24X7_EVIDENCE_HEALTH_LOOP.md`。这仍不是机器离线容错或外部通知送达证明。

`BR-028/BAS-040` 已加入默认无变更的 Windows Task 管理入口：Plan 不读取部署配置、不注册任务；Install 只允许从任务以后仍能读取的项目 `.env` 执行预检，成功后注册固定 `pwsh`、固定脚本与工作目录、`ControlPlaneOnly`、15 分钟重复、5 分钟上限和 `IgnoreNew`，命令行不得携带凭证。注册后定义不一致立即非零；Audit 只有在定义一致、最近结果为 0 且 Task Scheduler 原生完成历史连续三次为 0 时才返回 accepted。当前完整 G-1 为 206 个 Python 测试、6 个 Web 测试、287 文件密钥扫描，`evidence_health_task_contract=true`；没有创建真实任务，BAS-040 仍受持续控制平面、专用身份与三次完成历史阻塞。

2026-07-19 对已登录 Ozon Seller 再次执行最小只读复验：18 个商品（15 在售、3 待售、0 错误）的目录计数未变，财务、分析、Seller API 和 API 通知入口仍可访问；未读取个人资料值、余额、已有密钥详情，未生成密钥或下载报表。该复验只更新 `SRC-005/OZN-001` 的时效性，不解除专用最小权限身份、原始导出与真实单 SKU API 响应阻塞。用户要求后续做新上新，因此现有目录不自动成为三个候选，`UNK-001` 必须以需求、可采购性、三报价、合规和风险调整后 CM3 重新筛选。

新上新研究阶段采用 `BAS-041` 的商品级候选预检，而不是复用无边界的通用加权分数直接排名。每个候选以稳定 `candidate_ref` 关联需求、竞争缺口、供货、合规红线和退货风险观测；必须满足指定观察时点、默认 90 天时效、正可信度和至少两个独立来源族，同一机构的不同子域按同一来源族处理。任何当前合规红线直接淘汰，缺项、过期、未来数据、零可信度、非法数值、单一来源或无供货信号均要求补证；全部通过也只能进入三家真实报价，不能创建商品、采购或 Listing。该工程门不解除 `UNK-001/005`。

`BR-029/BAS-042` 收紧候选证据真实性：每条参与候选预检的观测必须通过 `dimensions.evidence_id` 绑定 Evidence Ledger 中存在且 SHA-256 复验通过的原件；观测的 `source/source_ref` 必须与原件记录一致，时效同时检查观测时间、原件 `effective_at` 和可选 `effective_until`。来源独立性只按原件来源计算，缺失、损坏、过期或不匹配的原件均失败关闭。该约束复用现有 EvidenceService 和观测维度，不新增表或迁移；结果分别返回观测 ID 与原件 Evidence ID，仍只允许进入三报价，不构成选品、采购或上架批准。

`BR-030/BAS-043` 把上述工程边界开放为一个非技术候选研究入口：用户先将原件固化到既有 Evidence Ledger，再为五类固定指标选择原件并填写值和可信度。服务端必须从原件派生 `source/source_ref/observed_at`，拒绝客户端自报来源；必须先复验全部 Evidence，再在一个 Repository 事务中写入五条观测。观测 ID 由候选、指标、原件和值的规范摘要确定，同一提交重试不得重复建账；缺项、重复指标、未知指标或坏原件不得写入任何观测。响应复用 BAS-041 预检，只能返回 `reject`、`collect_evidence` 或 `request_three_quotes`，不得创建 Product、采购、Passport、Listing 或平台写入。Web 必须把结果、缺口和“仍需三家真实报价”直接展示给非技术用户。

`BR-031/BAS-044` 定义候选到三报价的唯一交接：客户端不得直接把任意候选变成 Product；服务端必须在交接时重新执行 BAS-041 预检并复验全部 Evidence，只接受 RU/OZON 当前垂直切片和显式人工确认。交接只创建 `candidate` Product 报价工作区，以候选、市场、类目和 SKU 的规范摘要生成稳定 ID，并把全部候选原件链接为 `candidate_basis`；同一请求重试必须复用工作区，同 SKU 已属于其他商品则失败关闭。响应的下一门仅为 `sourcing_comparison_intake`，`automatic_procurement=false`、`automatic_listing=false`；Passport、真实报价、CM3、采购审批、Listing 审批与平台写入保持原有独立 Gate。

`BR-032/BAS-045` 禁止三报价绕过候选门：`SupplierComparisonIntakeService` 必须先确认目标 Product 存在 `product.candidate_sourcing_workspace_created` 内部审计事件，再查询其 `candidate_basis` 血缘并重新执行 Evidence 哈希复验。两项检查均发生在上传内容被捕获之前；任何一项缺失或损坏均失败关闭且不得留下部分报价、利润假设或场景。该约束复用现有 Repository event 与 Evidence lineage，不新增表、迁移或客户端令牌。

`BR-033/BAS-046` 消除“指标有名字但不参与决策”的假精确：服务端为五类指标固定 `ozon-ru-candidate-measurement-v1`，并把方法、单位、窗口和最小样本写入观测维度。需求和竞争缺口使用类目内百分位（28–90 天、样本至少 30），退货风险使用预期 30 日退货率百分比（28–90 天、样本至少 30），供货与合规使用 1–90 天内至少一个可核验对象的布尔结论。客户端只能提交值、可信度、原件、窗口和样本量，不能自定义方法或单位；所有有效观测按可信度加权，并由 `ozon-ru-quote-screen-v1` 执行 50/50/30 的保守询价阈值。任何输出必须同时返回策略 ID、聚合值和未达阈值，且明确这不是采购、上架或利润批准。

事务 Outbox 的第一批最小实现已完成：`20260717_0029` 增加稳定事件合同和投递状态，核心 Repository Service 与自动化推荐执行原子写入，发布器使用 `FOR UPDATE SKIP LOCKED`、有界批次、租约、退避和至少一次语义；`GET /v1/outbox/status` 提供只读运行状态。G-1 在一次性 PostgreSQL 中验证原子回滚、两个 worker 竞争、进程中断后的租约接管和失败重试，证据见 `docs/adr/ADR-0007-transactional-outbox.md` 与 `docs/project/evidence/2026-07-17-transactional-outbox-verification.md`。具体外部 sink 尚未配置；其他直接 Session 领域必须按覆盖清单在真实消费者或 Gate 触发时迁移，不能为追求覆盖率提前制造无消费者事件，因此只标记“第一批完成”。

第二批只迁移 Gate Review：创建、提交和决定分别写入 `gate_review.created`、`gate_review.submitted`、`gate_review.decided`，payload 不含目标、理由、预算等正文，只保留 gate、状态、决定和计数；actor 与首个证据引用进入标准事件字段。事件写入故障会回滚决定状态。G-1 的真实 PostgreSQL Gate API 链与通用 Outbox 演练均通过，完整回归 138 passed；见 `docs/project/evidence/2026-07-18-gate-review-outbox-verification.md`。这不代表其他直接 Session 领域已全部迁移。

覆盖清单批次不新增事件，而是把 25 个直接事务模块分为 2 个已覆盖、2 个轮询合同、4 个 Gate 前延期、15 个仅内部状态和 2 个基础设施模块；标准库测试要求源码发现集合与 `docs/project/registries/outbox_coverage.json` 精确一致，并显式保持 `full_system_outbox=false`。完整 G-1 为 139 passed、234 文件密钥扫描；见 `docs/project/evidence/2026-07-18-outbox-coverage-registry-verification.md`。

时间/金额语义的第一批最小实现已完成：`20260717_0030` 为供应商报价和利润场景增加 11 条数值约束；领域入口拒绝无时区时间、`NaN`/无穷值、非正价格/汇率/重量/MOQ、负成本和不可计算的组合费率。G-1 绕过服务层的三类非法 PostgreSQL 写入均被拒绝，完整回归为 121 passed；见 `docs/adr/ADR-0008-time-money-domain-semantics.md` 与 `docs/project/evidence/2026-07-17-time-money-integrity-verification.md`。其他金额表和真实财务舍入口径尚未完成审计。

第二批已扩展到 Ozon 导入与财务账本：`20260717_0031` 为 FX、财务分录、对账容差和现金计划增加 5 条约束；四类绕过服务层的非法写入均被 PostgreSQL 拒绝，当前完整回归为 123 passed。证据见 `docs/project/evidence/2026-07-17-finance-numeric-integrity-verification.md`。真实 Ozon/银行口径和其他金额领域仍未因此自动完成。

第三批覆盖决策合同、预测区间和因果实验风险数字：`20260717_0032` 增加 7 条 CHECK 约束，拒绝非有限最大损失/置信度/预测/结果/观测/安全阈值，并强制预测区间与实验预算—止损关系一致。G-1 绕过服务层的七类非法写入全部被拒绝，完整回归为 124 passed；见 `docs/project/evidence/2026-07-17-decision-experiment-numeric-integrity-verification.md`。因果策略、受控执行和其他 NUMERIC 领域仍需继续逐表审计。

第四批覆盖因果策略阶段结果与能力经济账：`20260717_0033` 增加 5 条 CHECK 约束，拒绝非有限阶段收益/能力价值、负成本、净价值算式不一致和非 ASCII 三字母币种；策略护栏、分阶段暴露、最小增量值与上下文数值比较也在领域入口拒绝非有限值。G-1 基于真实 API 业务链绕过服务层的五类非法写入全部被 PostgreSQL 类型或约束拒绝，完整回归为 125 passed；见 `docs/project/evidence/2026-07-17-policy-capability-numeric-integrity-verification.md`。执行后观测当前以字符串保存有限 Decimal，其他新接入 NUMERIC 领域仍须逐表审计。

第五批收口旧核心账：`20260717_0034` 为订单、费用、市场观测、机会分、旧增长实验、自动化建议和样品采购增加 7 条 CHECK，统一数量、有限值、置信度/评分范围、预算—止损、正价格和 ASCII 币种语义；共享标准库辅助函数在入口拒绝非有限 Decimal。七类绕过服务层的非法写入均被 PostgreSQL 拒绝，完整回归为 127 passed；见 `docs/project/evidence/2026-07-17-core-numeric-integrity-verification.md`。至此当前 ORM 显式 NUMERIC 列已完成结构层审计，但真实税务、银行、Ozon 结算、币种换算和舍入口径仍必须由一手数据与责任人冻结，不能将结构完整性等同于会计正确性。

备份与恢复的历史 G-1 演练使用 `pg_dump` 自定义格式、SHA-256 清单、隔离目标恢复，并校验当时的 Alembic head `20260720_0038` 与关键表计数；该结果只证明对应版本。当前 head 必须由实时 G-1 重新确认。见 `docs/adr/ADR-0005-postgres-backup-recovery.md`、`docs/project/07_BACKUP_RECOVERY_RUNBOOK.md` 与 `docs/project/evidence/2026-07-18-postgres-restore-drill.md`。自动计划、异地加密副本、保留周期和托管环境正式 RPO/RTO 仍未完成，因此本项尚不能作为生产灾备承诺。

证据保留已增加机器可执行的分类与复审评估，未知分类被拒绝、未分类进入 `classification_required`、legal hold 阻止归档，且所有证据一律 `automatic_delete_allowed=false`；见 `docs/adr/ADR-0006-evidence-retention.md` 与 `tests/test_evidence.py`。当前天数是内部复审最短间隔，不是法定期限；真实财务/客户数据进入前仍须由合规负责人冻结正式保留矩阵。

### 17.1.1 现有 Ozon SKU 增长规划

`BR-066/BAS-090` 把现有商品的增长诊断收敛到 `MarketplaceGrowthPlanner` 一个深模块。调用方只提交版本化全成本场景和有 Evidence 的店铺/同行快照；模块内部统一完成 RUB/CNY 语义、同行价格四分位、目标 CM3 价格底线、最大 ACOS、基于真实转化率的最大 CPC、内容七角色、合规/库存/评价/转化门禁和组合优先级。市场快照超过七天、同行样本少于三条、实际成本未通过独立权威复核、无库存、高合规风险或无真实转化率时均失败关闭相应增长动作。

输出固定为 `recommendation_only`，`automatic_marketplace_write=false`、`automatic_ad_spend=false`。1688 展示价只可作为供应商发现或估算证据，不能冒充采购、境内物流、国际物流、包装、税费、尾程、退货和售后均已实际确认的落地成本；广告只有在价格进入市场带、内容分不低于 90、评分不低于 4.5、至少 5 条真实评价、存在真实转化率且目标 ACOS 为正时才可进入有预算上限的因果实验。真实改价、内容发布和广告创建继续走既有审批、一次性许可、回读和止损合同。

`BR-068/BAS-092` 在该计算器外增加一个小接口、深实现的 `MarketplaceGrowthWorkspace`。调用方只负责采集快照、读取每个 SKU 的最新观测和请求全店计划；规范化、幂等、版本哈希、存储选择和组合规划均封装在服务端。SQL 是生产适配器，内存适配器只用于模块级测试。店群、铺货、精品/精细化和品牌运营不复制事实表或规划器，而是后续在同一快照与计划上叠加店铺范围、额度、模板和权限。

`BR-069/BAS-093` 增加 `MarketplaceCatalogWorkspace` 深模块。其接口只接受经 `PilotRunService` 完整复验的原始 Evidence、店铺范围和幂等键；模块内部完成固定合同解码、双响应哈希验证、目标绑定、字段规范化、媒体权属标记、快照哈希、PostgreSQL 持久化和 Evidence 血缘。第一条生产链只覆盖已有 Ozon Seller 只读证据，不虚构 1688 或竞品 API 连接。采购报价继续由 `SourcingService` 管理，竞品/行业动态继续进入 Research Signal Inbox，物流报价后续以版本化线路适配器接入既有 15 项全成本模板；三者不得复制 Product、Evidence、利润或审批事实源。

`BR-069/BAS-094` 落实版本化物流线路适配器。`LogisticsQuoteWorkspace` 把承运商、路由、服务、计价/申报币种、有效期、每 kg/每票/最低收费、体积重除数、计重进位及重量/尺寸/货值边界固化为 Evidence-backed 档位；每次输入生成不可变、幂等的 Decimal 计算快照。三家供应商比价可用每家实测重量与尺寸产生单件国际物流估算，并通过同一个 `SourcingService` 进入既有 15 项成本和 CM3，不复制利润公式。报价和 AI 建议永远是 `estimate/recommendation_only`；只有经 BR-057 独立权威复核的承运商最终账单可成为 `actual`。

`BR-070/BAS-095` 关闭上传即成为正式报价的权威漏洞。所有供应商页面、聊天、报价单和形式发票先以 B 级 `supplier_quote_source` 原件进入既有 Evidence Ledger；`public_display_price` 永远只保留为研究线索。`supplier_confirmed_quote` 与 `proforma_invoice` 必须由非上传者逐项核对原件真实性、供应商、冻结规格、金额/币种/MOQ、有效期与交付条件，接受后形成 A 级不可变复核凭证和 lineage。三报价最终化只从同一候选 Product 的三份当前已接受、不同供应商原件派生 `SupplierOffer` 和 CM3，客户端不得重报条款；任何报价在发票付款实际成本权威复核前仍只能是 estimate。边界与被否决方案见 `docs/adr/ADR-0021-supplier-quote-authority.md`。

`BR-071/BAS-096` 打通真实目录与 Canonical Product：最新 Ozon Catalog 条目只有在源 Evidence 完整性、店铺/offer 作用域、客户端 item hash 和显式人工确认同时通过时，才以稳定身份建立 `active` Product，并写入不可变外部身份映射、`product.existing_listing_growth_workspace_created` 事件与 `existing_listing_basis` 血缘。该事件不是候选交接，不进入 `SKU-001`；但允许已有商品继续收集三份独立接受的供应商报价、建立 Passport/CM3 和执行只读增长诊断。绑定不复制目录事实、不修改历史快照、不授予外部媒体权利，也不执行 Ozon 写入、采购、供应商联系或广告。见 `docs/adr/ADR-0022-existing-marketplace-listing-binding.md`。

`BR-072/BAS-097` 在已有 Listing 与报价权威门之间增加 `SupplierRfqWorkspace` 深模块。调用方只提交当前 Listing 身份、item hash、幂等键和买方要求；模块复验绑定 Product 与 Catalog Evidence，规范化数量阶梯、逐项规格、包装/文件/目的地/期限，生成确定性中文询价正文、供应商回复清单和未确认问题，并以 C 级 `supplier_rfq_package` 不可变 Evidence 固化。相同幂等键只允许相同包，数据库以来源引用唯一索引防并发双写。RFQ 是买方草稿，不是供应商事实、报价或发送回执；复制正文仍不自动联系供应商。真实回复上传可引用 RFQ 建立 `supplier_response_context_for` 血缘，但正式 `SupplierOffer` 与 CM3 继续只能由 BR-070 的三份独立接受报价生成。见 `docs/adr/ADR-0023-supplier-rfq-package.md`。

`BR-073/BAS-098` 关闭“复制 RFQ 即视为已联系供应商”的真实性漏洞。`SupplierRfqDispatchWorkspace` 只接受现有 RFQ、原文完全一致的发送内容、供应商与平台定位、会话/消息编号、带时区发送时间、幂等键和原始截图/导出；模块复验 RFQ 完整性与截止期，冻结 RFQ/package/message 哈希和证明原件哈希，以 B 级 `supplier_rfq_dispatch` Evidence 保存。另一身份必须核验平台原件、供应商、全文、时间和会话后才能形成 A 级不可变复核；即使已接受，也只证明存在与冻结 RFQ 一致的发送记录，不证明送达、回复或报价。供应商回复引用发送证明时，服务端必须复验同一 Product、RFQ 和 supplier ref，并建立 `supplier_response_to_dispatch` 血缘。见 `docs/adr/ADR-0024-supplier-rfq-dispatch-proof.md`。

`BR-075/BAS-100` 在 BR-065 与 BR-074 之上增加 `EvidenceOpsCopilot` 深模块。其外部
接口只接收 `objective` 与 `store_ref`，内部完成意图解释、事实/未知分离、阶段排序、
Agent 分派、验证条件、控制包和规范哈希。它不直接读取 Repository，不重新实现 Gate，
也不保存聊天或计划；服务端返回的任务合同是前端唯一排序真源。独立 Web 入口只负责目标
提交和合同呈现，所有继续操作返回既有 KJDS 工作区。边界和 `best_solution` 选择见
`docs/adr/ADR-0026-evidenceops-copilot-product-seam.md`。

`BR-076/BAS-101` 增加 `CrossBorderCapabilityAtlas` 深模块。模块只读取版本控制内的
单一能力注册表，验证宏观能力树和“点—线—面”运行图谱。原子点必须声明父能力、业务
对象、操作类型、合同 profile、输入输出、Evidence 门、责任人、失败队列、回读、KPI、
状态、市场/平台和价值流成员关系；价值流必须声明有序阶段、对象状态变化、入口/出口门、
事件、异常、SLO 和人工接管；经营面必须声明关联价值流、核心原子点、维度、真源、决策、
指标、预警和写边界。服务端拒绝悬空引用、重复 ID、越权状态和客户端自算路径，再返回带
规范哈希的只读快照。独立 Web 入口用原生 React、HTML 与 SVG 呈现可切换、可搜索、
可下钻的点、线、面视图以及 Russia/Global 过滤；不引入第二图数据库、前端状态真源或
未经 ADR 的工作流基础设施。`implemented` 只用于已有 KJDS 合同，`ready` 表示已完成
受控产品设计，`gated` 表示等待真实凭证/证据/批准，`research_only` 表示仅有公开
参考。LinkFox 页面、套餐、模型名、Skills 调用量和 Agent 宣称始终保留为 C 级观察，
不进入 Ozon 或经营事实。边界和 `best_solution` 选择见
`docs/adr/ADR-0027-cross-border-capability-atlas.md`；人可读点线面设计见
`docs/project/12_CROSS_BORDER_POINT_LINE_SURFACE_OPERATING_GRAPH.md`。

`BR-077/BAS-102` 在图谱与既有经营模块之间增加 `OperatingWorkspace` 深模块。外部
interface 只接收 `kind`、稳定节点 ID 和 `store_ref`，内部组合
`CrossBorderCapabilityAtlas.snapshot()` 与 `OperatingAnalyticsService.snapshot()`，
把点、线、面统一投影为可用工作区：阶段卡保留合同状态和真实运行状态两套语义，事实、
Evidence、缺口和下一动作来自现有服务端投影，所有继续操作只导航到既有领域工作区。
点、线、面的专用路由分别为 `/operations/points/{id}`、
`/operations/lines/{id}` 和 `/operations/surfaces/{id}`；未知 kind/ID 失败关闭。前端
不得用图谱的 `implemented/ready` 推断业务已完成，也不得从浏览器重新计算线或面关系。
边界和 `best_solution` 选择见
`docs/adr/ADR-0028-operating-workspace-drillthrough.md`。

`BR-081/BAS-103` 把页面与卖家工具线索放进证据化
`MarketplaceObservationWorkspace`，而不是复制旧插件的身份和执行模式。外部 Interface
只提供 `capture()` 与 `latest()`；Implementation 负责原始 JSON Evidence、来源/价格
语义、Decimal、自然键、幂等、快照哈希和正式事实隔离。默认经营调用方只使用
`PortfolioPilotWorkspace.prepare()`，由服务端组合当前 Ozon Catalog、目标规格、观察
候选、既有报价/利润/Listing readiness 和 OperatingTask，输出价差、悲观/基准筛选贡献、
规格差距、状态、阻断、下一动作与稳定排序。页面展示价不生成 Supplier Offer 或 actual，
验证码不绕过，真实写入继续消费既有批次批准与一次性执行合同。边界和
`best_solution` 选择见
`docs/adr/ADR-0030-marketplace-observation-portfolio-pilot.md`。

### 17.2 P1：G2/G4/G5 前补齐

| 能力 | 设计方向 | 触发条件 |
|---|---|---|
| Canonical 数据合同 | 平台对象映射到内部标准对象；平台字段变化留适配器版本 | 第二类真实 Ozon 数据或第二平台 |
| Read Model | 事实账与驾驶舱查询投影分离，避免复杂查询阻塞写事务 | 真实订单/结算进入后 |
| 对账差异队列 | 差异类型、金额、责任人、截止时间和关闭证据 | 第一份真实结算/银行文件 |
| 任务调度抽象 | 统一任务状态、重试、暂停、恢复和人工接管；先不用 Temporal | 单机脚本出现长任务/跨进程重放压力 |
| 结构化日志 | JSON 日志、字段白名单、错误码、采样和关联 ID | 多 worker 并行运行 |
| 指标与 SLO | 成功率、P95 延迟、证据缺口、越权、成本、队列年龄 | G2 真实草稿或 G4 财务运行 |
| Prompt/Agent 评测 | 金标集、轨迹、工具调用、成本和回归门 | Agent 输出进入运营建议 |
| 数据质量门 | schema、唯一性、完整性、及时性、币种、单位和异常值 | 真实数据导入 |
| 数据分类与隐私 | public/internal/confidential/restricted；最小读取、脱敏、删除/保留政策 | 客户或银行数据进入系统 |
| 资源预算 | API 请求、模型 token、浏览器时长、人工审批时间和库存敞口的预算 | G5 影子实验 |

### 17.3 P2：G7/G8 后再考虑

- 多租户隔离、组织级配额和跨租户审计。
- Temporal 或其他持久化工作流引擎；必须先有长事务、补偿和重放的实证需求。
- 独立搜索/向量库；必须先证明 PostgreSQL 查询与全文检索不足。
- 多区域部署、托管对象存储、跨地域灾备和主动—主动切换。
- 多平台能力市场、外部 Agent 协议和生态开放接口。

### 17.4 不能用“加组件”解决的问题

- 没有真实 Ozon 权限，不能用更多连接器代替业务输入。
- 没有真实结算/银行文件，不能用更复杂的利润模型制造“真实利润”。
- 没有因果实验数据，不能用更大的模型把相关性变成因果性。
- 没有明确 Owner/Approver，不能用数字 CEO 代替责任制度。
- 没有稳定数据合同，不能用前端兼容代码掩盖后端语义冲突。

---

## 18. 推荐 ADR 目录

涉及以下决策时，应在 `docs/adr/` 建立一份短 ADR，并在本文件更新链接与状态：

| ADR | 主题 | 决策问题 |
|---|---|---|
| ADR-001 | API 版本与兼容 | 何时新增 `/v2`，旧字段保留多久 |
| ADR-0007（Accepted） | 事件与 Outbox | PostgreSQL 原子写、租约领取、至少一次发布与重放边界 |
| ADR-003 | 事实与读模型 | 哪些表是事实，哪些是可重建投影 |
| ADR-0010（Accepted） | Ozon 连接器可靠性 | timeout、有界重试、熔断、schema 漂移和原始响应证据 |
| ADR-0011（Accepted） | 运行身份与密钥扫描 | 开发/生产身份边界、失败关闭、非敏感摘要和仓库扫描 |
| ADR-0017（Accepted） | 外部合同固定样本回放 | 版本化脱敏样本、完整性、漂移失败关闭与测试期边界 |
| ADR-0008（Accepted） | 时间/金额语义 | UTC、effective/recorded、Decimal、FX、度量和舍入规则 |
| ADR-006 | 备份与灾备 | RPO/RTO、恢复演练、证据保留和密钥恢复 |
| ADR-007 | Agent 运行时 | 何时从脚本升级为持久化工作流 |
| ADR-008 | 观测与 SLO | trace、日志、指标、告警、成本和人工注意力预算 |
| ADR-009 | 数据隐私 | 客户、银行、平台凭证和供应商机密的分类与保留 |
| ADR-010 | 扩展边界 | 何时解冻第二平台、多租户和生态协议 |

ADR 必须包含：背景、选项、取舍、不可逆影响、迁移/回滚、验收指标、Owner、Approver、复审触发条件。没有 ADR 的基础设施引入视为架构漂移。

## 19. 架构健康指标

每周或每次 Gate Review 复查：

- 需求覆盖率：每个 P0/P1 需求是否有实现、测试和证据。
- 合同稳定率：破坏性 API/数据合同变更数量。
- 幂等成功率：重复请求返回原结果的比例。
- 证据完整率：事实、决策、实验和执行结果的证据关联比例。
- 失败可恢复率：故障注入后无人工数据库修补即可恢复的比例。
- 越权次数：目标始终为 0。
- 事实污染率：未经证据门进入正式事实的数量，目标为 0。
- 观测闭环率：从请求到外部动作到回读是否有完整关联 ID。
- 复杂度税：新增模块的维护成本、依赖数、权限面和删除成本。
- Agent 净价值：增量利润/避免损失/知识价值减去模型、运维、人工和错误成本。

任何指标改善不能以牺牲用户信任、合规、现金安全或平台账号健康为代价；主指标必须同时配反向指标和硬约束。

---

## 20. Loop Engineering：六个闭环模块

Loop Engineering 不是再加一个 Agent，而是让“自动化能力如何产生、复用、隔离和记忆”成为可治理的工程系统。机器可读真源是 `docs/project/registries/loop_engineering_registry.json`。

| 模块 | 在 KJDS 中的职责 | 当前状态 | 不能越过的边界 |
|---|---|---|---|
| Automations | 定时、事件或人工批准触发任务 | 部分实现 | 必须有 run、超时、幂等、证据和 Kill Switch |
| Skills | 将已验证能力封装为版本化程序记忆 | 设计中 | 未通过 Evaluation/Shadow/Audit 不得晋级 |
| Integrations | 接入 Ozon、文件、模型、通知和未来平台 | 部分实现 | 最小权限、schema、限流、回读和证据 |
| Subagents | 受限专业角色协作 | 设计中 | 独立身份、预算、工具白名单和独立复核 |
| Worktrees | 隔离并行变更、实验和回滚 | 流程实现 | 共享迁移只能单一集成人；禁止破坏性 Git |
| Memory | 保存事实、知识、程序记忆与血缘 | 部分实现 | 原始来源、哈希、置信度、失效和保留策略 |

### 20.1 六模块闭环

```text
Observe / Propose
  → Validate input and permission
  → Bounded or Shadow execution
  → Capture result + evidence
  → Independent review
  → Gate promotion
  → Memory / Skill versioning
  → Re-evaluation before reuse
```

### 20.2 六模块与阶段门

| 阶段 | 可启用能力 |
|---|---|
| G-1 | 本地验证、临时数据库、测试 Worktree、健康检查 |
| G0 | Ozon read-only Integration、有限 Automation、Evidence Memory |
| G1–G4 | SKU/财务 Skill 的人工辅助、候选事实、供应商/结算数据记忆 |
| G5 | Subagent Shadow、Skill 评测、策略实验和能力经济账 |
| G6 | 经过批准的低风险 Automation/Integration 写入 |
| G7–G8 | 可复制 Skill、第二平台/国家、生态级 Subagents 和长期 Worktree 体系 |

### 20.3 六模块验收

- Automation：同一输入重复执行不产生重复命令；失败可重跑；每次有证据。
- Skill：有输入/输出合同、工具白名单、版本、评测集、成功/失败条件和回滚。
- Integration：凭证隔离、外部错误有界、响应 schema 校验、原始响应可追溯。
- Subagent：不能自授予权限；handoff 使用结构化合同；关键结论有独立 Reviewer。
- Worktree：并行改动可审查、迁移可重放、产物可定位、无未声明共享写入。
- Memory：事实、推断、假设和决策分离；历史失败不能删除；过期结论会降级。

### 20.4 控制面合同

- `GET /v1/loop-engineering/registry` 返回六模块、当前成熟度、必需控制和晋级门。
- `POST /v1/loop-engineering/validate` 只做无副作用的合同校验，返回缺失控制、是否允许进入 proposal/shadow/active；Kill Switch 启用时仍可用于安全诊断。
- `active` 只有在模块注册状态为 `ready` 且控制项完整时才允许；当前没有任何模块可绕过 Gate 直接进入生产激活。

### 20.5 外部开发 Harness 边界

- Grok Build、Codex、Hermes 或其他开发 Agent 都是可替换执行器，不是项目事实、决策、阶段门或生产权限的 Owner。
- 外部 Harness 首次进入仓库必须先执行配置发现；没有显式授权时不得加载 MCP、插件、Hook、跨会话记忆或生产凭证。
- 只读任务先采用无写权限模式；写任务必须进入可丢弃 Worktree，先计划、再修改、再验证，不得自动 Push、Merge、发布或迁移生产数据库。
- 评估对象是完整 Agent Harness，不是单一模型；主指标为安全有效交付率，反向指标至少包含返工率、人工审核时间、缺陷逃逸、成本和越权事件。
- Grok Build 当前安装与试点证据见 `docs/project/08_GROK_BUILD_PILOT.md`；任何生产集成、ACP 常驻进程或自动化写入必须先通过独立 ADR。

### 20.6 Ultimate execution entry

Ultimate execution is opened only by the approved start gates and the dedicated start evidence:

- [Ultimate product blueprint](ULTIMATE_PRODUCT_BLUEPRINT.md)
- [Ultimate requirements architecture](ULTIMATE_REQUIREMENTS_ARCHITECTURE.md)
- [PM start gate review](reviews/20260727_ULTIMATE_START_GATE_PM.md)
- [RA start gate review](reviews/20260727_ULTIMATE_START_GATE_RA.md)
- [Ultimate execution start evidence](evidence/20260727_ULTIMATE_EXECUTION_START.md)
- [M0 Truth/Governance first slice evidence](evidence/20260727_M0_TRUTH_GOVERNANCE.md)
- [M0 scoped OperatingTask/OperationsQueue evidence](evidence/20260728_BAS_111_SCOPED_OPERATING_QUEUE.md)
- [M0 scoped read-workspace evidence](evidence/20260728_BAS_112_SCOPED_READ_WORKSPACES.md)
- [M0 scoped Batch Opportunity evidence](evidence/20260728_BAS_115_SCOPED_BATCH_OPPORTUNITY.md)
- [M0 scoped Product/content and Listing-plan evidence](evidence/20260728_BAS_116_SCOPED_PRODUCT_CONTENT.md)
- [M1 native intelligence-ingestion evidence](evidence/20260728_BAS_117_NATIVE_INTELLIGENCE_INGESTION.md)
- [M1 scoped Market Radar evidence](evidence/20260728_BAS_118_SCOPED_MARKET_RADAR.md)
- [Verifier-owned Project/Engineering Graph kernel evidence](evidence/20260728_BAS_128_PROJECT_ENGINEERING_GRAPH_KERNEL.md)
- [Authenticated scope-authority review-lineage evidence](evidence/20260728_BAS_130_AUTHENTICATED_SCOPE_AUTHORITY_REVIEW.md)
- [Project operating-subject binding evidence](evidence/20260728_BAS_131_OPERATING_SUBJECT_BINDING.md)
- [Health scheduler Graph observation evidence](evidence/20260728_BAS_132_HEALTH_SCHEDULER_GRAPH_OBSERVATION.md)
- [Scheduler activation and Supabase bootstrap evidence](evidence/20260729_BAS_136_SCHEDULER_ACTIVATION_AND_SUPABASE_BOOTSTRAP.md)
- [Authenticated Web runtime acceptance evidence](evidence/20260729_BAS_137_AUTHENTICATED_WEB_RUNTIME_ACCEPTANCE.md)
- [Browser Capture Inbox ADR](../adr/ADR-0059-browser-capture-inbox.md)
- [Browser Capture Inbox engineering/runtime evidence](evidence/20260729_BAS_138_BROWSER_CAPTURE_INBOX.md)
- [Maozi ERP full capability benchmark evidence](evidence/20260729_BAS_139_MAOZIERP_CAPABILITY_BENCHMARK.md)
- [Exact-scope sale-triggered procurement review evidence](evidence/20260729_BAS_140_SCOPED_SALE_TRIGGERED_PROCUREMENT.md)
- [Native scoped OMS current-state/timeline evidence](evidence/20260729_BAS_141_NATIVE_SCOPED_OMS.md)
- [Native scoped inventory/fulfillment ADR](../adr/ADR-0062-native-scoped-inventory-fulfillment.md)
- [Native scoped inventory/fulfillment evidence](evidence/20260729_BAS_142_NATIVE_SCOPED_INVENTORY_FULFILLMENT.md)
- [Market-validated native parity and Agentization ADR](../adr/ADR-0063-market-validated-native-parity-and-agentization.md)
- [Market-validated AI ERP baseline evidence](evidence/20260729_BAS_143_MARKET_VALIDATED_AI_ERP_BASELINE.md)
- [Native exact-scope PIM ADR](../adr/ADR-0064-native-exact-scope-pim-workspace.md)
- [Native exact-scope PIM evidence](evidence/20260729_BAS_144_NATIVE_EXACT_SCOPE_PIM.md)
- [Native scoped sourcing-intelligence ADR](../adr/ADR-0065-native-exact-scope-sourcing-intelligence-workspace.md)
- [Native scoped sourcing-intelligence evidence](evidence/20260729_BAS_145_NATIVE_SCOPED_SOURCING_INTELLIGENCE.md)
- [Authorized Seller ERP Bridge ADR](../adr/ADR-0066-authorized-seller-erp-bridge-canonical-diff.md)
- [Authorized Seller ERP Bridge evidence](evidence/20260729_BAS_146_AUTHORIZED_SELLER_ERP_BRIDGE.md)
- [Native exact-scope Listing lifecycle ADR](../adr/ADR-0067-native-exact-scope-listing-lifecycle.md)
- [Native exact-scope Listing lifecycle evidence](evidence/20260729_BAS_147_NATIVE_EXACT_SCOPE_LISTING_LIFECYCLE.md)
- [Native exact-scope content media factory ADR](../adr/ADR-0068-native-exact-scope-content-media-factory.md)
- [Native exact-scope content media factory evidence](evidence/20260729_BAS_148_NATIVE_EXACT_SCOPE_CONTENT_MEDIA_FACTORY.md)
- [Native exact-scope settlement and cash control ADR](../adr/ADR-0069-native-exact-scope-settlement-cash-control.md)
- [Native exact-scope settlement and cash control evidence](evidence/20260729_BAS_149_NATIVE_EXACT_SCOPE_SETTLEMENT_CASH_CONTROL.md)
- [0.59 PM release gate review](reviews/20260727_GATE_PM_059.md) — remains `REJECTED`
- [0.59 RA release gate review](reviews/20260727_GATE_RA_059.md) — remains `REJECTED`

The BAS-136 continuation now has four distinct auto-confirmed Supabase Auth
users bound to the subject/owner/risk/admin actors. Real password-token checks
returned HTTP `200` for all four users, authenticated Web login returned `303`
to `/`, and the live secret-free Authority topology is `passed/fresh` with four
bindings and both API/Web chains ready. At that BAS-136 checkpoint the canonical
Graph was `32 tasks / 110 nodes / 123 edges / 204 observations / 77 bindings`,
`26 passed / 4 blocked / 2 no_data / 0 stale`. M0 current authority remains
`no_data`; no source/review/grant, Approval or Permit was synthesized, external
write remains false and Release `0.59` remains `REJECTED`.

The active implementation wave remains `M1 Intelligence/Candidate`, with the
cross-wave M3 BAS-140 order-to-procurement-review safety slice completed in
engineering and BAS-141 native scoped OMS also completed in engineering. The
current Graph after BAS-141 contains `40 tasks / 130 nodes / 141 edges` and an
append-only observation ledger (`>=268` at final reverification); real order authority is
still `no_data`. No `Ozon`, supplier, purchase, payment, or ads
external write is opened by this entry, and pricing remains `not_for_sale` until later gates explicitly
change that status.

The BAS-144–149 native-parity continuation has now delivered one exact-scope
PIM projection, one sourcing-intelligence projection, and one authorized
Seller ERP Canonical Diff, plus one observed/desired/reviewed/approved/dry-run/
readback Listing lifecycle projection, and one Product/Asset-centered content
media factory projection, plus one exact-scope Order/Accrual→Settlement→Bank
Cash three-book control projection. Seller ERP source admission is an explicit three-party
Evidence workflow with append-only revocation and no private endpoint, Cookie or
internal-token path. Listing lifecycle uses exact-as-of append-only Approval
decisions and keeps platform readback distinct from desired or approved state.
The media factory keeps source rights, fixed-template admission, execution/event
timeline, QA and Delivery Manifest separate and fails closed on future state or
hash/transition drift. Settlement control separates native scoped finance
authority from legacy rows, prohibits proportional allocation, and will not
display Actual Cash CM3 without three-book and native profit reconciliation.
The independently verified engineering Graph now contains
`76 tasks / 183 nodes / 186 edges / >=320 observations`. Real Product candidates,
Listing Drafts, Bridge Evidence, ContentAsset/Execution/Manifest, Order,
Inventory, Settlement and Cash remain `0/no_data`; this work does not open any
third-party write, Approval or Permit and does not change the rejected Release,
Pilot or Final Gates.

### 2026-08-02 Day 0 profit-truth correction

- `channel-accounts workspace=ready` is scoped only to the channel-account authorization control
  plane. Real catalog and finance read evidence is retained and the exact-scope read-only
  projection passed; this does not prove the full BAS-160 managed Worker execution path.
  Real order, platform settlement, bank cash and every provider write path have not passed;
  BAS-160 remains `IN_PROGRESS`, and Actual Cash Profit remains `no_data`.
- The retained market-recon projection contains 374/374 source rows, 18 Ozon SKUs, 99 identity
  sources and 114 finance operations. It has zero complete scoped FX records, zero formal Facts,
  zero scoped FinanceEntry rows and zero ProfitDecisionSnapshot rows. Therefore it is a truth and
  remediation workspace, not a profit result or scale authorization.
- Profit-growth thresholds remain `UNKNOWN`: downside CM3, return/refund rate, CAC/ACOS,
  fulfillment lead time and working-capital occupancy. They require signed operating and finance
  Evidence with an explicit formula, scope and validity window. Neither deterministic code nor an
  Agent may infer these values or promote them into a Pilot/scale Gate.

## 21. One-person accountable dual-engine operating system

KJDS uses one accountable Business Owner but never collapses research, finance, risk, approval and
execution into one identity. The stable operating contract is
`docs/project/14_ONE_PERSON_DUAL_ENGINE_OPERATING_SYSTEM.md`; the architecture decision is
`docs/adr/ADR-0089-one-person-dual-engine-operating-system-and-frontier-adoption.md`; the
date-bounded research record is
`docs/project/evidence/20260803_DOUYIN_MINDSET_AND_FRONTIER_TECH_RESEARCH.md`.

The shared business loop is:

```text
evidence-backed signal or content
  -> qualified problem
  -> scoped diagnosis
  -> paid bounded MVP
  -> measured delivery
  -> consented case evidence
  -> reusable module
  -> managed product or software capability
  -> renewal, referral and next demand signal
```

The front plane owns positioning, content and qualification; the middle plane owns diagnosis,
scope, value hypothesis, proposal and Pilot; the back plane owns delivery, customer success, case
abstraction and productization. Profit/cash truth, Evidence/compliance, identity/authority and
platform/data/AI controls cross every plane. Content is a demand experiment and qualification
surface, never a Fact source or a substitute for real orders, settlement, bank cash or customer
consent.

The Russia operation and software business share canonical Product, Evidence, Profit, Scope,
Approval, Permit and audit primitives, but they do not share raw customer data across tenants.
Only explicitly licensed, de-identified and non-reversible patterns may become reusable knowledge.
The offer ladder is public education -> paid diagnosis -> bounded Pilot -> managed implementation
-> isolated subscription -> self-service SaaS. Before C0, only preparation and truthful public
education are allowed; any paid offer requires C0, and self-service multi-tenant SaaS additionally
requires G7. Third-party screenshot prices, income and customer outcomes remain unverified
observations and cannot authorize pricing or claims.

Frontier adoption is governed by
`docs/project/registries/frontier_technology_adoption.json`. Every candidate is one of
`adopt_now`, `pilot`, `watch` or `reject_now`, with official/primary evidence, risk, owner, entry
Gate, exit Gate and review date. Current priority is to deepen the existing Agent trace/eval,
Evidence, Graph, Outbox, PostgreSQL and G1 seams. Temporal, GraphRAG, MCP Tasks/A2A, PostgreSQL 18,
SPIFFE/OPA, WebDriver BiDi, torchao, ClickHouse and Iceberg do not become production dependencies
from research or registry status alone.

`BAS-171` freezes this contract and its machine-readable radar. `BAS-172` is the next engineering
slice: persist a provider-neutral, redacted AgentRun/Eval Evidence envelope that links the existing
in-process trace and eval to model, prompt-template, tool, Evidence, authority, cost, latency and
outcome versions. It remains proposal-only and cannot promote Fact, FinanceEntry, Approval, Permit
or external write.

`BAS-177` deepens the existing Loop Engineering registry into a governed TeamAgent evolution
contract. Corrections, verified failures, evidenced outcomes and official source changes may create
Observations or versioned candidates only. Eval, baseline comparison, negative/scope tests, shadow,
independent review and rollback are mandatory before promotion. Canonical Graph learning is
temporal and source-hashed; generated nodes/edges are Observations, raw cross-tenant learning is
forbidden, and runtime Agents cannot self-modify code, authority, Facts, Approval, Permit or
external-write policy. Continuous frontier review can propose a registry change but cannot install a
dependency or change a Gate automatically.

## 22. Global cross-border expert council

The frozen operating choice is `ai_core_human_professional_review +
global_research_russia_ozon_execution_first + business_decision_high_risk_dual_sign`.
One `global_chief_commerce_officer` coordinates twelve bounded specialist seats through the
`GlobalPortfolioOrchestrator` interface. The coordinator may prioritize, allocate internal work,
resolve business trade-offs and stop work, but cannot verify its own proposal, override a failed
professional Gate, issue a Permit, hold marketplace credentials or perform an external write.

The machine source is `docs/project/registries/global_expert_team_registry.json`; the operating
contract is `docs/project/17_GLOBAL_CROSS_BORDER_EXPERT_TEAM.md`; the architecture decision is
`docs/adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md`. Until named human owners,
licensed reviewers and existing Gate evidence are current, the council remains proposal/shadow and
does not change Russia entry, commercial sale, payment, platform-write or Actual Cash CM3 status.

## 23. Exact-scope team control tower

`TeamControlTower.brief(...)` is the single leadership read interface for the four active user
workflows. It validates current exact-scope authority before reading OperatingTask, combines the
authoritative active-workstream registry with the global expert-team contract, reports WIP/write
scope conflicts, and emits exactly one state-bound continuation. `advance(...)` is the only command
interface; it progresses work through the existing OperatingTask/Event ledger with bounded results,
Evidence requirements and idempotency checks.

The control tower is coordination infrastructure, not proof of a business outcome. It creates no
Fact, finance entry, Approval or Permit and performs no provider write. Named human owners,
professional review, Russian order/settlement/bank Evidence, Actual Cash CM3 and the first paid C0
customer remain separate hard gates. The machine source is
`docs/project/registries/team_control_tower_registry.json`; the operator and owner runbook is
`docs/project/18_TEAM_CONTROL_TOWER.md`.

## 24. 90-day Top1 organization and delivery control

The 2026-08-07 baseline deepens the existing Team Control Tower; it does not introduce another
campaign, organization, finance, Gate, audit or task authority. The machine contract freezes 18
core role contracts, the existing 12 AI specialist contracts, a 20–40 person on-demand expert-pool
capacity target and the existing five independent control roles. A registry count is a staffing
requirement, not appointment Evidence. Until primary and alternate human bindings, professional
scope, conflicts, budget cap and maximum loss are independently evidenced, organization readiness
remains `UNKNOWN`.

The four campaign phases are day 1–7 organization freeze, day 8–30 real operating inputs, day
31–60 internal Alpha and cash loop, and day 61–90 commercial delivery plus dimension audit. The
planned interval is 2026-08-07 through 2026-11-04. Without an immutable kickoff event the actual
campaign day is `UNKNOWN`; a planned date cannot pass a Gate. A–E, I, L and M are active battle
lanes, while F–H remain preparation-only and cannot take resources from the Russian cash loop.

The twelve-dimensional scorecard selects only metrics already registered in
`strategic_benchmark_contracts.json`. It consumes the latest unique exact-scope benchmark snapshot,
preserves the existing leader observation references and never recomputes rank. A metric may show
`METRIC_LEADER` only when at least five eligible peer/frontier observations exist and the current
KJDS observation is already in those leader references. This is a metric/cohort/market/window result,
never a global Top1 claim. Cash forecasting is similarly authority-bound: missing opening bank
balance, CashPlan, FX basis, signed cash floor or approved maximum loss produces `UNKNOWN`, not zero
or an inferred forecast.

Organization, critical path, Top1, cash and five delivery Gate projections each carry their own
truth state, reasons, sources, as-of and SHA-256. Their hashes join the existing scope, flow,
workstream and conflict state in `decision_basis_sha256`; `advance` accepts only the continuation
bound to that exact basis. Engineering completion proves that this control projection, Web surface
and negative controls work. It does not prove real staffing, a real SKU cash reconciliation, a C0
design partner, production SLO/RPO/RTO or any market-leading claim.

## 25. Enterprise AI ERP leadership projections

The BAS-215B increment connects the BAS-215A static Enterprise AI ERP contract to the existing
`TeamControlTower`; it does not create an ERP execution authority. After exact-scope validation,
`brief(...)` reads the in-process, zero-argument `EnterpriseAiErpProgram.project()` contract and
white-lists six leadership projections: `squad_readiness`, `role_conflicts`,
`parallel_execution`, `integration_queue`, `capacity_risk` and `next_release_train`. The external
Interface remains `brief/advance`; runtime only constructs and injects the named dependency.

Every one of the six projections remains `UNKNOWN` until the corresponding human identity,
OperatingTask, runtime capacity or release authority is connected. A verified static contract means
only that the 14 roles, eight Squads, six EAERP work contracts, SoD rules, concurrency limits and
release-train policy are internally consistent. It does not prove appointment, WIP, available
capacity, achieved maturity, Gate PASS, a scheduled release or any customer or operating result.
The integration queue starts as `NOT_STARTED`; its dependency graph and parallel waves are planning
contracts, not execution facts.

Scope-invalid requests return six explicit `UNKNOWN` projections without calling the Program.
Missing optional injection also returns `UNKNOWN`; a malformed contract ID/version, inconsistent
source bundle, invalid snapshot, promoted dynamic truth or permissive authority envelope raises a
fail-closed control error. The BAS-215A registry, source-bundle and compiled snapshot hashes are
pinned in the Tower contract, so a self-consistent but unapproved resealed projection is also
rejected. Those trusted hashes remain inside the
decision semantics, so a contract change invalidates the old continuation. Observation `as_of`
continues to affect the audit snapshot but not the action decision when all authority semantics are
unchanged. This increment adds no database, migration, router, API, OpenAPI, Web, G-1 or external
write capability.

## 26. Enterprise AI ERP strict API and owner workbench

BAS-215C publishes the six BAS-215B leadership projections through the existing brief route and
owner workbench. The route now uses one strict full-response model rather than an unconstrained
object. Its saved OpenAPI response is a named `$ref`, rejects undeclared top-level fields and
requires all six projections. The model accepts the deliberately smaller scope-invalid and
dependency-missing `UNKNOWN` variants, so serialization cannot invent readiness or turn absence
into an HTTP failure.

The Web contract requires the same six fields and renders them in server order. Each panel shows
the supplied status, reason codes, contract details and nullable runtime observations. The client
does not sort the integration DAG, derive role conflicts, subtract WIP from limits, choose a
release candidate or promote a Gate. A visible statement distinguishes verified static contract
integrity from human staffing, active work, available capacity and a scheduled release.

The surface uses semantic sections and headings, native disclosure controls, live status/error
announcements, visible keyboard focus and responsive grids that collapse without horizontal
overflow at 390px. The command surface and `advance` contract are unchanged. This increment adds
no execution authority, dependency, database, migration, G-1 or provider write.

## 27. BAS-217 runtime-owned Profit receipt authority

BR-143 的“独立回读”由 server-owned `ScopedProfitOrderSkuReceiptAuthority` 实现，而不是由
可变 Profit projection adapter 自报。runtime 从 canonical engine、finance、Evidence 与 scoped
Evidence dependencies 独立构造 Profit projection 与 receipt verifier 两个对象，再分别注入
`ScopedSettlementCashWorkspace`；Settlement 禁止从 adapter 动态发现 verifier。receipt authority
的 `source_profit_snapshot_sha256` 必须等于本次实际消费的 Profit snapshot，否则即使 receipt、
row、顶层 projection 和 verified-looking authority 被联合重签，也只能返回 `no_data`，两个
verified count 必须为零。本增量不增加数据库、迁移、router、API/OpenAPI、Web、G-1 或外写。
