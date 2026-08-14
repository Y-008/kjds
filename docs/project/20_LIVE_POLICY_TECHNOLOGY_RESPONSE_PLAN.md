# KJDS 实时政策、平台与技术响应活计划

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-PLAN-020 |
| owner | Strategy Intelligence + Product + Risk |
| approver | 经营负责人；高风险变化另需对应 Risk/Finance/Compliance |
| status | Active design / monitor adapter pending |
| version | 2026.08.10.1 |
| last_source_review | 2026-08-10 |
| next_scheduled_review | 2026-08-15 |
| authority | BR-147；复用 Strategic Intelligence、Evidence、OperatingTask、Eval 与 Release Gate |

## 1. 目标

把“最新政策和技术”变成可验证、可回滚的经营变化，而不是新闻摘要或模型记忆。系统发现 Ozon、
1688/货源、物流、税费/汇率、内容、广告、AI 模型、协议或安全标准变化后，必须在同一条链上完成：

`发现 → 原件/哈希 → 版本差异 → 影响图 → 应对候选 → 独立复核 → 测试/Shadow → 人工生效 → 运行回读 → 复盘`

本计划不建立第二套政策数据库、工作流或权限系统。来源原件进入现有 Evidence；变化与行动进入
现有 Strategic Intelligence 和 OperatingTask；模型/技术变化进入既有 Eval/Shadow/Release；
经营写动作继续走 Approval、一次性 Permit、Executor、Readback、Kill Switch 和 Compensation。

“实时”定义为：已准入来源一旦被采集到新版本，立即生成内部差异和影响任务。它不表示 KJDS
能够早于平台发布，也不表示未经复核自动修改生产。

系统不能因为禁止自动外写就删除动作。每个已识别影响都必须保留可处理提案，例如
`price_change_proposal`、`advertising_budget_bid_change_proposal`、
`listing_content_change_proposal`、`replenishment_proposal`、
`markdown_return_or_disposal_proposal`。人工可选择：批准进入既有 Gate、写理由拒绝、延期到
指定时间或要求补证。正式建议售价/区间、预算、出价、数量和最大损失只有在权威输入与确定性
公式完整时才显示；否则提案保持 `awaiting_evidence` 并列出缺口，而不是给零值或模型估值。

## 2. 来源阶梯与刷新目标

| 等级 | 来源 | 目标频率 | 可推动的结果 |
|---|---|---|---|
| A0 | 已签合同、账号内规则/费率、官方 API 返回与官方导出 | webhook/运行时变化优先；否则每日 | 可进入独立复核与生产应对候选 |
| A1 | 官方政策、帮助、API 文档、Seller 公告、版本日志 | 每日；关键执行前再次预检 | 可进入独立复核与测试 |
| A2 | 法规/税务/海关/标准制定机构原文 | 每日或发布订阅 | 必须由 Compliance/Finance 复核 |
| B | 官方技术标准、官方模型/Provider 文档、官方代码仓库 Release | 每周；升级前强制复查 | 可进入 PoC、Eval、Shadow |
| C | 第三方 SaaS、专家、社区、竞品公开信息 | 每月或按需 | 只产生研究假设，不直接改生产 |

当前策略注册表规定：易变平台来源 30 天未复核、策略来源 90 天未复核即进入
`awaiting_source_review`。这是最长复核兜底，不替代上表的日常采集目标。任何文章示例中的金额、
比例、天数或阈值都不能直接写入成本/广告/库存政策。

## 3. Change Artifact（复用既有 Evidence/Intelligence）

每次变化至少保存：

- `source_id/source_tier/source_url/document_sha256`；
- `published_at/effective_at/observed_at/verified_at`，未知时间显式为 `unknown`；
- `market/account/store/fulfillment/category/api_version` 适用范围；
- 上一版本、新版本、结构化 diff、原文定位和抓取覆盖；
- 变化类别：`fee|tax|fx|api|auth|listing|content|ads|promotion|inventory|logistics|return|policy|ai_model|protocol|security`；
- 影响对象：成本项、Adapter、Schema、Gate、模板、评测、SKU、店铺、Campaign 或运行手册；
- 风险、截止时间、回滚/补偿、Owner、独立 Reviewer；
- 处理状态：`observed|needs_review|validated|scheduled|active|rejected|superseded`。

这些状态描述同一 Evidence-backed Change Artifact 的处理结果，不成为新的任务/审批状态机。

## 4. 影响与应对矩阵

| 变化 | 自动允许 | 必须复核/验证 | 禁止直接发生 |
|---|---|---|---|
| 费率、佣金、仓储、物流价 | 标记受影响成本项和场景为待复核；重算 shadow 场景 | Finance 核对账号/期间/币种/税口径；历史样本对账 | 自动改正式成本、利润、售价 |
| 税务、海关、禁限售、认证 | 隔离受影响 SKU；建立 Compliance 任务 | 法务/合规原文与生效范围双签 | 模型给出合规结论或放行 |
| Seller/Performance API | 生成 schema/endpoint diff，运行录制样本和合同测试 | 最小权限、分页、幂等、限流、回读、旧版退场 | 在生产直接切新版本或绕过授权 |
| Listing/属性/图片视频规则 | 标记模板和草稿重新 QA | 真实类目 schema、俄语审核、媒体审核样本 | 自动改已批准快照或复制受保护内容 |
| 广告/促销机制 | 暂停不兼容提案；更新分析字段和 shadow 策略 | 预算/出价/折扣/归因/读回测试 | 自动开广告、加预算、改活动 |
| 仓库/配送/退货规则 | 标记路线、包装、时间窗和成本受影响 | 真实线路/仓/重量尺寸/状态样本 | 自动发货、补货、处置或确认退货 |
| AI 模型、工具、Prompt、Agent | 离线重跑 golden set，比较质量/成本/时延/工具轨迹 | 安全红队、确定性校验、Shadow、回滚 | 模型自升级、自改权限或事实公式 |
| MCP/Agentic commerce/认证协议 | 创建隔离 Adapter/Tool 合同和权限矩阵 | OAuth/身份、最小数据、幂等、用户确认、审计 | 浏览器持有服务端密钥或无确认付款 |
| 市场趋势、搜索词、竞品店铺 | 生成 Observation 和研究候选 | 来源/窗口/样本、精确 SKU、RFQ、利润 Gate | 冒充销量、28 天趋势、报价或采购依据 |

“禁止直接发生”只限制资讯/模型绕过人工与 Gate 执行，不限制系统生成、排序和保留待处理动作。
所有提案统一使用 `awaiting_evidence → pending_human_decision →
approved_for_existing_gate_flow|rejected_with_reason|deferred_until` 语义；店铺/类目明确排除才是
`blocked_by_route`。批准后仍需对应 Evidence、Approval/Permit/Executor/Readback，不因人工点击
而跳过事实或安全门。

每张动作卡还必须提供默认未勾选的“自动执行此类动作”复选项。选中后保存
`supervised_batch` 或 `policy_bound_autonomous` 偏好并引导配置 exact-scope Automation Grant；
只有 Grant 的动作范围、SKU/类目、价格/预算/数量/损失上限、有效期、Evidence/策略版本、独立
批准、执行时复验和回读全部有效时才可自动执行。越界、过期、策略漂移或回读缺失自动暂停并转
人工待办。全面自动化按 Shadow→监督批次→单打法自治→跨打法闭环分级发布，不用一个全局开关
无限放权。

## 5. 自适应经营计划同步

一个变化只有在 `validated` 且对应测试/复核通过后，才允许同步以下资产：

1. `MASTER_SPEC.md`：业务边界或真相权威变化；
2. `store_category_strategy_registry.json`：打法、来源、适用阶段、门和停止条件；
3. `03_REMAINING_WORK_AND_PARALLEL_PLAN.md`：P0 优先级、依赖、Owner、状态和下一复核；
4. Adapter/Schema/测试：平台或协议接口变化；
5. Eval/Golden cases：模型、Prompt、视觉、工具或推荐变化；
6. 运行手册与 UI：只显示后端已生效版本、来源日期和阻断，不让前端复制规则。

所有同步写入同一个 `change_basis_sha256`。来源、适用范围、成本模型、策略、测试或审批任一变化，
旧 continuation/推荐必须失效并重算。

## 6. 最新经营与技术基线（2026-08-08）

已核验并进入研究注册表的一手基线：

- Ozon 2026 新品首批规划：市场/搜索/评论/交期/最小批量与小批验证；
- Ozon 搜索查询分析：查询曝光、浏览、订单、位置和收入；
- Ozon 视频封面：最多 5 个视频、平台审核和错误状态；
- Ozon PPC：预算、自动加预算、出价、商品范围、暂停和变更历史；
- Ozon 促销码分析：使用、订单、转化、销售和折扣成本；
- Ozon FBO：SKU×仓的 IDC 和周转；
- Ozon 2026 跨境物流合同：API/账号请求、条码、包装、重量尺寸、禁运、退件状态；
- OpenAI 2026 Product Discovery/Agentic Commerce：新鲜结构化商品、比较、用户显式确认、商户仍掌握订单履约与客户关系；
- OpenAI Graders 与 MCP Authorization：Agent 评测、trace 和按工具/身份最小权限。

该段来源母稿仍只存在于隔离分支的
`docs/project/evidence/20260808_RESEARCH_BACKED_OPERATING_PLAYBOOKS.md`，BAS-219A 不把它
冒充主线 Evidence。任何对应打法进入实现前，必须重新读取官方一手资料并在主线 Evidence
保存 freshness 结果；未复核项保持 `UNKNOWN`。

## 7. 当前实施状态与下一批

| ID | 交付 | 状态 | 验收 |
|---|---|---|---|
| PLR-001 | 开放式研究打法注册表、来源绑定和版本哈希 | IN_PROGRESS | 注册表可加载；来源 ID 守恒；策略数量不硬编码 |
| PLR-002 | SKU 阶段打法投影 | IN_PROGRESS | 返回 proposal/awaiting/blocked、Evidence Gate 状态、外写关闭和阶段主推荐 |
| PLR-003 | 非线性经营反馈图与 AI-native 技术合同 | IN_PROGRESS | 复用 Commerce OS 状态；无第二状态机；文档与 API registry 同源 |
| PLR-004 | 官方来源采集与 Change Artifact Adapter | PENDING | 增量、哈希、双时间、diff、覆盖/失败页、幂等、无外写 |
| PLR-005 | 影响图与现有 OperatingTask 自动建单 | PENDING | 只建内部任务；稳定指纹去重；Owner/SLA/回滚完整 |
| PLR-006 | 策略/Adapter/Eval Shadow 与生效门 | PENDING | 样本对账、回归、独立复核、回滚演练全部通过才 active |
| PLR-007 | Web“政策与技术变化”工作台 | PENDING | 非技术界面显示来源、差异、影响、Owner、状态、下一动作；前端不判定规则 |

当前没有声称已经运行 24×7 政策监控；本切片先固化注册表、投影、活计划和测试。上线 PLR-004
以后，才能把“实时更新”提升为生产运行事实。

## 8. 计划更新记录

| 日期 | 版本 | 变化 | 依据 |
|---|---|---|---|
| 2026-08-08 | 2026.08.08.1 | 从固定三段/固定数量打法升级为来源驱动的自适应经营图；增加政策/技术 Change Artifact 和响应矩阵 | 隔离设计基线、Ozon/OpenAI/MCP 一手资料 |
| 2026-08-10 | 2026.08.10.1 | BAS-219A 复核 OPA policy evaluator 与 Temporal durable workflow 官方状态，采用决定保持 shadow/pilot_later；主线不安装依赖、不新建控制面 | BR-147、OPA/Temporal 官方发布与管理文档 |
