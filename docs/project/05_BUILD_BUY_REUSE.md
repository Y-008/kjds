# Build / Buy / Reuse 决策

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-ARCH-REUSE-001 |
| owner | 工程负责人（待确认） |
| approver | 项目负责人 |
| status | Active |
| version | 1.9 |
| last_reviewed | 2026-07-20 |
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
| Durable Workflow | 当前服务+状态机 | Build/Defer | Temporal 仅在长事务、补偿、重放压力实证后 ADR |
| 商品图片执行器 | 官方 `Comfy-Org/ComfyUI` 本地 API | Reuse/Wrap | 已验证本机 `0.27.0`、RTX 4060 和 `/system_stats`；loopback 监听且默认禁用第三方 custom nodes。KJDS 持有事实、证据、Brief、QA 和审批 |
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

`artokun/comfyui-mcp` 和其他 MCP/自定义节点保持研究候选，不进入当前生产依赖。只有跨 SKU 稳定工作流已复现、原生 `/prompt` 与状态/历史接口成为实际编排瓶颈，且隔离 PoC 通过许可证、安全、升级和回滚评估后，才重新决策。任何执行器都不得绕过七类素材 readiness、ContentAsset 状态机和 G2 审核。

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
