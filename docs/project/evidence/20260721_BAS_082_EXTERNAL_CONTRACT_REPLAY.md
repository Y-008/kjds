# BAS-082 外部合同固定样本回放证据

- 日期：2026-07-21
- 状态：`PARTIAL_BLOCKED`（本地工程完成，CI 平台未配置）
- 需求：`BR-063`
- ADR：`docs/adr/ADR-0017-external-contract-replay-fixtures.md`

## 交付

在 `tests/fixtures/external_contracts/` 建立最小脱敏样本集和机器清单。六个样本分别覆盖 Ozon 商品读取、ComfyUI 历史输出和 Ozon 财务 CSV 的成功与结构漂移；每项声明外部系统、合同版本、预期结果和原始文件 SHA-256。

`tests/test_external_contract_replay.py` 先验证清单、路径约束、唯一 ID、敏感数据声明和文件哈希，再把样本交给现有生产解析路径：

- `OzonSellerClient.offer_state()`；
- `ComfyImageExecutionService._first_image()`；
- `OzonImportService.preview_file()`。

没有新增运行时服务、数据库表、迁移、依赖、录制代理或第二套适配器。限流、超时、写入结果不确定、幂等重放、回读和完整媒体状态仍由已有专项测试负责。

## 验证结果

- 新增固定样本回放：`7 passed`。
- Ozon、ComfyUI、财务导入专项回归：`39 passed`。
- 全量 Python：`336 passed, 1 warning`。
- Ruff：`All checks passed`。
- `git diff --check`：通过；仅报告工作树既有 Windows 行尾转换提示。

首次全量执行有 7 项在 pytest 建立 `C:\Users\Lunar\AppData\Local\Temp\pytest-of-Lunar` 时遇到 Windows `PermissionError`，当次已有 329 项通过。改用仓库内独立 `--basetemp` 后全量 336 项通过，未把环境错误误记为代码成功。

## 未被本任务证明的事项

- 合成样本不证明 Ozon 或 ComfyUI 当前线上响应未变化。
- 尚未取得可提交仓库的真实脱敏 Ozon Seller API 响应。
- 没有调用生产账户、生产 ComfyUI、付款、采购、发布、广告或财务入账。
- 没有数据库/API 变更，因此本任务不产生迁移或 `/health` 新验收。
- 当前仓库没有 Git remote，也没有 GitHub Actions、GitLab CI、Azure Pipelines 等流水线配置；测试已被默认 pytest 发现，但尚不能声称在远端 CI 执行。

## 下一步

交付平台确定后，只需让其运行现有 `uv run ruff check .` 与 `uv run pytest -q`，不再建立第二套测试入口。取得真实响应后，由平台集成 Owner 脱敏并独立复核，再替换对应合成样本；合同版本变化时新增版本，不覆盖旧样本。下一工程任务优先连接真实经营 Owner 提供的组合风险阈值和 `forecast → commitment → actual` 映射，不在代码中虚构现金安全线。
