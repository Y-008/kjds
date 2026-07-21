# 2026-07-18 私密启动资料工作区验证

| 项目 | 结果 |
|---|---|
| 任务 | `BAS-018` |
| 状态 | PASS |
| 默认目录 | `.runtime/startup-intake` |
| Git 状态 | 默认目录被忽略 |
| Web 发布 | 不进入 `web/public` |
| 正式事实晋升 | `false` |
| 自动测试 | 152 passed |
| 密钥扫描 | 265 个非忽略文件 |
| G-1 | PASS |

## 验收目标

1. 从五份公开空模板创建本地私密工作副本。
2. 默认副本位于已被 Git 忽略的 `.runtime/startup-intake`。
3. 目标目录已存在时只补充缺失模板，已有真实资料永不被模板覆盖。
4. 命令不读取或输出 CSV 内容，只返回目录、模板数量和安全警告。
5. 私密副本可由现有结构校验器验证，但校验不产生证据、正式事实或 Gate 放行。

## 验证结果

- PowerShell 语法解析：PASS。
- `scripts/prepare-startup-package.ps1`：支持首次创建和非覆盖式增量升级，返回新增与保留文件清单、`git_ignored_default=true` 和 `formal_fact_promoted=false`。
- `git check-ignore`：确认 `.runtime/startup-intake/g0-governance.csv` 由 `.gitignore` 排除。
- 对既有 v1 私密工作区执行升级：保留 5 份已有文件，只新增缺失的 `sku-media.csv`，`changed_existing=[]`，升级前后已有文件哈希一致。
- `uv run python scripts/validate_startup_package.py .runtime/startup-intake`：返回 `contract=kjds-startup-package-v2`、`status=structurally_valid`，3 个 SKU 各覆盖 3 家供应商和 7 类基础素材角色。
- `uv run python scripts/validate_startup_package.py .runtime/startup-intake --require-review-ready`：返回退出码 3、`submission_readiness.status=awaiting_inputs`，六个资料区均列出真实待填字段；不写数据库。
- 内容预检识别并修正公开报价模板中 `currency/source_to_cny_rate` 的列错位；当前私密报价文件与旧公开模板哈希完全一致、没有用户录入内容，因此同步修正列位置，其余已有文件仍未覆盖。
- 增量升级回归测试：在已有 `g0-governance.csv` 含用户录入内容时运行准备脚本，原内容保持不变，另外 5 份缺失模板被补齐。
- 经营看板已明确标注“双层状态”：本地命令只检查资料完整度；启动卡片只认系统 Evidence、Passport、事实账和人工审批。API/容器不挂载、不读取、不暴露 `.runtime/startup-intake`，任一层状态都不触发自动上架。
- `uv run ruff check .`：PASS。
- `uv run pytest --basetemp <repo-runtime-temp>`：152 passed，保留 1 条既有 Starlette/httpx 弃用警告。
- `uv run python scripts/verify_secrets.py`：265 个非忽略文件通过。
- `scripts/verify-g1.ps1`：PASS；迁移、真实 PostgreSQL、API/Web、Outbox、隔离备份恢复和资源清理全部通过。
- 机器报告：`.runtime/G1_VERIFICATION.json`，完成时间 `2026-07-18T11:17:12.5098405Z`。
- 恢复备份 SHA-256：`e8ecd72bf949882305a14d60085bd770391976a9e89b4aedf464e7865009694f`；恢复用时 4.136 秒；商品/订单/证据/只读运行计数为 4/0/19/1。

## 安全边界

CSV 不保存密码、API Key、Token、完整银行账号或身份文件；这些资料必须继续通过专用凭证或原始证据入口处理。`.runtime` 的 Git 忽略只降低误提交风险，不等于加密、权限隔离或正式秘密管理。

本次升级只证明目录合同能够安全演进，不证明 CSV 中存在真实经营事实。当前私密副本仍是待填写模板，不产生 Ozon 上架、采购、利润或 Gate 放行结论。
