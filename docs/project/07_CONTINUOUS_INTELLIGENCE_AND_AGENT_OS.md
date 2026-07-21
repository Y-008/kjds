# KJDS 24×7 持续情报与 Agent Operating System

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-OPS-AI-002 |
| owner | 本机操作员 |
| approver | 项目负责人 |
| status | Active |
| version | 1.0 |
| last_reviewed | 2026-07-16 |
| next_review | 2026-07-23 |
| gate | G-1 支撑能力；不得替代 G0–G7 经营证据 |

## 当前结论

本机已经从“定时唤醒一个 Agent 上网搜索”升级为三层系统：

1. 确定性采集层每 30 分钟运行，不依赖任何模型或云余额。
2. 报告层从 SQLite 生成可复核晨报，不允许模型伪造“成功”。
3. 推理层只产生候选洞察；缺标题、缺 event_id、出现证据外年份/版本时自动拒绝，不进入长期记忆。

```text
官方 / 平台 / 官方仓库
        ↓
Authority Radar（30 分钟；去重、来源层级、置信度、影响、复核标记）
        ↓
SQLite 事件库 + 健康状态 + 事件收件箱
        ├─ 08:00 确定性晨报
        ├─ 09:10 本地 Gemma 候选分析 ── Evidence Gate ──→ Chief 记忆
        └─ 智谱 Auditor（有余额时并行第二意见）── Evidence Gate ──→ 合并候选
```

“持续进化”不是允许 Agent 自行修改生产配置，而是：发现新信息 → 保留证据 → 形成假设 → 离线评估 → 影子运行 → 人工晋级。未经晋级的模型输出不能改变来源注册表、核心 Prompt、Skill allowlist、平台参数或经营决策。

控制平面现在把两项边界固化为可验证接口：只读 worker 使用独立 `pilot_reader` 身份，试运行带 15 分钟默认租约；租约过期后由管理员回收为 `expired` 并生成 B 级审计证据，迟到结果不能再完成。G0/G1 的 Gate Review 也已结构化，必须明确 owner、独立 approver、参与人、退出条件、风险预算、最大损失、回滚方案和有效证据，不能再用单个 GOV-001 文件替代完整治理合同。

业务写接口还必须通过 endpoint 级最小角色校验；全局 middleware 只负责身份、Kill Switch 与“有某种写角色”的粗门禁，不能替代具体角色授权。`pilot_reader`、`executor`、`monitor` 等专用身份不会因此获得商品、订单、内容或市场写权限。

Ozon 只读 worker 还支持最多 50 个目标的确定性分页：每个目标使用批次键加目标哈希生成幂等键，输出不泄露 offer id，只返回哈希、run/evidence 引用和下一页游标。批次不是新的权限边界，最终事实仍以控制平面的逐 run 记录和证据为准。

成功的只读 run 可以提出受限的候选事实声明（商品身份、属性、库存或价格观察），声明必须匹配 `state_sha256` 并引用 run 证据；独立 reviewer 只能接受或拒绝，接受后仍标记为 `formal_fact_promoted: false`，直到后续正式事实映射和业务批准完成。

## 运行态

| 能力 | 频率 | 执行者 | 输出 | 2026-07-16 验收 |
|---|---:|---|---|---|
| 权威来源采集 | 每 30 分钟 | Windows Task `KJDS-Authority-Radar` | SQLite、事件收件箱、健康 JSON | PASS；最近任务结果 0 |
| 本机健康检查 | 每 2 小时 | OpenClaw command job | Gateway/n8n/Ollama/KJDS 控制平面/采集器状态 | PASS；连续错误 0；KJDS readiness 在配置 API Key 时纳入检查 |
| 晨间就绪战报 | 每日 08:00 | OpenClaw command job | `morning-readiness.md` 与 Chief 镜像 | PASS；真实内容验收通过 |
| 权威 AI 决策雷达 | 每日 09:10 | 本地 Gemma，无工具调用 | 候选分析或拒绝报告 | PASS；幻觉候选被 Gate 拒绝 |
| 本地金标回归 | 每周日 03:30 | OpenClaw command job | 20 条引用、安全、审批与治理回归；低于 90% 自动失败 | PASS；19/20，95.0% |
| 智谱第二意见 | 按高价值事件 | Auditor Agent | 独立候选 | BLOCKED；HTTP 402 余额不足 |

当前事件库建立 24 个来源状态、98 个去重事件。Amazon 已切换到官方 changelog RSS，EU TAXUD 已切换到可访问的官方新闻入口；Wildberries 因公开站返回 498，被明确降级为等待官方 News API Token。最近强制验收为 `24/24 healthy、0 failing`，历史故障仍保留在运行记录中。

## 权威来源域

来源的机器可读唯一真源为 [authority_sources.json](registries/authority_sources.json)。来源状态与内容结论分开：页面 Hash 改变只代表“需要核验”，不代表政策或平台规则已经改变。

| Domain Cell | 优先对象 | 自动化边界 | 下一里程碑 |
|---|---|---|---|
| AI 前沿 | OpenAI、Google DeepMind、Gemini changelog、官方 SDK release | RSS、官方 changelog、官方仓库 | 加入模型废弃日期与迁移提醒 |
| 资本与监管 | SEC EDGAR、HKEX、上交所、深交所、公司 IR | 当前只登记官方入口 | 批准 CIK/公司 watchlist 与合规 User-Agent |
| 企业端 AI | AWS ML、NVIDIA、SAP、Salesforce、主流云厂商 | 官方 feed 优先 | 增加 ROI、部署、采购、治理结构化标签 |
| 跨境电商 | Amazon、TikTok Shop、Ozon、Wildberries、EU TAXUD、CBP、EAEU | 反爬与登录源进入复核队列 | 与 Obsidian 增量自动化共享 dedupe key |
| 国内平台 | 淘宝/天猫、抖音、京东、拼多多；后续快手、小红书 | 当前只监测公开官方文档 | 获得商家账户、应用审核和只读 Token 后启连接器 |

主要官方入口包括：[Gemini API changelog](https://ai.google.dev/gemini-api/docs/changelog)、[GitHub Releases API](https://docs.github.com/en/rest/releases)、[SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)、[Amazon SP-API release notes](https://developer-docs.amazon.com/sp-api/lang-US/docs/sp-api-release-notes)、[TikTok Shop changelog](https://partner.tiktokshop.com/doc/changelog)、[Wildberries release notes](https://dev.wildberries.ru/en/release-notes)、[Alibaba Open Platform](https://developer.alibaba.com/docs/doc.htm?articleId=108&docType=1&treeId=154)、[Douyin OpenAPI](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/list/) 和 [JD OpenAPI](https://help.jd.com/oapihelp/question-460.html)。

## Agent 联动协议

Agent 不是按头衔传递自然语言，而是传递同一份任务合同：

| 字段 | 要求 |
|---|---|
| `event_id` | 64 位事件哈希；没有 ID 不进入下游 |
| `source_url` / `source_tier` | 原始链接与 official/platform/research/media/vendor |
| `published_at` / `captured_at` | 不明时写“未找到明确发布时间” |
| `fact` / `inference` | 事实与推断分开 |
| `confidence` / `impact` | 0–1 置信度；影响 1–4 |
| `requires_review` | 反爬、页面变化、二手摘要、合规判断一律为 true |
| `proposed_action` | 只描述下一实验，不直接执行高风险动作 |
| `approval_level` | L0–L4 |
| `result` / `evidence` | 执行后回读与证据路径 |

角色链固定为：Scout/Collector → Verifier → Strategist → Operator → Auditor → Memory Curator。任何角色都不能绕过 Evidence Gate 或审批级别；Auditor 的意见也只是候选，不拥有业务批准权。

## 审批边界

| Level | 自动化范围 | 例子 |
|---|---|---|
| L0 | 自动 | 公开来源读取、Hash、去重、健康检查、日志 |
| L1 | 自动，本地可回滚 | 草稿、分类、摘要、离线测试、候选补丁 |
| L2 | 自动但限额、只读、可审计 | 有 Token 的官方只读 API、受控浏览器核验 |
| L3 | 必须人工批准 | 商品/价格/广告/库存/订单/客户消息/平台配置写入 |
| L4 | 禁止自治 | 付款、银行、合同、法律结论、账号权限、密钥轮换、删除证据 |

## 认知晋级门

每个候选改进必须依次通过：

1. Proposal：写清问题、证据、预期收益、风险和回滚。
2. Evaluation：使用真实失败案例；Prompt/Agent 变更进入 Promptfoo 或等价回归集。
3. Shadow：至少 7–14 天不执行生产写操作，只比较建议与真实结果。
4. Audit：检查幻觉、引用、成本、延迟、误报、权限与数据泄露。
5. Promotion：人工批准后再更新 Prompt、Skill allowlist、工具或连接器。

最小指标：来源成功率、重复率、`requires_review` 命中率、事实引用率、候选拒绝率、有效行动转化率、预测校准、P95 延迟、单次成本和高风险越权次数。高风险越权目标始终为 0。

## 里程碑

| Milestone | 目标 | 退出标准 | 状态 |
|---|---|---|---|
| M0 恢复可用性 | 消除欠费模型导致的全体停摆 | 34 个角色有本地可用路径；3 条 cron 连续错误归零 | DONE |
| M1 权威采集底座 | 模型无关的来源、去重、健康和报告 | 30 分钟任务结果 0；单源失败隔离；事件有 ID/来源/置信度 | DONE |
| M2 认知质量门 | 阻止流畅幻觉进入长期记忆 | 证据外年份/版本、无 event_id 候选自动拒绝 | DONE |
| M3 双模型评审 | 本地 + 智谱独立候选与审计合并 | 本地 20 条基线 19/20（95.0%）；证据 ID 截断缺口由 Gate 拦截；仍需智谱有效余额/新 Key 与完整双跑 | BLOCKED |
| M4 资本雷达 | 公司/基金/监管事件按 watchlist 增量跟踪 | 候选清单和合同已建立；待批准 CIK/证券代码/合规 UA | NEEDS_REVIEW |
| M5 电商与国内平台只读 | 官方只读 API 与证据合同 | 账户批准、Token 最小权限、沙箱、字段映射、回放测试 | BLOCKED |
| M6 受控动作 | 从建议升级到低风险执行 | 必须通过项目 G5 影子模式与 G6 执行链 | FROZEN |
| M7 真正 24×7 | 不依赖桌面登录与单机在线 | 迁移到受管 VPS/NAS；备份、告警、SLO、故障演练 | NOT_STARTED |

## 国内平台扩展顺序

国内平台不做“一次性全接入”。每个平台都按四步复制：公开官方文档监测 → 账户/应用审批 → 沙箱或只读同步 → G6 后逐项批准写操作。优先顺序由真实商品和渠道决定，不按热门程度决定；当前建议为淘宝/天猫、抖音、京东、拼多多，之后再评估快手和小红书。

## 文件与运维入口

- 采集器：[collect.py](../../scripts/authority_radar/collect.py)
- 本地分析与证据门：[analyze.py](../../scripts/authority_radar/analyze.py)
- 确定性晨报：[report.py](../../scripts/authority_radar/report.py)
- 来源注册表：[authority_sources.json](registries/authority_sources.json)
- AI 工具治理清单：[ai_tool_registry.json](registries/ai_tool_registry.json)
- 双模型金标集：[authority_eval_gold.json](registries/authority_eval_gold.json)
- 双模型评测器：[evaluate.py](../../scripts/authority_radar/evaluate.py)
- 最近评测结果：`D:\KJDS\kjds\.runtime\authority-radar\evaluation\latest.md`
- 资本候选 watchlist：[capital_watchlist.example.json](registries/capital_watchlist.example.json)
- 国内平台连接器合同：[china_platform_connectors.json](registries/china_platform_connectors.json)
- 运行数据：`D:\KJDS\kjds\.runtime\authority-radar\`
- Chief 镜像：`D:\AI\Apps\OpenClaw\workspace-chief\memory\authority-radar-*.md`

当前 Windows Task 使用交互式当前用户并启用 WakeToRun；电脑关机或用户会话不可用时不能构成真正的 24×7。M7 前应把它理解为“本机开机在线期间持续运行”。健康脚本对 OpenClaw 快照采用 20 秒有界等待；超时会记录为失败并继续输出其它组件状态，不会让整次健康检查无限挂起。KJDS 控制平面与 G0/G1 readiness 只在配置 `KJDS_API_KEY` 时加入检查，是否将其设为硬门禁由 `KJDS_HEALTH_REQUIRED=true` 明确控制。
