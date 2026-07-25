# KJDS 主规格：AI 原生跨境电商经营控制平面

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-MASTER-SPEC-001 |
| status | Active |
| version | 7.8 |
| last_reviewed | 2026-07-25 |
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
| BR-066 | 受控货源采集与真实连接器状态 | KJDS 必须复用 `CommerceConnector` 和 Research Inbox 接入 1688 CLI、OpenCLI 1688 Adapter 及既有 Ozon 官方读取路径；统一输出版本化商品、市场、素材和供应商消息快照，以 provider、稳定记录 ID 和内容哈希精确去重，字段变化追加历史。单轮最多 20 个候选、每候选 5 家供应商；连接器状态必须明确工具安装、浏览器桥接、登录、最近成功、Schema 和稳定错误码。登录、MFA、CAPTCHA、账户歧义或 Schema 漂移必须失败关闭并要求人工接管。采集只形成 `research_signal`，不得自动晋升正式报价、创建 Product、发送消息、改购物车、下单、支付或写平台；SKU 只读工作台只聚合既有事实与 Gate。 | P0 |

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
- Ozon Listing 草稿的 `images` 必须全部来自请求中明确列出的、同一商品且状态为 `approved` 的图片 ContentAsset 产物证据；草稿保存内容资产 ID 作为血缘。创建草稿仅建立 `listing.publish` 待审批对象，未提供平台写执行器，也不得把审批请求解释为发布。
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
| ADR-0018（Accepted） | 受控货源采集 | `CommerceConnector` Adapter、统一快照、哈希去重、真实健康、人工接管与 SKU 读模型 |
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
