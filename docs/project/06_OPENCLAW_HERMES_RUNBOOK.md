# OpenClaw–Hermes 世界级本机 Agent 栈运行手册

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-OPS-AI-001 |
| owner | 本机操作员 |
| approver | 项目负责人 |
| status | Active |
| version | 2.3 |
| last_reviewed | 2026-07-22 |
| next_review | 2026-08-16 |
| applies_to | 本机 OpenClaw 2026.7.1-2、Hermes Agent 0.19.0、ComfyUI 0.28.2 |

## 当前结论

本机已经形成可运行的分层 Agent 栈，而不是简单堆叠 Skills：

```text
OpenClaw（控制面、角色 Agent、飞书入口）
  ├─ 每个角色的最终 Skill allowlist
  ├─ 6 个显式允许的外部插件 + stock memory-core
  ├─ 受控 MCP：GitHub、Context7、Playwright、只读 Filesystem
  └─ hermes-gateway
       └─ Hermes（执行/反思/Skill Curator/Bundle，人工审批默认开启）
            ├─ 本地主模型：Ollama gemma4:26b，65,536 context
            ├─ GitHub Official MCP + Context7 MCP
            └─ 云模型保留为充值/换证后的可选路径
```

2026-07-16 的最终验收：

- Hermes 本地模型实际返回 `HERMES_LOCAL_OK`；
- OpenClaw `local-gemma` 实际返回 `OPENCLAW_LOCAL_OK`；
- OpenClaw Chief 经 `hermes-gateway/hermes-agent` 成功完成真实调用；
- Hermes 依赖审计：128 个组件，0 个已知漏洞；
- OpenClaw 安全审计：0 Critical、4 Warning、2 Info；
- OpenClaw 配置校验通过，Gateway 与飞书 Channel 运行中；
- OpenClaw Chief 的模型可见技能由 900+ 收敛为 37 个；本地 26B Agent 已禁止 Web/Browser 工具。
- 33 个角色默认使用 Hermes Gateway，1 个 Local Gemma Worker 直连 Ollama，1 个 Auditor 使用智谱优先、本地回退；智谱 402/429 不再阻塞其它角色。
- 三条原有无人值守任务已改为可验证 command job；健康、晨报、AI 候选分析均实际运行，连续错误归零；另有每周 20 条本地金标回归，当前基线 19/20（95.0%），低于 90% 时任务自动失败并进入错误计数。
- 24×7 来源采集与认知晋级规则见 [07_CONTINUOUS_INTELLIGENCE_AND_AGENT_OS.md](07_CONTINUOUS_INTELLIGENCE_AND_AGENT_OS.md)。

2026-07-22 更新后复验：

- OpenClaw CLI/Gateway 为 `2026.7.1-2 (0790d9f)`，Gateway 保持 `127.0.0.1:18789`；
- Brave、Feishu、Firecrawl、Parallel、Tavily 均为 `2026.7.1`，Codex 为 `2026.7.1-1`；外部插件 allowlist 仅含这 6 个 ID，`plugins doctor` 为 0 issue；
- `research` Agent 共发现 57 个技能，26 个依赖满足、7 个对模型可见、0 个缺失依赖；其它角色不能沿用这个数字，必须各自复验；
- OpenClaw 当前安全审计为 0 Critical、5 Warning、2 Info。新增重点是：Skill allowlist 不能约束 host-exec 进程访问全局 MCP；本 Gateway 仍只能按单一可信操作员模型使用，不能当作敌对多租户隔离；
- Hermes 为 `v0.19.0 (2026.7.20, 86fb0463)`，129 个组件无已知漏洞；skills/memory 写入需审批、agent-created skill 保护和 checkpoint 已开启；
- Hermes 中高风险的 `oss-forensics`、`watchers` 已移除，保留 9 个已扫描的工程技能。当前配置模型最小调用返回 HTTP 429“余额不足或无可用资源包”，因此只证明 CLI 与错误回读正常，不证明当前模型可用；
- OpenClaw 中一条 2026-07-07 的旧 Task/Flow 仍因存在 backing session 被维护预览保留。未直接修改 SQLite，也不把“清理未发生”伪报为完成；
- ComfyUI 已升至官方 `v0.28.2`，默认只加载固定第三方白名单，另有纯核心回滚模式。Triton 补丁经 30 对 A/B 后因中位耗时慢 25.07% 未晋升默认路径。

上述 2026-07-16 项保留为历史基线；任何与 2026-07-22 复验冲突的“成功”不得当作当前状态。

## 为什么这样选

| 层 | 采用 | 原因 | 未采用/延后 |
|---|---|---|---|
| GitHub | 官方 `github-mcp-server` 1.6.0 | 官方、MIT、只读和 lockdown 模式、校验下载哈希 | 废弃的 Node GitHub MCP、社区写权限 MCP |
| 文档检索 | Context7 MCP 3.2.3 | 按库解析并读取当前技术文档 | 无来源聚合器作为默认事实源 |
| 浏览器 | Playwright MCP 0.0.78 | 官方 Microsoft 实现，隔离、无头、阻止 service worker | Puppeteer 重复栈、社区浏览器 MCP |
| 文件 | Filesystem MCP 2026.7.10 | 固定版本、本地运行、只读工具过滤 | 全盘写权限 |
| 工程方法 | Superpowers 的 TDD、计划、执行、评审、验证、worktree、并行调度 | 可组合、测试优先、交付闭环 | 被 Hermes 扫描器阻断的社区 Skill 不强行绕过 |
| 研究安全 | 来源登记 + GitHub/官方文档 + 独立复核 | 证据优先、供应链调查、增量监控；不依赖高风险自动执行 Skill | `oss-forensics`、`watchers` 已从 Hermes 移除 |
| 本地模型 | `gemma4:26b` | 已在本机存在、262K 原生上下文信息、离线可用；运行时限制为 65K | 1B–3B 模型不用于高权限任务 |

参考入口：[Hermes 文档](https://hermes-agent.nousresearch.com/docs/)、[Hermes Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)、[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)、[OpenClaw Skills](https://docs.openclaw.ai/skills)、[OpenClaw MCP](https://docs.openclaw.ai/cli/mcp)、[OpenClaw 安全](https://docs.openclaw.ai/gateway/security)。

## 已安装能力

### OpenClaw

- 角色基线：brainstorming、writing/executing plans、systematic debugging、TDD、verification、code review、worktree、parallel agents、finish branch、healthcheck、session logs、taskflow。
- Chief：保留角色级精选技能配置；2026-07-22 未重新计数，不能继续把旧的 37 当作当前验收数字。
- 开发/架构/QA：浏览器、文档、测试、评审与安全能力。
- 研究/审计：GitHub、论文、公司与竞争情报能力。
- 经营/Ozon：跨境电商、Amazon/Ozon 运营、定价与竞品能力。
- 媒体/文档：PPTX、XLSX、DOCX、PDF、Canvas。
- `local-gemma`：只保留 3 个轻量技能，直接使用 `ollama-direct/gemma4:26b`，Web 与 Browser 被 Provider 级策略拒绝。

文件未因收敛被删除；allowlist 是最终可见能力边界，可按角色回滚。

### Hermes

新增并通过安装扫描的工程技能：

- `test-driven-development`
- `verification-before-completion`
- `writing-plans`
- `executing-plans`
- `receiving-code-review`
- `requesting-code-review`
- `using-git-worktrees`
- `finishing-a-development-branch`
- `dispatching-parallel-agents`

`oss-forensics` 与 `watchers` 已在 2026-07-22 安全复核中移除，不再属于 Hermes 当前能力面。需要供应链或增量调查时，复用 GitHub Official MCP、Context7、官方来源、静态扫描与 KJDS Evidence，不以强行安装 Skill 换取“全能”。

未强行安装：Superpowers 的 `systematic-debugging`、`brainstorming` 在 Hermes 社区 Skill 扫描中被阻断。OpenClaw 已有自己的可信副本，因此不以 `--force` 绕过隔离策略。

Hermes 可用 Bundle：

| 命令 | 用途 |
|---|---|
| `/worldclass-chief` | 总调度、研究、工程与 OpenClaw 协作 |
| `/worldclass-dev` | 计划、worktree、TDD、评审、验收、收尾 |
| `/worldclass-research` | GitHub 调研、OSS 取证、来源验证 |
| `/top-ai-assistant` | 原有综合能力包，保留兼容 |

Hermes 的插件与 Skill 继续按最小权限启用；浏览器、Web、vision 与 Playwright 能力可用，但 `computer_use/browser-cdp` 尚未验收为可用。不能因为 Edge 已登录就宣称 Hermes 已连接该会话；专用 KJDS Profile、loopback attach、账户 readback 和重启复验通过前仍是未连接状态。

## MCP 清单与权限

| 端 | Server | 验收 | 安全边界 |
|---|---|---|---|
| OpenClaw + Hermes | `github-official` | 30 tools | 运行时从 `gh` 读取认证；read-only；lockdown；配置不存 Token |
| OpenClaw + Hermes | `context7` | 2 tools | 固定 3.2.3 |
| OpenClaw | `playwright` | 22 tools | headless、isolated、Edge、阻止 service worker；拒绝 unsafe code 与 upload |
| OpenClaw | `filesystem` | 10 tools | 仅批准目录；拒绝 write/edit/create/move |
| OpenClaw | `hermes-remote` | 保留 | 既有 SSH 能力，不扩大权限 |
| OpenClaw | `gbrain` | 保留 | 既有本地能力 |

Node MCP 依赖安装在 `D:\AI\Apps\MCP\node-servers`，均为精确版本；不在生产启动时使用 `@latest`。

该表的工具数来自既有验收。2026-07-22 更新后的 OpenClaw 插件/技能复验已通过，但 Hermes 组合 MCP 测试曾挂起，尚未取得完整的更新后通过记录；在逐个 server 重跑成功前，不能把旧工具数解释为当前端到端可用。

官方 GitHub MCP 安装在 `D:\AI\Apps\MCP\github-mcp-server\1.6.0`。下载 SHA-256 已与官方 checksum 比对，结果为 `699d91a1f49897d9c51cef5794cb423401a1ab27e263c76168c133dff0d004e0`。

## 模型与当前云端状态

Hermes 保留 `ollama/gemma4:26b` 作为本地回退配置，运行时 context 设为 65,536；但 2026-07-22 的默认配置最小调用实际走到外部 Provider 并返回 429。现状是“历史本地路径通过、当前默认模型路径失败”，不能只引用 2026-07-16 的成功：

| 路径 | 2026-07-16 实测 | 处理 |
|---|---|---|
| 智谱 GLM-5.2 | HTTP 402/429，额度或限流不可用 | 充值、设月度硬预算并轮换已在聊天暴露过的 Key 后再启用 |
| DeepSeek Direct | HTTP 429，无余额/资源包 | 充值或替换有效 Key |
| 本地 CPA Proxy | HTTP 401，Provider Token 过期 | 重新认证 Proxy Provider |
| Ollama Gemma4 26B | 成功 | 当前稳定离线主路径 |

2026-07-22 当前复验：默认 `hermes -z` 返回 HTTP 429“余额不足或无可用资源包”。恢复前需先明确 Provider 路由，再分别验证显式本地模型和默认模型；只有返回预期文本且运行记录可追溯，才能重新标记 current pass。

Hermes 的 DeepSeek 与 CPA Key 已从 `config.yaml` 迁入 `.env`，配置只保留环境变量引用。文档、Git、日志和聊天中不得保存任何明文密钥。

## 使用

```powershell
# Hermes CLI（使用已建立的 Windows 策略兼容包装器）
hermes --version
hermes -z "你的任务"

# 使用精选 Bundle
hermes -z "/worldclass-dev 为当前任务制定计划并执行验收"

# OpenClaw 配置与安全检查
& D:\IT\openclaw.cmd config validate
& D:\IT\openclaw.cmd security audit --json

# MCP 连通性
& D:\IT\openclaw.cmd mcp probe github-official --json
hermes mcp test github-official
hermes mcp test context7

# 显式通过 Hermes
& D:\IT\openclaw.cmd agent --agent chief --model hermes-gateway/hermes-agent --message "状态检查"

# 纯本地、安全受限 Agent
& D:\IT\openclaw.cmd agent --agent local-gemma --message "状态检查"
```

Hermes CLI 的原生 `venv\Scripts\hermes.exe` 被 Windows 应用控制策略阻止；`D:\IT\hermes.cmd` 已改用获准的 Python 运行时并补齐 venv/pywin32 搜索路径。不要删除该包装器。

### ComfyUI 受控模式

```powershell
# 默认：官方核心 + 固定、已审查第三方白名单；loopback 8189
pwsh -NoProfile -File D:\AI\Apps\OpenClaw\workspace-chief\scripts\start-comfyui-latest.ps1 -Mode trusted

# 回滚/排障：只加载官方核心节点
pwsh -NoProfile -File D:\AI\Apps\OpenClaw\workspace-chief\scripts\start-comfyui-latest.ps1 -Mode core
```

`trusted` 模式的节点数为 1186，`core` 为 807；两个模式均已从修改后的启动脚本真实启动并读取 `/object_info`。Manager 的任意 Git URL 和 pip 安装均关闭。`PatchTritonVAE` 虽在 trusted 模式可见，但 A/B 未达到性能晋升阈值，默认 workflow 不引用它。合成夹具只能验工具链；真实商品保真验收必须使用供应商授权原图，并通过 KJDS 素材 readiness、Evidence、QA 与审批。

### 已登录浏览器边界

OpenClaw/Hermes/1688-cli 需要登录态时，建立专用 KJDS Edge Profile；首登、MFA 和 CAPTCHA 由用户在可见窗口完成。自动化只允许 loopback attach、平台域名 allowlist、单一 writer、明确账户/店铺 `whoami` 回读和服务端 ID 对账。不得 attach 当前含 CPA、2FA、网银或个人资料的主 Profile，不得复制 `Cookies`、`Login Data`、`Local State` 或 MFA 密钥。

浏览器能力验收要求：每个平台连续 10/10 成功并跨两次重启，attach 不超过 30 秒，账户/商品完全匹配，跨 Tab/跨账户泄漏为 0；出现登录失效、MFA、CAPTCHA 或账户歧义时只产生一个 `human_required`，保留准确续跑点，不循环催促、不绕过平台控制。

OpenCLI 当前固定为 `@jackwener/opencli@1.8.6` 隔离试验，扩展固定为 `1.0.22`（SHA-256 `9d2e3d053948beab5d97124aa79b1532d2122e33e461eca56cac113afd33207a`）。代表性 1688 商品读取已真实运行，但因 Browser Bridge 未连接返回 `BROWSER_CONNECT`/exit 69；这是环境硬阻断，不允许通过猜测或修改平台适配器绕开。已安装的 `opencli-browser`、`opencli-browser-sitemap`、`opencli-sitemap-author`、`opencli-adapter-author`、`opencli-autofix` 与 `opencli-usage` Skill 用于下一轮的 inspect-first、network-before-DOM、失败签名、fixture、site memory 和 replay 复利；任何登录、MFA、CAPTCHA、限流或账户歧义都必须停在人工接管点。

### KJDS Evidence 健康任务

该任务复用 Windows Task Scheduler，不由 OpenClaw、n8n 或另一套工作流引擎重复调度。默认命令只生成计划，不修改系统：

```powershell
Set-Location D:\KJDS\kjds

# 1. 查看预期定义；该命令不读取 .env，不创建任务。
pwsh -NoProfile -File .\scripts\manage-evidence-health-task.ps1 -Mode Plan

# 2. 由配置负责人从 .env.example 建立 Git 忽略的 .env，填入持续控制平面、
#    独立 operator/monitor 身份映射，并手工完成失败关闭预检。
pwsh -NoProfile -File .\scripts\run-24x7-health.ps1 -ControlPlaneOnly

# 3. 只有上一步退出码为 0，且确认 .env 是任务以后仍可读取的持久配置后，才显式安装。
pwsh -NoProfile -File .\scripts\manage-evidence-health-task.ps1 -Mode Install

# 4. 等待至少三个计划周期后审计；历史不足或定义漂移时退出码为 2。
pwsh -NoProfile -File .\scripts\manage-evidence-health-task.ps1 -Mode Audit
```

安装命令不得附带任何 API key、Token 或平台凭证。`installed_pending_history` 只代表任务定义已注册，不代表验收完成；只有 Audit 返回 `accepted` 且连续三次原生完成结果为 0 才可更新 BAS-040。当前机器尚无目标任务和 `.env`，不要跳过配置负责人审批执行 Install。本机任务也只覆盖“开机且用户环境可用”的运行窗口，不等于托管 24×7。

## 安全状态与保留警告

Hermes 0.19.0：129 个组件无已知依赖漏洞。本机把 `mcp`、`pyasn1`、`pillow`、`cryptography`、`python-multipart` 与 `starlette` 固定到审计通过版本；上游升级可能回退这些 override，因此每次更新后必须重新跑 `hermes security audit`、实际模型和逐个 MCP 测试。

OpenClaw 2026.7.1-2 的当前审计为 0 Critical、5 Warning、2 Info：

1. Reverse proxy：Gateway 只绑定 loopback；如未来暴露反向代理，必须配置 `trustedProxies`。
2. Host exec / MCP 边界：Skill allowlist 只控制模型看见的 Skill，不能阻止 host-exec 进程读取全局 MCP registry。高风险角色必须收紧 exec policy 或使用独立 OS/沙箱边界，不能把 Skill 数量当权限隔离。
3. Multi-user：飞书 allowlist 会触发个人助手信任模型告警；不得让互不信任用户共享此 Gateway，也不得把个人/CPA/2FA 会话放进该运行时。
4. Plugin npm spec：Brave/Tavily 已精确 pin；Codex、Feishu、Firecrawl、Parallel 的历史 install index 仍记录未固定 spec，尽管当前已安装版本已更新。后续修复 install index 时必须保留现有配置备份并重新验收，不因“消警告”盲目重装。
5. 飞书文档创建：仅对可信 allowlist 开放；若不再需要创建文档，应关闭 Feishu doc tool。

另有旧目录 `D:\IT\OpenClaw\home\.openclaw` 的共享 SQLite 警告。它可能属于历史运行态，未经确认不得删除或移动。

## 备份与回滚

| 对象 | 回滚点 |
|---|---|
| OpenClaw | `D:\AI\Apps\OpenClaw\home\openclaw.json.worldclass-20260716-120431.bak` |
| Hermes | `D:\AI\Backups\Hermes\hermes-pre-019-20260722-185509.zip`；另保留 state snapshot `20260716-041812-before-worldclass` |
| ComfyUI | `D:\AI\Backups\ComfyUI\pre-v0.28.2-20260722-1945` |
| 配置清单 | `D:\AI\Manifests\openclaw-*.json` |

回滚顺序：停止双方 Gateway，恢复配置/快照，执行 JSON/YAML 校验，先验 MCP，再启服务，最后做一次无工具最小模型调用。不得使用破坏性 Git reset。

## 每月维护门

1. 查官方 release，不根据 Star 数自动升级。
2. 下载物必须校验 release checksum/签名；MCP 与插件使用精确版本。
3. 更新前做 OpenClaw 配置备份和 Hermes snapshot。
4. 更新后依次验证：配置、漏洞、MCP、Hermes 单调用、OpenClaw 本地调用、OpenClaw→Hermes 调用。
5. 新 Skill 先扫描、再隔离试用、最后进入角色 allowlist；扫描阻断默认不绕过。
6. 只有验收证据完整才把版本写入本手册并标记 Active。
