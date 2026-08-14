# 抖音思维材料与前沿技术研究 Evidence

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-EVD-DMFT-20260803 |
| date | 2026-08-03 |
| status | Research evidence, not a Gate approval |
| owner | 项目总控 |
| scope | 18 张本地思维截图的业务逻辑提炼；官方或一手前沿技术来源；映射到 KJDS 俄罗斯 Ozon 经营与软件商业化双引擎 |
| source_access_date | 2026-08-03 |
| external_write | false |
| commercial_claim | false |
| runtime_truth_changed | false |

本文是研究切片，不是营销材料、收入预测、客户案例证明、技术选型批准或生产放行记录。
本研究记录本身不改变运行时真相、Gate 或外部写权限；同一合流通过 ADR、`MASTER_SPEC`、
动态计划和采用注册表登记 BAS-171 决策，但这些治理变更不能反向把研究结论冒充实现证据。

## 1. 证据分层与使用规则

本文严格使用以下四种标签，任何下游引用都必须保留标签：

| 标签 | 定义 | 可以用于 | 不可以用于 |
|---|---|---|---|
| `OBSERVATION` | 从 18 张本地截图及其 OCR 中观察到的表达、叙事或主张 | 形成待验证假设、访谈问题、产品实验 | 证明博主身份、收入、客户结果、方法有效性或 KJDS 商业结果 |
| `VERIFIED_PRIMARY_SOURCE` | 2026-08-03 访问的官方规范、官方产品文档或原始研究论文 | 描述来源明确公开的技术能力与状态 | 证明 KJDS 已实现、已上线、已适合生产或能产生商业收益 |
| `INFERENCE` | 项目根据 Observation、Primary Source 与现有 KJDS 约束形成的推断 | 设计实验、排优先级、定义 Gate 和验收指标 | 冒充市场事实、法律意见、财务事实或自动放行依据 |
| `UNKNOWN` | 当前没有足够、同作用域、可复验 Evidence 的结论 | 进入补证队列、保持 fail-closed | 猜值、按零处理、写入正式 Fact、对外承诺 |

使用原则：

1. 截图中的平台账号、发布时间、学历、工作经历、收入、客单价和客户结果均未被独立核验。
2. 截图中存在平台自动生成或 AI 生成的总结，它们只能证明“截图出现了该文本”，不能证明文本正确。
3. OCR 可能出现漏字、错字和顺序偏差。本文只提炼多张截图重复出现且语义稳定的结构，不依赖单个模糊数字或单句措辞。
4. 官方技术来源只证明公开能力或规范状态。能否进入 KJDS 生产路径，仍需适配、威胁建模、基准、成本、回滚和 G1/Gate 证据。
5. 所有“增收、降本、提效、获客”结果都必须绑定客户/店铺/SKU exact scope、基线、观察窗口、归因方法、币种和 Evidence。

## 2. 本地材料来源与完整性边界

来源目录：`D:\KJDS\ozon\抖音资料\思维`。

本次分析覆盖 18 张 `1240x2772` 竖屏 JPG。2026-08-03 复算的原图 SHA-256 如下，
后续复核必须同时匹配文件名与哈希：

| 顺序 | 文件名 | SHA-256 |
|---|---|---|
| 01 | `0616c5948208ae392774a0d5cd373df7.jpg` | `dbc53734dd29bb07d96064599e53e69a9c5de426d1b3d4ba981609a2dae6cb77` |
| 02 | `61b9d4835ea82ff042784177547c98d1.jpg` | `844f260ba60b777e3fde2c662514a398307dab0008155d48f0de576666eb5519` |
| 03 | `43a7e165ca7c5632381e2746d9a7bb58.jpg` | `1b18517f573612a30ec680c394d2b8bb498c337e4ee3c8646b509b9d9e5d4ecf` |
| 04 | `bcaac66749c5694bb2a9f1555423a8e2.jpg` | `9aafd79185755721591ccd07e22019d1c7645754ba6457757328b095ae20e18b` |
| 05 | `d88e1b0123a0074b6bffddf5f7cc7562.jpg` | `10f10a0e8f44b3320212aa6092b70748a45ca90e0c604f25a4cb7f39c64d7b69` |
| 06 | `f20d08a63e48933a7eb89b34600061b9.jpg` | `248e075bd1249f6f107d93fe306389a7ce71f4d1c71daf05a30ae3c40a7ba4f7` |
| 07 | `8b93191604023afdc7d4e04fb8771eb5.jpg` | `6d1fd61c6e80c8173089fc1214a7a20a36a842a31edfe19d7c02438b0c79609a` |
| 08 | `91aae03f11a42815b08761bd0fb69bba.jpg` | `cf7eeb0f164f1e28ef8fa1f0b210b2485c71017de340f46cfae6a65f05556a54` |
| 09 | `32fcedc0feba4865d9d407aa62d30e59.jpg` | `125fbc4fca93db18e2a5ce1da41818aa78137eb1c49993f63e3e316a065a78cf` |
| 10 | `eb18da621642b2215b4ded159f171b85.jpg` | `338ea4626fa94f6e7d7ab2a7ce0de02544ba060c2682fadadf0b660165afeab9` |
| 11 | `9f243347495bcd13a2272715a9b777dc.jpg` | `b1cf528b54f890ecfb0862c4e05ca327fed11eee7d176a35c22fc84029cc73dd` |
| 12 | `68d77e0ccd20bbc1291095160b28f8c3.jpg` | `daab8572eeaa3d7116d0fda396d9aa1f548e7e37b2c72327df6209e2009e10a4` |
| 13 | `5b729cb51e63d94c24c257f29256a67e.jpg` | `e70274f6fe748ba0b214ed27f6412598fa79814f0d4dd53b0775ab2ee5b527d4` |
| 14 | `2597a3867f06072fc8bf24b360360f25.jpg` | `a30825076e6a20bcff21861ab4e445a8445ca20aa136018f10283712ddc74f03` |
| 15 | `33b08b6d8733f3bc2a9d247f0612fc07.jpg` | `3f262b8dcb5e5a88796c9e2e923619297c169167ce3841fff54c1f476985dd8f` |
| 16 | `e1d18716820b8cabb76393a9406abc8b.jpg` | `7450225098b587b9f66643ab9a0500c2ac79b16cb4154bc30e4d18498654e1c7` |
| 17 | `b0bf6d981f66512e354d36f1b6f39e41.jpg` | `5082708cb4c940ef20b78dab233cd615d7a3ad5643b3fc74cfa764ce4db92b36` |
| 18 | `3ef14b5ce40520f03df5565945ee7a92.jpg` | `49c90ebc9dfe544809f372aa4d602e2644111b3182512a00d3288434c81921ff` |

OCR 中间结果位于仓库忽略目录 `.runtime/douyin-mindset-ocr/`，不作为正式 Fact，不进入
Git。本文没有把原图、OCR 全文、账号标识或评论者身份复制进仓库。

以下仍为 `UNKNOWN`：原帖 URL、账号真实控制人、原始发布时间链、截图是否完整、内容是否
被编辑、成交合同、收款凭证、客户授权、客户基线、结果归因、退款情况、交付成本和持续留存。

## 3. 截图中的业务逻辑 Observation

### 3.1 Observation ledger

| ID | 截图中反复出现的内容 | 证据状态 | 限制 |
|---|---|---|---|
| OBS-001 | 叙事主体把业务描述为一人公司，并把经营拆为定位、产品、流量、交付和成交五部分 | `OBSERVATION` | 未核验主体身份、经营实体与真实组织规模 |
| OBS-002 | 反对按“先做产品、再获客、再成交”的线性顺序，主张前端、中端、后端相互反馈的动态系统 | `OBSERVATION` | 未证明该结构优于其他模型 |
| OBS-003 | 前端以内容回答真实复杂问题，同时观察需求、语言和案例 | `OBSERVATION` | 内容数据、样本量和渠道归因未知 |
| OBS-004 | 中端通过诊断、匹配度筛选和销售沟通，把问题转成有边界的付费交付 | `OBSERVATION` | 成交率、销售周期、拒绝率和退款率未知 |
| OBS-005 | 后端把交付案例拆解、建模并沉淀为可复用模块，再反向提升内容、成交与交付 | `OBSERVATION` | 模块复用率、维护成本和客户间数据边界未知 |
| OBS-006 | 内容被描述为筛选器，而不是追求所有流量；短内容测试需求，长内容建立理解与信任 | `OBSERVATION` | 粉丝质量、触达成本、平台波动和可迁移性未知 |
| OBS-007 | 获客路径呈“逆漏斗”：先公开认知和问题框架，让理解方法的人自我筛选，再进入少量深度诊断 | `OBSERVATION` | “逆漏斗”为本文概括，原始漏斗数据不存在 |
| OBS-008 | 先以较小范围付费 MVP 获取真实需求与种子案例，再发展更深、更高客单的系统交付 | `OBSERVATION` | 截图中的价格与收入未核验，不作为定价依据 |
| OBS-009 | 交付被描述为通用算法/思维内核与客户交互/应用层解耦，后者按客户场景定制 | `OBSERVATION` | 没有源代码、架构、测试或可复验算法证据 |
| OBS-010 | 产品主张根据后验结果持续更新检测指标，形成动态决策系统 | `OBSERVATION` | 是否自动更新、如何防止漂移、谁批准均未知 |
| OBS-011 | 价值定价叙事强调解决战略级问题、降低试错成本，而不是按交付小时计价 | `OBSERVATION` | 预期价值不是已实现结果，不能据此承诺 ROI |
| OBS-012 | 严格筛选客户与交付匹配度被视为满意度和高客单关系的前提 | `OBSERVATION` | 客户满意度、续费和增购数据未知 |
| OBS-013 | 截图声称曾取得收入、客单提升、大客户成交和客户满意度等结果 | `OBSERVATION` | 无合同、付款、基线、对照、客户确认；禁止作为事实引用 |
| OBS-014 | 截图把结构化思维、数学建模、概率推断和因果链分析描述为差异化能力 | `OBSERVATION` | 具体模型、准确率、校准、适用范围和风险未知 |

### 3.2 可迁移的方法骨架

以下是 KJDS 对上述 Observation 的结构化提炼，全部属于 `INFERENCE`：

```text
前端：问题内容 + 需求观测 + 资格筛选
  -> 中端：诊断 + exact scope + 价值假设 + 付费 MVP 合同
  -> 后端：受控交付 + Evidence + 结果复盘 + 案例拆解
  -> 产品化：通用内核 + 场景模块 + 标准验收 + 版本化资产
  -> 再反馈：更精确的内容、ICP、报价、交付与产品优先级
```

该骨架的价值不是模仿某个博主，而是把“市场学习、销售、交付、产品研发”放入一个
可观测闭环。KJDS 必须额外加入截图中没有得到充分证明的四个横切系统：

| 横切系统 | KJDS 必须补足的内容 |
|---|---|
| 利润与现金 | 四本利润、十五项成本、FX、结算、银行到账、交付毛利和支持成本 |
| Evidence 与治理 | 来源、完整性、作用域、有效期、人工批准、Permit、审计与复验 |
| 客户成功 | 首次可信价值、实施工时、采纳/拒绝、续费、退出和数据返还 |
| 安全与合规 | 租户隔离、凭证、PII、平台条款、俄罗斯/EAEU 合规、税务和制裁人工门 |

## 4. KJDS 双引擎映射

### 4.1 统一飞轮

`INFERENCE`：KJDS 不应把俄罗斯电商与 SaaS 当成两个割裂项目。两者共用 Product、
Evidence、Profit、Scope Authority、Approval、Permit 和审计内核，但保持经营账本与
客户商业元数据的边界。

```text
俄罗斯 Ozon 自营/受控经营
  -> 真实商品、订单、费用、退货、结算、到账 Evidence
  -> 识别可复验的止损、提效、降本或增收问题
  -> 脱敏案例与诊断内容
  -> 筛选具备真实账户、数据和负责人条件的中国出海卖家
  -> 付费诊断 MVP
  -> 单客户隔离的设计伙伴交付
  -> 把重复问题沉淀为共享内核、连接器、规则和工作台模块
  -> 软件续费与客户反馈反哺产品
  -> 改善下一轮自营经营和客户交付
```

跨客户学习只能使用经过同意、最小化、去标识且不泄露租户数据的模式级知识。任何客户
原始数据、凭证、订单、利润或 Evidence 不得被默认并入共享模型或另一个客户的上下文。

### 4.2 前端、中端、后端在两个引擎中的职责

| 层 | 俄罗斯经营引擎 | SaaS 商业引擎 | 统一验收 |
|---|---|---|---|
| 前端 | 市场观测、选品假设、Ozon 需求/竞争 Evidence、内容素材 | 问题型内容、诊断清单、伙伴渠道、合格线索筛选 | 内容不冒充 Fact；每条线索有来源、ICP 匹配和同意状态 |
| 中端 | 候选诊断、合规/利润/物流缺口、G0-G4 Gate、人工审批 | 发现会、exact-scope 数据授权、价值基线、付费 MVP SOW、C0/S0-S2 Gate | 问题、范围、Owner、基线、期限、价格、成功/停止条件明确 |
| 后端 | Product/Evidence/Profit 真相、只读工作台、受控动作、结算到账复盘 | 隔离部署、实施、验收、客户成功、计费/权益、支持和恢复 | 交付结果绑定 Evidence；不存在“口头成功”或模型自证 |
| 产品化 | 把重复经营问题沉淀为可复用规则、连接器和 UI | 把重复交付沉淀为套餐、模块、SLA、实施模板和自助能力 | 通用内核与客户配置分离；版本、兼容、回滚和成本可测 |

### 4.3 内容筛选与逆漏斗

`INFERENCE`：KJDS 的内容不是流量 KPI，而是低成本的需求实验和资格预审。推荐漏斗为：

```text
真实问题 Evidence
  -> 一页问题清单/匿名案例/利润误区内容
  -> 明确写出适合与不适合对象
  -> 自助资格问卷
  -> 30-45 分钟发现会
  -> 有边界的付费诊断 MVP
  -> 设计伙伴试点
  -> 年付经营工作台或托管服务
```

必须同时记录分母和拒绝原因，避免把“少量高意向沟通”错误解释为高转化。首批内容仅应
使用已脱敏、已获发布授权且能回链 Evidence 的事实；不得使用截图中的未核验收入或客户
结果作为 KJDS 背书。

### 4.4 付费 MVP 与案例模块化合同

`INFERENCE`：付费 MVP 不是廉价定制开发，而是最小可信价值合同。建议固定字段：

| 字段 | 必须内容 |
|---|---|
| customer_scope | 客户、主体、店铺、角色、数据源、用途和有效期 |
| problem_statement | 客户当前无法回答的经营问题，不写泛化“AI 提效” |
| baseline | 当前工时、差错、利润缺证、损失或周期；无证据则 `UNKNOWN` |
| deliverable | 只读诊断、Evidence 缺口、至少一个 SKU 投影和下一动作 |
| success_metric | 首次可信价值时间、客户确认的问题、可执行动作和验收人 |
| stop_condition | 数据不可用、权限不合法、利润口径未签署、成本失控或不匹配 |
| productization_right | 客户数据不共享；仅允许沉淀不含租户信息的通用能力 |
| post_review | 结果、偏差、支持工时、毛利、复用候选和拒绝原因 |

案例进入共享模块前必须完成：问题稳定、输入/输出合同稳定、至少两个独立作用域复现、
租户数据隔离、安全评审、成本可接受、回滚可用。单一客户定制不得直接升级为平台标准。

### 4.5 高客单系统交付边界

`INFERENCE`：高客单可以来自复杂度、责任、风险降低、实施和持续价值，但不能来自未经
证实的预期叙事。KJDS 的报价应拆分诊断、实施、软件权益、托管、支持与可选效果费，且：

1. `C0 Commercial Pilot Gate` 前保持 `not_for_sale`，不得收款或形成应收。
2. 不按截图价格定价；使用交付成本、客户可验证价值、替代成本、风险和付费实验校准。
3. 不保证盈利、GMV、排名或市场份额；效果费只能基于双方签署的增量实际现金 CM3。
4. 通用内核持续升级，客户场景通过配置、Policy、Skill 或 Adapter 承载，禁止复制第二真相源。
5. 任何自动动作仍受 exact scope、Approval、一次性 Permit、回读和补偿控制。

## 5. 前沿技术 Primary Source ledger

本节仅纳入官方规范、官方产品文档或原始论文。所有链接访问日期均为 `2026-08-03`。

### 5.1 Agent runtime、协议与可观测性

| ID | 一手来源 | `VERIFIED_PRIMARY_SOURCE` 摘要 | KJDS 采用边界 |
|---|---|---|---|
| PS-001 | [OpenAI: New tools for building agents](https://openai.com/index/new-tools-for-building-agents/) | Responses API、内置工具、Agents SDK 与 tracing 被作为 Agent 构建组件公开 | `PILOT`。只经 Model Gateway/Agent Harness 接入；不绕过 Evidence、Authority、Approval 或 Permit |
| PS-002 | [OpenAI: Responses API tools and features](https://openai.com/index/new-tools-and-features-in-the-responses-api/) | 官方描述远程 MCP、后台任务与加密 reasoning items 等能力 | `PILOT`。后台运行仍需 durable state、取消、超时、重试和结果签名；加密 reasoning 不等于业务 Evidence |
| PS-003 | [OpenAI: WebSocket mode for agentic workflows](https://openai.com/index/speeding-up-agentic-workflows-with-websockets/) | 官方提供持久 WebSocket 会话以减少多轮 Agent 循环的连接开销 | `WATCH/PILOT`。先测真实延迟与故障恢复；经营正确性优先于 token 延迟 |
| PS-004 | [OpenAI: Responses API computer environment](https://openai.com/index/equip-responses-api-computer-environment/) | 官方提供计算机环境、Skills、compaction 与 hosted shell 等能力 | `PILOT`。浏览器/桌面能力放隔离执行器；禁存 Cookie；Seller API 仍是首选 |
| PS-005 | [OpenAI model catalog](https://developers.openai.com/api/docs/models) | 官方模型目录提供当前模型、上下文和能力信息 | `ADOPT_INTERFACE`。业务逻辑不硬编码厂商型号；按风险、质量、延迟、成本与 eval 路由 |
| PS-006 | [MCP Tasks specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks) | MCP Tasks 定义任务创建、轮询、结果与取消语义，规范标记为 experimental | `WATCH/PILOT`。可映射现有 OperatingTask/AgentRun，但实验规范不能成为生产唯一状态机 |
| PS-007 | [MCP Authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) | MCP 授权基于 OAuth 2.1，并强调资源绑定、受众校验、增量 scope 和禁止 token passthrough | `PILOT`。每个 MCP server 单独 audience；最小 scope；高风险动作 step-up；通过跨 audience、撤销和 scope 漂移负向验收前不成为生产依赖 |
| PS-008 | [A2A v1.0 announcement](https://a2a-protocol.org/latest/announcing-1.0/) 与 [latest specification](https://a2a-protocol.org/latest/) | A2A 提供 Agent 间发现、任务、消息和 artifact 互操作规范 | `WATCH`。当前页显示 v1.0，但 KJDS 暂不引入跨组织 Agent 网络；先保持内部深模块合同 |
| PS-009 | [Temporal](https://temporal.io/) 与 [AI reference architecture](https://go.temporal.io/platform-hub/ai-engineering/ai-reference-architecture) | Temporal 官方把 durable execution、重放和 Activity 隔离作为长流程可靠性基础 | `PILOT`。先复用现有状态机/outbox；仅对超长 Listing、采购、市场侦察流程做 adapter POC，不双写真相 |
| PS-010 | [Anthropic: Context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 一手工程文章强调上下文选择、压缩、工具结果管理和长任务信息卫生 | `ADOPT_NOW`。运行时保存结构化状态与 Evidence 引用，不把完整历史无限塞入 prompt |
| PS-011 | [Anthropic: Harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | 一手工程文章展示初始化、进度文件、增量提交与可恢复任务分段 | `ADOPT_NOW`。与现有任务账本、Gate、精确写集和 G1 验证结合，不把 agent 自述当完成 |
| PS-012 | [OpenAI graders](https://platform.openai.com/docs/api-reference/graders) 与 [evals](https://platform.openai.com/docs/api-reference/evals/) | 官方 API 提供 grader 与 eval 运行的结构化接口 | `ADOPT_NOW` 为候选 eval seam。必须有人工金标、版本、作用域、回归门和失败样本；grader 不批准经营动作 |
| PS-013 | [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/) 与 [GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) | OTel 定义 GenAI system/model/token/agent/tool 等遥测属性，并提示 tool 参数/结果可能敏感 | `PILOT`。现有内部 span 可先保留，外部语义映射层需版本固定；默认不记录 prompt、PII、凭证和完整 tool result |

### 5.2 记忆、检索与数据底座

| ID | 一手来源 | `VERIFIED_PRIMARY_SOURCE` 摘要 | KJDS 采用边界 |
|---|---|---|---|
| PS-014 | [Agent Memory: Characterization and System Implications](https://arxiv.org/abs/2606.06448) | 原始研究讨论长生命周期 Agent 记忆的类型、访问模式与系统影响 | `RESEARCH`。不直接形成产品结论；先建立 KJDS memory workload 与遗忘/污染测试 |
| PS-015 | [MemGym](https://arxiv.org/abs/2605.20833) | 原始研究提出对长程记忆能力进行环境化评估 | `RESEARCH`。可借鉴测试维度，但必须使用 KJDS 自有任务和 Evidence 构建基准 |
| PS-016 | [AMA-Bench](https://arxiv.org/abs/2602.22769) | 原始研究评估高级记忆架构，并报告结构化/因果检索相对简单向量检索的优势 | `PILOT`。在 Product/Evidence/Decision 图上验证，不因论文结果直接采购图数据库 |
| PS-017 | [Microsoft GraphRAG publications](https://www.microsoft.com/en-us/research/project/graphrag/publications/)、[dynamic community selection](https://www.microsoft.com/en-us/research/blog/graphrag-improving-global-search-via-dynamic-community-selection/) 与 [LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/) | 一手项目与研究描述图索引、社区选择和成本/质量优化方法 | `PILOT`。优先复用 canonical graph + Evidence；只为跨文档全局问题建索引，禁止生成节点冒充 Fact |
| PS-018 | [pgvector](https://github.com/pgvector/pgvector) 与 [changelog](https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md) | 官方仓库提供 Postgres 向量检索、HNSW/IVF 与过滤相关能力 | `PILOT`。Postgres-first；向量只做候选召回，exact scope、时效、权限和事实判定仍由关系/图合同完成 |
| PS-019 | [PostgreSQL 18 release](https://www.postgresql.org/about/news/postgresql-18-released-3142/) 与 [release notes](https://www.postgresql.org/docs/18/release-18.html) | PostgreSQL 18 官方列出异步 I/O、skip scan、UUIDv7、OAuth 与 temporal constraints 等改进 | `BENCHMARK`。当前生产/验证基线不自动升级；先做迁移回放、扩展兼容、性能、备份恢复和回滚演练 |
| PS-020 | [Apache Iceberg specification](https://iceberg.apache.org/spec/) | Iceberg v3 规范包含 row lineage、deletion vectors、variant 与 geospatial 等表能力 | `NO-GO_NOW`。当前数据规模不足以证明 lakehouse 复杂度；达到留存/分析阈值后再评估 |
| PS-021 | [ClickHouse real-time analytics](https://clickhouse.com/use-cases/real-time-analytics) 与 [official product page](https://clickhouse.com/clickhouse) | 官方资料描述列式实时分析、物化视图和大规模查询能力 | `NO-GO_NOW`。经营真相继续由 PostgreSQL 持有；只有观测量和查询 SLA 超阈值才做只读分析副本 |

### 5.3 身份、安全、供应链与 AI 治理

| ID | 一手来源 | `VERIFIED_PRIMARY_SOURCE` 摘要 | KJDS 采用边界 |
|---|---|---|---|
| PS-022 | [SPIRE concepts](https://spiffe.io/docs/latest/spire-about/spire-concepts/) 与 [SPIFFE specifications](https://spiffe.io/docs/latest/spiffe-specs/) | SPIFFE/SPIRE 定义工作负载身份、attestation、SVID 与 federation | `WATCH/PILOT`。单机/小规模部署先保持简单；多环境服务身份与短期凭证需求成立后引入，不替代用户授权 |
| PS-023 | [OPA decision logs](https://www.openpolicyagent.org/docs/management-decision-logs) 与 [bundles](https://www.openpolicyagent.org/docs/management-bundles) | OPA 官方提供 policy bundle 分发与决策日志管理 | `PILOT`。适合外部化部分 Policy；业务状态机、Evidence 真相和 Permit 不迁入策略引擎；决策日志先脱敏 |
| PS-024 | [OWASP Agentic Top 10 announcement](https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-risks-and-mitigations-for-agentic-ai-security/) | OWASP GenAI 项目发布 Agentic 应用主要风险与缓解清单 | `ADOPT_NOW` 到威胁模型和验收清单。它是风险框架，不是合规认证或安全证明 |
| PS-025 | [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) 与 [Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) | NIST 提供 Govern、Map、Measure、Manage 风险管理框架及 GenAI 配套 Profile | `ADOPT_NOW` 到治理词汇与风险 register。不能替代俄罗斯法律、税务、制裁或产品合规意见 |
| PS-026 | [SLSA v1.2](https://slsa.dev/spec/v1.2/)、[build track](https://slsa.dev/spec/v1.2/build-track-basics) 与 [artifact verification](https://slsa.dev/spec/v1.2/verifying-artifacts) | SLSA 规范定义源码/构建成熟度、provenance 与产物验证 | `ADOPT_NOW` 分阶段接入 G1、镜像 digest、签名和发布清单；不得只生成文件而不验证 provenance |
| PS-027 | [CycloneDX AI/ML BOM guide](https://cyclonedx.org/guides/OWASP_CycloneDX-Authoritative-Guide-to-AI-ML-BOM-en.pdf) | 官方指南描述模型、数据、依赖和 AI/ML 组件的 BOM 表达 | `ADOPT_NOW` 到一个发布物的受限 BOM 合同。记录模型/提供商/adapter/eval 版本；不记录 secret、客户数据或私有 prompt 内容，生成 BOM 不等于通过发布 Gate |

### 5.4 浏览器、前端与推理效率

| ID | 一手来源 | `VERIFIED_PRIMARY_SOURCE` 摘要 | KJDS 采用边界 |
|---|---|---|---|
| PS-028 | [WebDriver BiDi Working Draft](https://www.w3.org/TR/webdriver-bidi/) | W3C Working Draft 定义双向浏览器自动化协议 | `WATCH/PILOT`。仍为 Working Draft；建立 provider interface，Seller API 优先，浏览器 fallback 隔离且只读起步 |
| PS-029 | [Playwright authentication](https://playwright.dev/docs/auth)、[BrowserContext](https://playwright.dev/docs/api/class-browsercontext) 与 [tracing](https://playwright.dev/docs/api/class-tracing) | 官方文档提供隔离上下文、认证状态和 trace 能力 | `ADOPT_NOW` 到测试/受控 fallback。认证状态视为 secret；禁止提交、跨租户复用或在 trace 中泄露 |
| PS-030 | [React 19.2](https://react.dev/blog/2025/10/01/react-19-2) | React 官方发布 Activity、useEffectEvent、cacheSignal 等能力 | `ADOPT_NOW_SELECTIVELY`。只批准进入一个有测量目标的实现切片；遵循现有 React Compiler/项目模式，不为追新重写稳定页面 |
| PS-031 | [Next.js 16](https://nextjs.org/blog/next-16) | Next.js 官方发布 Cache Components、Turbopack、React Compiler 支持和 DevTools MCP 等能力 | `ADOPT_NOW_SELECTIVELY`。项目已在当前主版本，只启用有验收收益且按 scope 分区的能力；缓存不能跨作用域泄漏数据 |
| PS-032 | [WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/) | W3C Candidate Recommendation 定义更强的公钥认证能力 | `PILOT`。适合管理员/审批者强认证；需恢复、设备丢失、浏览器兼容与 step-up 流程 |
| PS-033 | [torchao inference workflows](https://docs.pytorch.org/ao/stable/workflows/inference.html) 与 [torchao documentation](https://docs.pytorch.org/ao/stable/) | 官方文档描述 int4/fp8 等量化推理工作流，并区分稳定与实验能力 | `WATCH`。只有私有/本地模型经济性成立且 eval 不退化时采用；不以量化速度替代决策质量 |

### 5.5 2026-08-03 增量官方来源复核

以下结论是本日第二次增量复核产生的 `VERIFIED_PRIMARY_SOURCE` Observation。它们只更新
采用判断与验收条件，不证明依赖已经升级、运行环境已经修补或任何 Gate 已通过：

| ID | 一手来源 | 新 Observation | 候选与失效条件 |
|---|---|---|---|
| PS-034 | [MCP 2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28)、[authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) 与 [maintainer release explanation](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/) | 2026-07-28 已形成稳定、无会话握手的自包含请求协议，并强化 issuer、resource、audience、registration 与 step-up；它对 2025-era 实现存在 breaking change | OAuth 继续 `PILOT`。只有 Python SDK 明确支持该版本且 issuer/audience/resource/exact-scope 负向测试通过，才可迁移线协议；否则保持现有版本 |
| PS-035 | [MCP Tasks overview](https://modelcontextprotocol.io/extensions/tasks/overview) 与 [draft extension specification](https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks) | Tasks 已从 2025-11-25 实验性核心迁到 2026-07-28 可选扩展，但扩展规范仍为 draft、两端必须显式支持，旧新生命周期不兼容 | 保持 `WATCH`。若版本化扩展、Python SDK 与两个真实 Provider 未通过 lifecycle/cancel/replay/scope 测试，禁止替换 KJDS canonical task state |
| PS-036 | [OpenTelemetry semantic conventions 1.43](https://opentelemetry.io/docs/specs/semconv/)、[moved GenAI notice](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-exceptions/) 与 [deprecated attribute registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) | GenAI 语义已移出主 semantic-conventions 版本线，旧属性页被标记 moved/deprecated | 保持 `PILOT`。BAS-172 只冻结 provider-neutral、hash-only 运行真相；OTel 通过可替换翻译层映射，任一正文泄漏或字段漂移即回滚 |
| PS-037 | [PostgreSQL 18.4/17.10 security release](https://www.postgresql.org/about/news/postgresql-184-1710-1614-1518-and-1423-released-3297/) | 2026-05-14 官方安全版本同时覆盖 18.4 与 17.10；当前 Docker daemon 未运行，无法证明本机实际镜像 patch level | PostgreSQL 17 安全 patch 验证归入 `ADOPT_NOW` 的 BAS-175 provenance；18 仍是 BAS-176 `PILOT`。未证明 17.10+ 与镜像 digest 前，不得形成新的部署版本证明 |

本次还复核了 A2A 1.0、Temporal、GraphRAG、OPA、SPIFFE 与 torchao 的官方来源；未发现足以
改变既有 `WATCH/PILOT` 决策的 KJDS 新需求或本地量化收益。Ozon Seller 文档在本次访问中
超时，因此其变化状态保持 `UNKNOWN`，不能据此声明无变化。

## 6. KJDS 前沿技术采用决策

### 6.1 现在采用

以下是 `INFERENCE`，表示优先形成项目合同，不表示已经实现。机器注册表只为选中的
前沿依赖或有界实现候选建独立条目；上下文卫生、长任务 Harness、OWASP Agentic 与 NIST
AI RMF 属于 ADR 管理的工程/治理实践，现有 Playwright、Next.js/React 版本和 KJDS 内核属于
已存在基线，不能因为没有单独候选条目就被解释为遗漏或新生产依赖：

| 优先级 | 能力 | 最小落点 | 必须验收 |
|---|---|---|---|
| P0 | Agent Run/Trace/Eval contract | 在现有 Agent Harness 上记录 model/tool/prompt template/Evidence/authority/version、成本、延迟、结果与 grader | exact scope、脱敏、重放、失败样本、人工金标、模型切换回归 |
| P0 | 长任务上下文卫生 | 结构化 checkpoint、摘要、Evidence pointer、任务恢复和明确完成条件 | 中断恢复、上下文污染、旧 Evidence 失效、agent 自述不放行 |
| P0 | 供应链 provenance | G1 报告、commit、migration、镜像 digest、SBOM/AI-BOM、签名和验证 | 新 HEAD 精确证明、不可篡改关联、发布前验证、回滚产物存在 |
| P0 | Agentic 威胁模型 | OWASP Agentic + NIST AI RMF 映射现有 Authority/Approval/Permit | prompt/tool/identity/memory/supply-chain 攻击测试与 residual risk Owner |

### 6.2 受控试验

| 优先级 | 能力 | 试验范围 | 停止条件 |
|---|---|---|---|
| P1 | 因果/时序 GraphRAG memory | 仅在 canonical Product/Evidence/Decision 图上做只读问答与候选召回 | 任一跨租户泄漏、伪造 Fact、成本无优势或准确率不优于基线 |
| P1 | Durable workflow adapter | 选一个长周期市场侦察或 Listing 草稿流程，与现有 outbox/state machine 对照 | 产生双真相、不可回放、取消不可靠或运维成本超过收益 |
| P1 | MCP 最小权限 | 一个一方只读 server 的 OAuth audience/resource binding、增量 scope、token 不透传和高风险 step-up | 跨 audience、过期/撤销、scope 漂移或日志出现 token |
| P1 | OTel GenAI 映射 | 把现有内部 span 映射到固定版本最小语义字段与 KJDS trace/evidence ID | PII/prompt/tool body 泄露、租户串线、基数失控或成本/延迟不守恒 |
| P1 | Policy engine | 选无资金/无外写的只读授权策略验证 OPA bundle/decision log | Policy 与业务状态冲突、日志泄密或回滚不可用 |
| P1 | 浏览器自动化 provider | Seller API 不覆盖的只读页面；Playwright/BiDi 隔离上下文 | 需规避平台控制、Cookie 泄露、DOM 漂移不可控或出现外部写 |
| P1 | PostgreSQL 18 lane | disposable DB 迁移回放、扩展、查询、备份恢复、OAuth/temporal 评估 | downgrade/restore 不通过、扩展不兼容或收益无测量依据 |
| P1 | WebAuthn step-up | approver/管理员测试环境 | 恢复流程、兼容、审计或可用性不达标 |

### 6.3 观察或当前拒绝

| 技术 | 当前决策 | 原因 |
|---|---|---|
| MCP Tasks | `WATCH` | 规范仍标 experimental；现有 OperatingTask 不应被替换为不稳定外部核心 |
| A2A 跨组织 Agent 网络 | `WATCH` | 当前没有必须跨组织互操作的真实需求，攻击面和责任边界更大 |
| SPIFFE/SPIRE 全面落地 | `WATCH` | 单客户隔离阶段先避免平台复杂度；待多环境工作负载身份需求成立 |
| Iceberg/ClickHouse 数据平台 | `NO-GO_NOW` | 当前规模没有证明第二数据面收益；PostgreSQL 是经营真相源 |
| 本地量化模型主导经营决策 | `NO-GO_NOW` | 尚无 KJDS eval、校准、运维和单位经济证明 |
| 全自动浏览器经营 | `NO-GO` | 平台风险、脆弱性和外部写危害高；API 优先且动作必须受控 |
| 未经同意的跨租户模型学习 | `NO-GO` | 违反客户数据边界、商业信任和潜在法律要求 |

## 7. 业务与技术联合验收指标

`INFERENCE`：任何前沿技术只有改善下列真实指标且不削弱控制面，才可晋级：

| 维度 | 指标 | 证据要求 |
|---|---|---|
| 内容筛选 | 合格线索率、ICP 拒绝率、来源到发现会转化 | 同意、来源、分母、去重和时间窗 |
| 付费 MVP | 发现会到付费率、首次可信价值时间、验收率 | 合同、付款/退款、作用域、客户验收 |
| 案例模块化 | 案例到模块转化率、跨作用域复用次数、每次实施工时 | 版本、客户隔离、复验、人工工时 |
| 高客单交付 | 交付毛利、支持成本、变更请求、续费/增购 | 收入、成本、退款、工时、有效合同 |
| 俄罗斯经营 | 实际现金 CM3、退货率、履约时效、现金周期 | 订单、平台结算、银行到账、FX 与十五项成本 |
| Agent 质量 | 任务成功率、严重错误率、人工接管率、校准与回归 | 固定数据集、金标、trace、版本和失败样本 |
| Agent 成本 | 每个可信结果的 token/tool/compute/人工成本 | 供应商账单、trace 守恒、重试与缓存命中 |
| 安全治理 | 越权拒绝率、secret/PII 泄露、Permit 回读、恢复时间 | 负向测试、审计日志、事故演练和 Owner 签署 |

禁止使用粉丝数、浏览量、Agent 调用次数、模型自评分、GMV 或未绑定基线的百分比替代上述
结果。没有证据时必须返回 `UNKNOWN` 或 `no_data`。

## 8. 待验证假设与 UNKNOWN

| ID | 待验证项 | 最小验证方式 | 未验证前边界 |
|---|---|---|---|
| UNK-001 | 中国 Ozon 成长型卖家是否愿为“利润真相诊断”付费 | 20 次合格访谈、8 家只读数据意愿、5 家真实付费共创 | 不宣称 PMF，不扩大销售团队 |
| UNK-002 | 内容筛选是否优于外呼/伙伴渠道 | 同期、同 ICP、同报价的来源 cohort | 不把互动量当获客效果 |
| UNK-003 | 付费 MVP 能否稳定转设计伙伴/年付 | 记录分母、周期、退款、拒绝和续费 | 不根据截图价格定价 |
| UNK-004 | 单客户案例能否安全模块化 | 至少两个独立客户 exact-scope 复现 | 不进入共享默认能力 |
| UNK-005 | 高客单系统交付是否有正向交付毛利 | 全量人工、模型、工具、支持和退款成本 | 不只按收入判断成功 |
| UNK-006 | KJDS 自营店能否形成正向实际现金 CM3 | 完整订单、退货窗、结算、银行到账和 FX | 不扩大库存、广告或保证盈利 |
| UNK-007 | GraphRAG 是否改善 KJDS 复杂问答 | 与结构化 SQL/图查询/向量基线盲测 | 不采购第二真相数据库 |
| UNK-008 | Durable workflow 平台是否值得引入 | 单流程故障注入、恢复、成本和运维比较 | 不双写现有状态机/outbox |
| UNK-009 | 新模型/量化/路由是否改善单位结果成本 | 固定 eval + 真实 trace + 人工复核 | 不按厂商 benchmark 自动切换 |
| UNK-010 | PostgreSQL 18 是否可安全升级 | 全迁移、扩展、备份恢复、性能和回滚证据 | 当前版本继续作为运行基线 |

## 9. 采用边界总结

1. 学习的是“动态闭环、市场验证和能力产品化”的思维，不复制未经证明的人设、收入或案例。
2. KJDS 的前端以 Evidence 支撑的问题内容筛选需求，中端以 exact-scope 诊断和付费 MVP
   冻结责任，后端以受控交付和实际结果沉淀模块。
3. 俄罗斯经营是软件可信度的 Evidence 来源之一，不是营销表演；SaaS 是经营内核的可复制
   交付形态，不是第二套商品、利润、审批或授权真相。
4. 前沿技术采用服从深模块、最小复杂度、PostgreSQL-first、API-first、fail-closed 和
   Evidence-first。新名词不能自动成为新基础设施。
5. 任一新技术必须先进入独立试验，具有基线、威胁模型、成本、回滚、负向测试和 Owner；
   通过后才可申请写入架构合同与动态计划。
6. 本文不改变当前 `C0`、G0-G8、R0-R4、S0-S4 或外部写状态，也不构成任何 Gate 通过证据。
