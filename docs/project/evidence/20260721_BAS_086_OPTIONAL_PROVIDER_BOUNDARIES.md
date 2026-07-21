# BAS-086 可选 Provider 运行边界证据

日期：2026-07-21
分支：`refactor/optional-provider-boundaries`

## 结果

- ComfyUI 继续作为默认受控媒体执行器；既有 Brief、Gate、Evidence、QA 与审批边界不变。
- Ollama、n8n 与 Firecrawl 仅在对应 URL 被显式配置后构造，并且集成健康接口只返回本次运行实际配置的 Provider。
- `/health/ready` 只检查数据库、事件存储与 Kill Switch，不调用任何 Provider 健康检查。
- Ollama 未配置时，模型发现接口以明确的 `503 ollama is not configured` 失败，不再依赖隐含的本机服务。
- Compose 与示例环境文件不再为可选 Provider 提供默认地址；删除没有运行调用方的 `MPSTATS_API_KEY` 示例配置。
- 没有新增 Provider 注册框架、依赖或数据库对象。

## 机器验证

- 新增测试验证默认运行时只包含 ComfyUI，显式配置后才包含 Ollama、n8n 与 Firecrawl。
- 新增测试验证 Ollama 缺失时模型发现稳定失败。
- 新增测试验证核心 readiness 不触发可选 Provider，而集成健康接口只检查已配置 Provider。
- 密钥扫描、写路径合同、Ruff、全部 Python 测试、Web 测试、生产构建和 `git diff --check` 均作为本 PR 的必需验证。

## 明确保留

来源连接器目录仍可描述“可接入但等待凭证”的能力；它不是运行 Provider 健康状态，也不导致服务被构造。只有实际运行配置决定集成健康与运行职责。
