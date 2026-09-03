# DeepSeek Harness 安装存证

| 字段 | 值 |
|---|---|
| doc_id | KJDS-TOOL-DSH-001 |
| 日期 | 2026-08-15 |
| 指令来源 | 经营负责人：解冻新 Agent 平台并安装 DeepSeekHarness |
| 官方仓库 | https://github.com/deepseek-ai/deepseek-harness |
| 许可证 | MIT |
| 阶段 | developer preview（官方声明可能有兼容性破坏变更） |
| 安装方式 | npm 本地固定版本安装（非全局） |
| 包名/版本 | @deepseek-ai/dsh@0.1.0-rc.6（npm latest） |
| 安装路径 | D:\KJDS\tools\deepseek-harness |
| 运行环境 | Node v24.18.0 / npm 11.16.0（本机） |
| package-lock SHA-256 | F868D16E30AB69C399CF30BEB6E20B42EC03FA36E8C233F125B6A07334410362 |
| 安装脚本放行 | @deepseek-ai/dsh-subprocess-local（官方 spawn 助手）、koffi 3.1.5、node-pty 1.1.0、@google/genai（no-op）；protobufjs postinstall 为良性空脚本，未放行 |
| 原生依赖验证 | require('koffi')=OK 3.1.5；require('node-pty')=OK（win32 prebuild） |
| CLI 验证 | dsh --version = 0.1.0-rc.6；dsh --help 正常 |
| Web 冒烟 | dsh web 后台启动 → http://127.0.0.1:3080 返回 HTTP 200（zh-CN 页面）→ 验证 PID 命令行后安全关闭 |
| 启动脚本 | D:\KJDS\tools\deepseek-harness\launch-dsh.ps1 |
| 安全边界 | 仅本地 127.0.0.1:3080；不接 Ozon 账号；无付款/调价/改库存权限；API Key 不入库 |
| 待办 | ① 首次运行需配置 DEEPSEEK_API_KEY（此前 Hermes 路由 429 无余额，需充值或换 Key/换 Provider 插件） ② 如需源码开发/插件开发再 git clone 官方仓库 |

## 对应决策

- ADR-0100-unfrozen-agent-platforms-and-expansion.md：新 Agent 平台与长期 Agent 扩编解冻。
