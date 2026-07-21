# BAS-053 Ozon 财务只读证据采集

## 结论

截至 2026-07-19，KJDS 已实现 `ozon.finance.read` 的生产安全代码路径，但尚未使用真实 Ozon 凭证执行。该能力只读取官方 Seller API 财务交易页，完整保存原始响应 Evidence，控制面只接收脱敏摘要；任何费用字段都不会未经财务批准自动进入利润账。

## 实现边界

- 固定端点：`POST https://api-seller.ozon.ru/v3/finance/transaction/list`。
- 时间：输入必须是带时区的 ISO-8601 时间，`date_from < date_to`，单次最长 31 天，发送前统一转换为 UTC。
- 分页：`page >= 1`，`1 <= page_size <= 1000`。
- 固定 v1 过滤：`transaction_type=all`、空 `operation_type`、空 `posting_number`。
- 响应：必须存在 `result.operations` 列表；存在 `page_count` 时必须为非负整数，否则失败关闭。
- Evidence：原始 HTTP 状态、安全响应头、响应体 Base64、响应体 SHA-256 和合同版本进入不可变响应包；运行完成前复验字节数、哈希和血缘。
- 摘要：仅允许合同版本、查询哈希、页码、页大小、总页数和交易条数；不保存金额、订单号、交易号或客户字段。
- 会计边界：不自动创建 `FinanceEntry`，不自动映射 `platform_fee`、`last_mile`、`return`、`advertising` 或 `tax`。

## 验证

目标测试覆盖：

- 官方路径与请求体精确匹配；
- 时区、时间顺序、31 天上限、页码和页大小失败关闭；
- `result.operations` schema 漂移失败关闭；
- 财务 worker 先 checkpoint 原始响应再 finalize；
- Pilot 成功摘要的合同版本、条数与查询哈希强校验；
- 离线预检不构造 HTTP 客户端、不输出密钥或原始查询日期。

验证命令与结果：

```text
uv run pytest -q tests/test_ozon_worker.py tests/test_ozon_read_preflight.py tests/test_pilot_runs.py --basetemp .runtime/pytest-ozon-finance-read
65 passed
```

全仓复验：

```text
uv run ruff check .
All checks passed

uv run pytest -q --basetemp .runtime/pytest-full-ozon-finance
252 passed, 1 existing Starlette deprecation warning

git diff --check
PASS（仅既有 Windows CRLF 转换提示）

pwsh -NoProfile -File scripts/verify-g1.ps1
PASS；migration=20260719_0037；api_health=true；tests=true；
ozon_worker_contract_test=true；ozon_response_integrity=true
```

## 未完成的真实验收

1. 账户负责人创建或确认仅含财务读取权限的 Ozon Seller API 凭证，并通过运行时密钥注入；不得写入仓库、文档或聊天。
2. 独立 Reviewer 激活允许 `ozon.finance.read` 的 Read-only Pilot，设置日期、请求次数和目标数上限。
3. 首次仅执行一个短期间、一页；核对原始 Evidence、页面总数和 Ozon 后台下载报告。
4. 若存在多页，按独立幂等键逐页执行并确认无漏页、重页；当前 worker 不会擅自自动遍历全部历史。
5. 财务负责人对真实 `operation_type`、`services` 等字段建立版本化映射并批准后，才能进入正式费用事实和三方对账。

因此当前状态是“代码与离线合同通过，真实账户读取待显式授权”，不能据此宣称已经取得店铺费用、完成对账或确认 SKU 真实利润。
