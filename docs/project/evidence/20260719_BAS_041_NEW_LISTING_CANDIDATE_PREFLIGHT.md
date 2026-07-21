# BAS-041 新上新候选研究预检验证

| 字段 | 值 |
|---|---|
| 日期 | 2026-07-19 |
| 状态 | DONE_ENGINEERING |
| Gate | G0 |
| 业务放行 | 否 |

## 目标

关闭“通用机会分数直接变成上新商品”的错误路径。新候选在请求供应商报价前，必须先证明证据属于同一个商品假设、仍在有效期内、来源不单一，并完成供货与合规红线预检。

## 实现边界

- 复用现有 `MarketObservation`、Repository 和市场情报服务，没有新增数据库表、迁移、队列或评分基础设施。
- `POST /v1/market/candidates/assess` 只读评估已入账观测。
- 五类必需指标为 `demand_signal`、`competition_gap`、`supplier_available`、`compliance_redline`、`return_risk`。
- 观测必须以 `dimensions.candidate_ref` 精确绑定候选；其他候选的证据不能混入。
- 默认只接受 `as_of` 前 90 天内的观测，未来、过期、零可信度、越界与非法布尔值均失败关闭。
- 至少两个独立来源族；URL 按末两级域名归并，避免把同一机构的不同子域误算成独立来源；非 URL 退回来源标识。
- 当前合规红线返回 `reject`；证据不足返回 `collect_evidence`；全部满足仅返回 `request_three_quotes`。
- 所有结果固定声明 `automatic_product_creation=false`、`automatic_listing=false`，并要求三家供应商报价。

## 验证

```text
uv run pytest tests/test_core.py -q
15 passed

uv run pytest tests/test_api_contract.py tests/test_core.py -q
19 passed

uv run pytest -q --basetemp .runtime/pytest-bas041-<timestamp>
210 passed

uv run ruff check apps/control_plane/intelligence.py apps/control_plane/api.py tests/test_core.py
All checks passed

uv run ruff format --check apps/control_plane/intelligence.py apps/control_plane/api.py tests/test_core.py
3 files already formatted
```

OpenAPI v1 快照已由项目既有导出脚本更新，契约测试通过。

项目总门禁使用 PowerShell 7 执行 `scripts/verify-g1.ps1`，结果为 `PASS`；迁移头为 `20260718_0036`，数据库清理完成。Windows PowerShell 5 的首次调用在前置版本检查即失败，未进入测试或产生业务写入；随后按脚本合同改用 `pwsh` 重跑。

## 尚未证明

- 尚未录入任何真实新上新候选，也没有把公开搜索结果写成正式 Evidence。
- 尚未取得三家真实供应商报价、样品、包装/重量实测、物流价、关税、退货准备金或 Ozon 实际费率。
- 尚未完成俄罗斯/EAEU 商品级合规结论、知识产权审查或可售性批准。
- 尚未计算任何真实候选的风险调整后 CM3，也没有创建 Product、采购单、图片、Listing 或平台写操作。
- `SKU-001/UNK-001/005` 保持阻塞，下一步是采集当前市场与货源证据并运行本预检。
