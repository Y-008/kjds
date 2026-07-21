# Grok Build 隔离试点与超越基准

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-ENG-GROK-001 |
| owner | 工程负责人（待确认） |
| approver | 项目负责人 |
| status | Active |
| version | 1.0 |
| last_reviewed | 2026-07-17 |
| gate | G-1；不进入生产 Gate |

## 1. 结论

Grok Build 是独立的终端 AI 编程 Agent/Harness，不是 Codex 插件，也不是 KJDS 业务运行时。它可通过交互 TUI、Headless 和 ACP 使用，并能发现项目 Instructions、Skills、Plugins、Hooks 与 MCP。

KJDS 的策略是：**安装学习、隔离对照、按证据复用、绝不形成第二控制平面。** 当前不新增适配器、不接入生产凭证、不启动常驻 ACP 服务。

## 2. 安装与本机证据

安装时间：2026-07-17。

| 项目 | 结果 |
|---|---|
| 官方仓库 | <https://github.com/xai-org/grok-build> |
| 官方文档 | <https://docs.x.ai/build/overview> |
| 安装版本 | `grok 0.2.102 (ab5ebf69ac)` |
| 可执行文件 | `%USERPROFILE%\.grok\bin\grok.exe` |
| 二进制 SHA-256 | `D09FEAC145D12636245F14732B70DD2BCB684A68A20BB8DEF3A9A2CD3EE967FF` |
| 本次安装脚本 SHA-256 | `9E995D8D6ADAA425FD52AD89B5281D6D4D9076C1835D6CC65A666EC89288D5B6` |
| 源码许可 | 第一方代码 Apache-2.0；第三方与 vendored 代码按各自许可 |

上述哈希是本机安装审计证据，不是发布方签名或官方校验值。升级后必须重新记录版本与哈希；自动更新不得被视为已经完成供应链复核。

## 3. 已验证基线

在 `D:\KJDS\kjds` 执行 `grok inspect --json`，已确认：

- 正确识别项目根目录与 `AGENTS.md` 指令族；
- 项目处于 trusted 状态；
- 未加载 MCP、Plugins、Hooks、Skills 或 Marketplace；
- 未配置额外权限规则和 Managed Settings；
- 当前只有内置 `general-purpose`、`explore`、`plan` Agent；
- 尚未完成 xAI 登录，也未设置项目 API Key。

这组“零扩展、零额外权限”结果是后续试点的安全对照。任何新增能力都必须能从下一次 `inspect --json` 中解释来源。

## 4. 首次使用

用户交互登录会打开 xAI 浏览器认证，必须由账号所有者本人完成：

```powershell
grok login
grok models
grok inspect --json
```

禁止把 `XAI_API_KEY`、登录 Token 或 `%USERPROFILE%\.grok\auth.json` 写入仓库、日志、测试夹具或项目文档。登录前不执行需要模型调用的 Headless、ACP 或写入任务。

### 4.1 第一条只读任务

登录后先运行只读架构复核，不允许子 Agent、记忆、Web 搜索或隐式写入：

```powershell
grok -p "读取 AGENTS.md 与 docs/project/MASTER_SPEC.md；只报告当前 G-1 边界、三项最重要风险和证据路径，不修改任何文件。" `
  --cwd D:\KJDS\kjds `
  --permission-mode dontAsk `
  --no-subagents `
  --no-memory `
  --disable-web-search `
  --max-turns 6 `
  --output-format json
```

验收：退出码为 0；工作树没有新增修改；输出可解析；结论引用真实仓库路径；没有请求额外权限。

### 4.2 第一条写任务

只有只读任务通过后，才能在可丢弃 Worktree 中做一个小型、无迁移、无凭证、无外部写入的任务：

```powershell
grok --worktree=kgb-pilot "只在隔离工作树中补一个失败测试并修复；执行项目规定的 lint 和 pytest；不得 push、merge、发布或修改生产配置。"
```

输出必须包含：计划、Diff、验证命令及结果、未解决风险、回滚方式。失败 Worktree 直接丢弃，不在原工作树修补。

## 5. 安全边界

| 能力 | 当前策略 | 晋级条件 |
|---|---|---|
| 仓库读取 | 允许 | `inspect` 无未知来源，任务范围有界 |
| 仓库写入 | 仅隔离 Worktree | 只读基准通过，Diff 可审，验证完整 |
| Shell | 默认询问或显式白名单 | 命令、路径、超时和副作用可解释 |
| MCP/Plugin/Hook | 默认禁止 | 来源、版本、权限、Owner、回滚均登记 |
| Web 搜索 | 默认关闭 | 任务需要且外部内容按不可信输入处理 |
| 跨会话 Memory | 默认关闭 | 有保留、删除、血缘和隐私策略 |
| ACP | 仅研究 | ADR、认证代理、超时、预算、审计、Kill Switch 完成 |
| 生产系统与凭证 | 禁止 | 当前没有晋级计划 |
| 自动 Push/Merge/Deploy | 禁止 | 不因试点成绩自动解禁 |

禁止使用 `--always-approve` 或 `bypassPermissions` 作为 KJDS 默认方式。Agent 输出不能替代阶段门、Reviewer 或确定性验证。

## 6. 从分享对话吸收的方法

分享对话《企业AI工程实施方法》是非权威设计输入，不是事实来源。可吸收并已经映射到 KJDS 的原则：

| 方法 | KJDS 落点 |
|---|---|
| Agent Control Plane | KJDS 控制面、角色权限、预算、Kill Switch；不由 Grok Build 取代 |
| Session 不等于任务状态 | 事件账本、决策账、证据、阶段门保存在项目真源中 |
| Instructions + 强制门禁 | `AGENTS.md` 指导；Ruff、Pytest、迁移、G-1 脚本确定性验收 |
| Plan Review Gate | 中高风险任务先给计划、影响、验证和回滚 |
| Skill Registry | `loop_engineering_registry.json` 管控版本、权限、评测和晋级 |
| 按需工具发现 | 首先 `inspect`，不批量暴露 MCP 与敏感工具 |
| Workload Identity | 每个执行器独立身份和最小权限，不共享生产 Token |
| Provenance 与统一语义 | 版本、哈希、请求、Diff、测试和证据路径可追溯 |
| Agent Evaluation Lab | 对真实任务比较整个 Harness，不只比较模型 |
| Engineering Memory | 事实、决策、失败、模式和能力账分离保存 |

## 7. “超越”不是功能更多

Grok Build 是对照执行器，KJDS 要超越的是“不可治理的 Agent 使用方式”，不是复制它全部功能。

主指标：

```text
安全有效交付率 =
满足规格且验证通过、无越权、证据完整的任务数
÷ 全部试点任务数
```

同时记录：

- 首次验证通过率；
- 缺陷逃逸率与需求偏差率；
- 人工审核分钟数；
- 返工次数；
- Agent/模型费用与总有效变化成本；
- 越权、敏感数据和未知工具调用事件；
- 失败后是否产生测试、规则、Skill 或负知识资产。

只有至少 10 个同类型真实工程任务形成可复现对照，才讨论“优于”。单次演示、Token 数、回答长度、主观观感或 GitHub Stars 都不能作为结论。

## 8. 阶段路线

1. **P0 已完成**：安装、版本/哈希、`inspect --json`、工具登记。
2. **P1 待用户完成**：账号所有者登录；重新执行 `inspect`，确认无未知扩展。
3. **P2 只读基准**：3 个架构/风险/测试范围任务，零工作树变更。
4. **P3 隔离写基准**：3 个小修复任务，只在 Worktree 中运行。
5. **P4 Harness 对照**：累计至少 10 个真实任务，与 Codex 当前基线比较安全有效交付率和总成本。
6. **P5 决策**：继续作为按需开发工具、停用，或提出 ACP/自动化 ADR。默认是按需工具，不晋级生产。

## 9. 停止条件

任一条件出现立即停止试点：未知插件/MCP/Hook 自动加载；非预期仓库或用户目录写入；生产凭证可见；绕过审批；不能解释的网络外传；无法复原的工作树修改；基准成本持续高于收益；同类任务连续两次出现严重需求偏差。

## 10. 权威来源

- Grok Build 源码与许可：<https://github.com/xai-org/grok-build>
- 官方概览与安装：<https://docs.x.ai/build/overview>
- Headless 与 ACP：<https://docs.x.ai/build/cli/headless-scripting>
- 企业配置、身份、权限与沙箱：<https://docs.x.ai/build/enterprise>
