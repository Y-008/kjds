# BAS-048 真实需求报告门与候选 readiness 防串组

| 字段 | 值 |
|---|---|
| 日期 | 2026-07-19 |
| Gate | G0 |
| 状态 | DONE_ENGINEERING |
| API 版本 | `0.35.0` |
| 业务事实晋升 | 否 |
| 平台写入 | 否 |

## 问题

原 readiness 用全部 Product 行判断“已有三个候选”。这会让 Ozon 历史目录、人工直建商品，甚至缺少候选研究血缘的商品错误满足 `SKU-001`，并继续贡献 Passport 与三报价完成数。同时，候选研究前没有独立表达“真实需求报告已取得”的 `SKU-000` 门。

## 实现

- G0 新增 `SKU-000`：Evidence 必须有效、链接到 `gate_requirement/SKU-000`，元数据声明 `source_system=ozon_data`，且 `report_window_days >= 28`。
- Gate Evidence 上传接口仅允许 reviewer、compliance 或 admin 提交 `SKU-000`，并在捕获 Blob 前校验上述来源和窗口；缺失时返回 422。
- `SKU-001` 只统计同时存在 `product.candidate_sourcing_workspace_created` 事件和有效 `candidate_basis` Evidence 血缘的 Product。
- `SKU-002/003` 的 Passport、供应商和正 CM3 数量也只从上述合格候选计算，防止历史目录绕过候选门。
- readiness 返回合格候选 ID、历史/不合格 Product 数和总数，便于前端解释阻断原因。
- Web 启动路径把 `SKU-000` 放在 `SKU-001` 前，链接 Ozon Data 正式入口且不生成虚假的需求报告模板；Reality Gate 提供固定 `SKU-000`、`ozon_data` 和窗口字段的专门上传卡，成功后刷新 readiness。候选步骤明确“研究并交接”。

## 验收

- 三个完成交接且带有效血缘的候选可满足 `SKU-001`。
- 三个仅存在于历史目录的 Product 不能满足 `SKU-001/002/003`。
- 公开示例来源、缺失来源或短于 28 天的报告不能满足 `SKU-000`。
- Web 契约验证 `SKU-000` 顺序早于 `SKU-001`，并保留真实 Ozon Data 链接。
- OpenAPI v1 快照随接口表单合同重新导出。

## 已执行验证

- `uv run pytest tests/test_readiness.py tests/test_api_contract.py -q`：9 项通过。
- `uv run ruff check apps/control_plane/readiness.py apps/control_plane/api.py tests/test_readiness.py`：通过。
- `npm test`：8 项 Web 契约/身份安全测试通过。
- `npm run build`：Next.js 生产构建通过。
- `uv run ruff check .`：通过。
- `uv run pytest --basetemp=.runtime/pytest-bas048-20260719`：222 项完整 Python 回归通过；默认系统临时目录曾因 Windows ACL 拒绝访问，改用项目内全新隔离目录后无测试失败。

## 未解除项

- 尚未取得真实 Ozon Data 报告，`SKU-000` 继续为业务阻塞。
- 本工程门不判断账户主体是否应接受 Ozon 条款，也未替其点击、下载或上传报告。
- 尚无三个真实新候选完成五指标预检和人工交接，`SKU-001` 继续阻塞。
- 本次没有创建采购、Listing、广告、价格、库存或平台写操作。
