# OpenClaw–Hermes 世界级本机 Agent 栈运行手册

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-OPS-AI-001 |
| owner | 本机操作员 |
| approver | 项目负责人 |
| status | Active |
| version | 2.0 |
| last_reviewed | 2026-07-16 |
| next_review | 2026-08-16 |
| applies_to | 本机 OpenClaw 2026.6.11、Hermes Agent 0.18.2 |

## 当前结论

本机已经形成可运行的分层 Agent 栈，而不是简单堆叠 Skills：

```text
OpenClaw（控制面、35 个角色 Agent、飞书入口）
  ├─ 每个角色的最终 Skill allowlist
  ├─ 28 个启用插件（其余未使用 Provider 插件已关闭）
  ├─ 受控 MCP：GitHub、Context7、Playwright、只读 Filesystem
  └─ hermes-gateway
       └─ Hermes（执行/反思/Skill Curator/Bundle）
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

## 为什么这样选

| 层 | 采用 | 原因 | 未采用/延后 |
|---|---|---|---|
| GitHub | 官方 `github-mcp-server` 1.6.0 | 官方、MIT、只读和 lockdown 模式、校验下载哈希 | 废弃的 Node GitHub MCP、社区写权限 MCP |
| 文档检索 | Context7 MCP 3.2.3 | 按库解析并读取当前技术文档 | 无来源聚合器作为默认事实源 |
| 浏览器 | Playwright MCP 0.0.78 | 官方 Microsoft 实现，隔离、无头、阻止 service worker | Puppeteer 重复栈、社区浏览器 MCP |
| 文件 | Filesystem MCP 2026.7.10 | 固定版本、本地运行、只读工具过滤 | 全盘写权限 |
| 工程方法 | Superpowers 的 TDD、计划、执行、评审、验证、worktree、并行调度 | 可组合、测试优先、交付闭环 | 被 Hermes 扫描器阻断的社区 Skill 不强行绕过 |
| 研究安全 | Hermes 官方 `oss-forensics`、`watchers` | 证据优先、供应链调查、增量监控 | 未审计的热门仓库自动执行代码 |
| 本地模型 | `gemma4:26b` | 已在本机存在、262K 原生上下文信息、离线可用；运行时限制为 65K | 1B–3B 模型不用于高权限任务 |

参考入口：[Hermes 文档](https://hermes-agent.nousresearch.com/docs/)、[Hermes Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)、[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)、[OpenClaw Skills](https://docs.openclaw.ai/skills)、[OpenClaw MCP](https://docs.openclaw.ai/cli/mcp)、[OpenClaw 安全](https://docs.openclaw.ai/gateway/security)。

## 已安装能力

### OpenClaw

- 角色基线：brainstorming、writing/executing plans、systematic debugging、TDD、verification、code review、worktree、parallel agents、finish branch、healthcheck、session logs、taskflow。
- Chief：37 个精选技能，额外覆盖研究、电商、定价、文档和图表。
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
- 官方 `oss-forensics` 与 `watchers`

未强行安装：Superpowers 的 `systematic-debugging`、`brainstorming` 在 Hermes 社区 Skill 扫描中被阻断。OpenClaw 已有自己的可信副本，因此不以 `--force` 绕过隔离策略。

Hermes 可用 Bundle：

| 命令 | 用途 |
|---|---|
| `/worldclass-chief` | 总调度、研究、工程与 OpenClaw 协作 |
| `/worldclass-dev` | 计划、worktree、TDD、评审、验收、收尾 |
| `/worldclass-research` | GitHub 调研、OSS 取证、来源验证 |
| `/top-ai-assistant` | 原有综合能力包，保留兼容 |

Hermes 只启用了 `security-guidance` 插件；其它云浏览器、社交、视频、搜索插件按需启用，避免扩大供应链与密钥面。

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

官方 GitHub MCP 安装在 `D:\AI\Apps\MCP\github-mcp-server\1.6.0`。下载 SHA-256 已与官方 checksum 比对，结果为 `699d91a1f49897d9c51cef5794cb423401a1ab27e263c76168c133dff0d004e0`。

## 模型与当前云端状态

Hermes 当前主模型为 `ollama/gemma4:26b`，运行时 context 设为 65,536。云端入口没有删除，但当前不能作为成功验收依据：

| 路径 | 2026-07-16 实测 | 处理 |
|---|---|---|
| 智谱 GLM-5.2 | HTTP 402，余额不足 | 充值并轮换已在聊天暴露过的 Key 后再启用 |
| DeepSeek Direct | HTTP 429，无余额/资源包 | 充值或替换有效 Key |
| 本地 CPA Proxy | HTTP 401，Provider Token 过期 | 重新认证 Proxy Provider |
| Ollama Gemma4 26B | 成功 | 当前稳定离线主路径 |

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

## 安全状态与保留警告

Hermes：0 个已知依赖漏洞。为消除审计问题，本机携带了 Hermes `pyproject.toml` 的安全版本调整；上游升级时必须重新跑 `hermes security audit` 和实际模型/MCP 测试。

OpenClaw 的 4 个 Warning 当前按以下规则处理：

1. Reverse proxy：Gateway 只绑定 loopback；如未来暴露反向代理，必须配置 `trustedProxies`。
2. Multi-user：飞书 allowlist 会触发个人助手信任模型告警；不得让互不信任用户共享此 Gateway。
3. Plugin npm spec：4 个插件的已安装版本均为 2026.6.11，但注册表仍保留未固定 spec；在线重装固定版本曾超时，后续网络稳定时用 `plugins install --pin` 修复。
4. 飞书文档创建：仅对可信 allowlist 开放；若不再需要创建文档，应关闭 Feishu doc tool。

另有旧目录 `D:\IT\OpenClaw\home\.openclaw` 的共享 SQLite 警告。它可能属于历史运行态，未经确认不得删除或移动。

## 备份与回滚

| 对象 | 回滚点 |
|---|---|
| OpenClaw | `D:\AI\Apps\OpenClaw\home\openclaw.json.worldclass-20260716-120431.bak` |
| Hermes | state snapshot `20260716-041812-before-worldclass` |
| 配置清单 | `D:\AI\Manifests\openclaw-*.json` |

回滚顺序：停止双方 Gateway，恢复配置/快照，执行 JSON/YAML 校验，先验 MCP，再启服务，最后做一次无工具最小模型调用。不得使用破坏性 Git reset。

## 每月维护门

1. 查官方 release，不根据 Star 数自动升级。
2. 下载物必须校验 release checksum/签名；MCP 与插件使用精确版本。
3. 更新前做 OpenClaw 配置备份和 Hermes snapshot。
4. 更新后依次验证：配置、漏洞、MCP、Hermes 单调用、OpenClaw 本地调用、OpenClaw→Hermes 调用。
5. 新 Skill 先扫描、再隔离试用、最后进入角色 allowlist；扫描阻断默认不绕过。
6. 只有验收证据完整才把版本写入本手册并标记 Active。
