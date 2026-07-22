# Build / Buy / Reuse 决策

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-ARCH-REUSE-001 |
| owner | 工程负责人（待确认） |
| approver | 项目负责人 |
| status | Active |
| version | 2.0 |
| last_reviewed | 2026-07-22 |
| next_review | 2026-08-16 |
| gate | G-1–G8 |

## 当前组合

| 层 | 当前 Owner | 决策 | 边界 |
|---|---|---|---|
| 业务控制平面 | KJDS 模块化单体 | Build | 事实、Passport、账本、审批、证据、业务状态由 KJDS 持有 |
| API/Schema | FastAPI + Pydantic | Reuse | 服务层执行业务规则，Agent/连接器不得直连 Repository |
| 事实库 | PostgreSQL/Supabase | Reuse | Decimal、币种、双时间、迁移和审计事件 |
| Web 身份会话 | Supabase Auth + `@supabase/ssr` | Reuse/Wrap | Cookie 会话由 Supabase 维护；KJDS 服务端将真实 user ID 映射到既有独立 actor；浏览器不接触 API key |
| 浏览器探索 | Playwright | Reuse | 探索/采集可用；生产写动作仍需确定性代码与审批 |
| Agent 操作工具 | OpenClaw + Hermes | Reuse | 仅操作员与研究调度，不成为业务唯一真源 |
| 开发 Agent Harness | Codex 主执行；Grok Build 隔离试点 | Reuse/Pilot | 只比较安全有效交付率；不得接入生产凭证或成为业务控制平面 |
| Agent 运行时 | 现有壳层；后续评估官方 Agents SDK/PydanticAI | Defer | 先完成真实闭环和 Agent 需求合同 |
| Durable Workflow / 任务队列 | 当前服务+状态机；Postgres 原生库为后备 | Build/Defer | 先比较 PgQueuer/Procrastinate；只有长事务、补偿、重放压力实证后才评估 DBOS/Temporal 并走 ADR |
| 商品图片执行器 | 官方 `Comfy-Org/ComfyUI` 本地 API | Reuse/Wrap | 生产继续只开放 core `ozon-retouch-v1`；第三方白名单仅为本机隔离实验。KJDS 持有事实、证据、Brief、QA 和审批 |
| 可观测/评测 | 业务审计账本优先；Langfuse/Promptfoo 候选 | Defer | 不能替代业务证据和黄金 Oracle |
| AI 网关 | 官方 API/现有本地 Provider | Reuse | 不采用共享订阅池 |
| 标准 ERP 交易内核 | ERPNext 隔离 PoC 候选 | Reuse/Defer | 当前不安装生产实例；只在真实 Ozon 竖切后验证采购、库存、供应商、多币种与会计单据，避免 KJDS 重造 ERP |

## 开源 ERP / Commerce 结论

标准采购、库存、供应商和会计能力不应长期全部自研。当前首选 ERPNext 作为隔离侧车 PoC；Odoo Community 为第二候选，Dolibarr 为轻量备用。Medusa、Saleor、Vendure属于自有商城 Commerce Kernel，不是当前 Ozon 优先阶段的会计 ERP，因此延期。

任何 ERP 晋升前必须证明单一可写 Owner、外部 ID、幂等同步、Evidence 血缘、双向对账、最小权限、备份恢复与完整卸载。详细比较和 PoC 门见 [12_OPEN_SOURCE_ERP_AND_COMMERCE_KERNEL_DECISION.md](12_OPEN_SOURCE_ERP_AND_COMMERCE_KERNEL_DECISION.md)；机器可读快照见 [`registries/open_source_commerce_kernels.json`](registries/open_source_commerce_kernels.json)。

## sub2api 结论

当前不引入、不部署、不占用 G-1–G4 开发窗口。它提供多账号池、Key 分发、计费、调度和后台，但不是项目监控、Codex 多窗口调度或跨境电商工作流。它还会引入第二套用户/权限/计费、PostgreSQL 和 Redis 运维面，并存在许可证声明与上游服务条款张力。

保留研究项：`R&D-AI-GW-001`，优先级 P3。只有在至少一个 SKU 完成订单—结算—人民币 CM3 闭环，且官方云模型成本、并发或故障切换成为实际瓶颈后，才做隔离 PoC。PoC 只能使用官方 API Key，不得导入订阅 Cookie/OAuth Token 或生产业务数据。

## Grok Build 结论

已在开发工作站安装 Grok Build `0.2.102`，定位为外部开发 Harness 的隔离候选，不是 KJDS 运行时、业务 Agent 或生产依赖。当前只采用它的 `inspect` 预检、工作树隔离、受限权限、结构化输出和 ACP 接口作为对照样本；不复制整套运行时，不添加第二套业务状态，也不允许直接接触 Ozon、数据库、结算或客户凭证。

试点、命令、安全边界和“超越”验收见 [08_GROK_BUILD_PILOT.md](08_GROK_BUILD_PILOT.md)。只有真实任务基准证明其提高安全有效交付率，且额外成本、人工审核和返工可接受，才允许进入下一阶段 ADR。

## 商品图片结论

不自研图片生成引擎，也不让 ComfyUI/MCP 持有商品事实。生产基线直接复用官方 `Comfy-Org/ComfyUI` 的本地 HTTP/队列能力；KJDS 只向它提交已冻结、版本化、受控模板产生的 workflow，不开放任意 workflow 输入。当前唯一自动模板是 `ozon-retouch-v1`，只使用官方核心节点对已批准真实原图做 4MP 等比保真处理并回收 Evidence，不加载生成模型、不改变商品结构、颜色、配件或文字。背景合成与信息图待真实 SKU 模板复验后再开放；所有输出仍须人工 QA 后才能用于 Listing。

`artokun/comfyui-mcp` 仍保持研究候选，因为原生 `/prompt` 与历史接口尚未形成实际编排瓶颈。生产默认继续使用只含官方节点的 `core` 模式和唯一 `ozon-retouch-v1`；本机 `trusted` 白名单只用于隔离效果实验，未提交逐节点 commit、许可证、hash、SBOM 和共享启动配置前不得晋升默认路径。Manager 禁止任意 Git URL 与 pip 安装。

`triton-windows 3.7.1.post27` 已按同一 Flux2 潜变量、同一 VAE、`cache-none` 做 30 对 A/B。重启后两组均为 30/30 成功，但补丁中位耗时 `476.5 ms`，对照为 `381 ms`，慢 `25.07%`；输出差异极小（PSNR `61.16 dB`），却没有质量收益。因此保留为显式实验能力，不进入默认 workflow，也不削弱 Windows Application Control。该结果只是合成技术夹具的性能证据，不是 RU-001 商品图、Listing 资产或业务验收。任何执行器仍不得绕过七类素材 readiness、ContentAsset 状态机和 G2 审核。

## Web 身份结论

不自研用户名密码、Token 刷新和第二套用户库。Next.js Web 复用 Supabase Auth 的服务端 Cookie 会话，并由 BFF 在每次请求重新确认用户，再映射到 `KJDS_API_KEYS_JSON` 中唯一的控制面 actor。用户—actor 映射不重复保存密钥；前端角色显示不参与授权；非管理员 actor 禁止同时拥有 `operator` 与 `approver`。本地 legacy 只保留为单一 `operator` 开发入口，生产必须启用 Supabase 模式。详见 [ADR-0012](../adr/ADR-0012-web-authentication-and-independent-approval.md)。

## 跨境 SaaS 竞品借鉴结论

萌啦、Seerfar、妙手 ERP 和 51Selling 作为产品模式样本，不作为 KJDS 的事实所有者或默认运行依赖。KJDS 借鉴其低门槛字段录入、趋势/竞品视图、采集箱、批量编辑、订单异常队列、库存/物流协同和模板复用；不复制“一键采集即刊登”、未知公式利润、自动跟价、共享店铺凭证或未经审批的批量写入。

具体映射、来源状态和 KJDS 超越标准见 [11_COMPETITOR_CAPABILITY_BENCHMARK.md](11_COMPETITOR_CAPABILITY_BENCHMARK.md) 与机器可读注册表 [`registries/competitive_capability_patterns.json`](registries/competitive_capability_patterns.json)。任何 Open API 接入先完成协议、数据血缘、字段合同、速率限制、权限、撤销、审计和真实样本对账；未完成前只允许手工导出进入 C/D 级研究收集箱。

萌啦式“集中填写成本”的低摩擦模式已经通过 `ozon-ru-full-cost-v1` 复用落地，但公式、Evidence、状态和放行规则完全由 KJDS 持有。实现只扩展现有场景 JSONB，不新增模板表、依赖或自动定价器；第三方结果只能作为 C/D 级交叉检查。下一阶段只有在真实运营证明批量差异预览是当前瓶颈时，才进入 P2 受控批量工作台。

51Selling 式字段来源提示也已用现有 `cost_states + cost_evidence` 落地：报价/CM3 卡片逐项展示“预估、实际、未知”和 KJDS Evidence，不复制第三方标志或算法。未归类 Ozon 费用继续进入显式待批准队列；应计报告即使来源复核通过，也因混合收入与费用而保持入账阻断。该增量没有新增数据表、依赖或第二套利润引擎。

研究收集箱已按最小实现落地：复用现有 Evidence/Blob/Lineage 和独立权威复核，只增加专用服务与 API，不增加数据表、迁移、队列、浏览器插件或供应商 SDK。它解决“第三方资料如何安全进入系统”，不解决“第三方数字是否为真”；任何连接器只有在手工流程出现可测瓶颈后才重新评估。

## 新技术准入问题

1. 它解决哪个当前 Gate 的实证瓶颈？
2. 现有模块为何不能用更小修改解决？
3. 谁拥有该层，是否形成双 Owner？
4. 数据、密钥、许可、上游条款和退出成本是什么？
5. 最小隔离 PoC 的成功/失败标准是什么？
6. 如何回滚和完全移除？

## 跨境电商 CLI / App / Agent / Skill / MCP / Harness 雷达

2026-07-22 已按 GitHub 仓库与 Topics、官方平台文档、npm、PyPI、MCP 目录、OpenClaw/ClawHub 和 Hermes Skill 生态做横向检索，并把可复核结果固化到 [`registries/cross_border_automation_ecosystem.json`](registries/cross_border_automation_ecosystem.json)。注册表区分 `active_now`、`official_api_targets`、`deferred_until_channel_exists` 与 `not_adopted`，且固定 `automatic_install=false`、`automatic_write_enablement=false`。

新增动作仍不安装后台。`1688-cli@0.1.47` 已在 Git 忽略目录固定版本安装并完成真实消息回读，承担持久会话、商品原页、旺旺消息号去重和只读结算预览。另将当前官方仓库 `jackwener/OpenCLI` 的 `@jackwener/opencli@1.8.6` 以 `--ignore-scripts` 隔离安装并完成 0 漏洞依赖审计；其 1688 商品代表性读取真实返回 `BROWSER_CONNECT`/exit 69，原因是 Browser Bridge 未连接，所以只登记为 `installed_isolated_not_promoted`，没有猜测修补适配器，也没有生成业务事实。官方扩展 `1.0.22` 已核对 SHA-256 和高权限清单，后续只可加载到专用 KJDS Profile，用于只读适配器、站点记忆、任务 sitemap、素材下载与回放资产复利，严禁进入包含个人 CPA/2FA/金融会话的主 Edge Profile。

Playwright 继续作为确定性底座复用；Stagehand `3.7.0`/server `v3.7.4`、browser-use `0.13.6` 和 Skyvern `v1.0.47` 只作为同一浏览器 lane 的候选实现，出现确定性适配器无法覆盖的可测缺口后再逐一隔离对比，不同时建设三个浏览器控制面。Playwright MCP、OpenChrome、社区 Shopify MCP、PriceBuddy、PIM 和 Commerce Kernel 当前仍因重复能力、渠道未立项、包身份异常或会形成第二 Owner 而不采用。

官方长期路径保持不变：1688 写操作优先等待开放平台企业应用和最小权限授权；Ozon 继续使用版本化的直接 HTTP 合同；FX 优先直接取得央行原始响应。Amazon、Shopify、Wildberries、物流聚合器和 UN Comtrade 只在对应渠道、账户、预算或真实决策问题出现后重新评估，不能因为已有开源包就提前进入生产依赖。

工作流补充检索覆盖可视化编排、持久执行、Postgres 任务队列、数据管道和 Agent 工作流。结论不是再装一个后台：现有 n8n 只保留计时与通知，业务状态仍由 KJDS 的 Evidence → Approval → DecisionPacket → ExecutionPermit → Readback 链路拥有。若以后出现可量化的后台任务缺口，先在隔离 PoC 中二选一比较 PgQueuer/Procrastinate；只有现有状态机加单一队列仍无法满足崩溃恢复时才评估 DBOS。Temporal、Restate、Hatchet、Kestra、Activepieces、Windmill、Node-RED、Dagster、Prefect、Airflow 当前全部延后，避免第二控制面。

Agent 工作流同样按缺口复用：若现有 Agent 壳层确实缺少 handoff、guardrail、session 或 tracing，优先评估官方 OpenAI Agents SDK；LangGraph/PydanticAI 不并行引入，已进入维护模式的 AutoGen 不用于新开发。多源数据达到真实的增量加载与 schema evolution 瓶颈后才引入轻量 `dlt`，其输出仍是 research evidence，不能自动晋升为 formal fact 或 actual。

### 采集合同蓝图与复利指标

注册表先冻结 22 个连续环节的验收合同：来源权威与许可、账户/会话范围、官方 API/导出、确定性登录浏览器、AI 浏览器后备、原始响应留存、文件安全与隐私、解析与 schema 版本、SKU/供应商身份、时间窗/分页/控制总数、哈希去重与历史、字段级来源与置信度、独立复核、Evidence 血缘、research→formal→actual 晋升、漂移隔离与回放、限流/重试/熔断/人工接管、服务端回读与对账、保留与撤销、监控/SLO/事件、人工分钟与成本、复用资产登记。每一环都在 [`registries/cross_border_automation_ecosystem.json`](registries/cross_border_automation_ecosystem.json) 固定 `primary`、`fallback`、`owner`、`boundary`、`status`、`verification` 和 `provenance`；当前只是机器可读合同，不是统一运行时实现，任一关键环节缺失即保持 blocked 或 requires_review。

浏览器路径固定为“官方 API/导出优先 → 专用 KJDS 浏览器 Profile 的确定性适配器 → Stagehand/browser-use/Skyvern 等 AI 浏览器隔离试验 → 登录、MFA、CAPTCHA 或账户歧义时可见人工接管”。不得导出 Edge 主 Profile 的 Cookie、密码或 2FA，不得混用个人 CPA/金融会话；AI 浏览器没有反爬绕过权限，也没有独立写权限。当前 1688 RU-001 是用户人工发送后的带外只读回读，虽取得服务端消息 ID、目标供应商与回复“您好，稍等”，但没有 KJDS ExecutionPermit/`authorize_action()` 记录，不能算受控写链验收；正式书面报价仍为 0，不能晋升 actual。Ozon 连续至少 28 天官方数据仍缺获批身份或原始导出。

“复利”是验收指标：每次运行必须留下适配器或明确缺口、字段映射、原始/标准化金样、失败签名与接管规则、回放测试、Evidence/Readback 模板以及人工分钟/机器成本。第二个同类 SKU 的流程与适配器复用率不得低于 70%，第三个不得低于 85%；第三个 SKU 人工分钟不得高于第一个的 50%；已知失败复发率低于 5%，重复外部动作与未经复核事实晋升均为 0，回滚成功率为 100%。工具只有在代表性结果测试同时通过稳定性、质量、权限、来源、回滚和总成本后，才从实验能力晋升默认路径。

### 2026-07-22 前沿协议与实现快照

本快照不使用搜索结果页的“最近更新”猜测版本，而是读取官方仓库默认分支 HEAD、最新 GitHub Release、规范稳定版和官方成熟度声明；晚于 2026-07-22 的草稿不进入结论。当前分层是：UCP/ACP 负责 commerce exchange，AP2 负责 delegated-payment mandate，A2A 负责独立 Agent 互操作，MCP/MCP Apps 负责工具、资源与沙箱 UI，AG-UI/A2UI 负责 Agent 到前端的事件或界面表达，Agent Framework/Agents SDK/DBOS 等才是底层实现。它们互补，不能拿一个“全能工作流平台”同时替代这些边界。

截至本日，UCP 已有 `v2026-04-08` 开放规范且仓库仍在 7 月 22 日活跃；A2A 已到 `v1.0.1`；MCP Apps 的 `2026-01-26` 扩展规范为 stable，SDK 最新 `v1.7.4`；AG-UI 最新发布为 `release/2026-07-15`。但 ACP 官方仍标注 beta（最新稳定规范快照 `2026-04-17`），AP2 只是 `v0.2.0` 的 SDK/样例且尚未发布 PyPI 类型包，A2UI 虽持续开发但没有 GitHub Release。不能把这些项目统一写成“生产成熟”。

实现层的当前版本更快：OpenAI Agents SDK `v0.18.3`（2026-07-17）强化 sandbox、并发 computer provider、session retry 和 trace redaction；Microsoft Agent Framework `python-1.12.0`（2026-07-21）把 harness agent 升为 stable，并加入 app-owned MCP/A2A hosting 与 workflow HITL response URL，但仍有显式 experimental 子系统；GitHub Agentic Workflows `v0.82.14`（2026-07-20）适合受沙箱和 safe-output 约束的仓库维护；DBOS Python `2.28.0`（2026-07-21）是当前最贴近 KJDS Python/Postgres 的 durable execution 候选；Trigger.dev `v4.5.6` 同样活跃，但会增加独立 TypeScript 控制平面。

对 KJDS 的实际采用顺序因此是：先把 UCP/AP2 的 capability/mandate 思路映射到现有合同与 ExecutionPermit 评审，不启用支付；若需要非技术界面，优先评估 MCP Apps 作为现有 API 的显示适配器，不新建审批 Owner；若出现可量化崩溃恢复缺口，再对 DBOS 做 ADR/隔离 PoC；只有出现真正独立、跨组织 Agent 才接 A2A。ACP、UCP checkout、AP2 payment、AG-UI/A2UI、Trigger.dev、Microsoft Agent Framework 当前均不能解决 Ozon 28 天凭据或 1688 供应商回复这两个真实外部阻断，故不以“前沿”为由直接启用。
