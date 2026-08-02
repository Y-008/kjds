# BAS-105 利润款 ERP Item 草稿同步 Evidence

| 项 | 值 |
|---|---|
| 时间 | 2026-07-27T18:10:00+08:00 |
| 分支基线 | `feature/batch-opportunity-mining-059`（未提交 0.59/M0 工作树） |
| 版本 | API/Web `0.59.0` |
| 需求 | BR-055 / BR-078 / BR-082 / BR-083 |
| ADR | `docs/adr/ADR-0033-profit-qualified-erp-item-sync.md` |
| 实现状态 | 工程链路已实现；真实利润款 0、ERPNext 连接器未配置，因此真实 ERP 写入 0 |

## 结果

`ProfitQualifiedErpSync` 已把“利润款 → ERP Item 草稿 → 显式 dispatch → 回读”收敛成一个服务端深模块。调用方不能提交利润布尔值或 ERP payload；模块重新读取授权店铺的不可变 Batch Opportunity run/candidate，并复验 exact identity、Canonical Product、完整十五项成本 Evidence、悲观 CM3 大于冻结门槛、侵蚀守恒为零、Evidence 完整性与 payload SHA-256。

通过后只生成 `docstatus=0`、`opening_stock=0` 的 ERPNext Item 草稿和 PostgreSQL 幂等 outbox。统一 Action Policy / Write Path Registry 将其登记为 `erp_item_draft_sync` L1 可逆侧车草稿；prepare 与 dispatch 均重新授权，dispatch 还会再次复验来源与 Evidence。写后必须精确回读 `item_code/docstatus/custom_kjds_product_id`，差异进入 `failed_readback`。采购单、收货、库存调整、付款、广告和 Ozon 写入始终为 false。

Frappe 适配器按[官方 REST API](https://docs.frappe.io/framework/user/en/api/rest)的 DocType resource create/read 方式实现，凭据只从运行环境读取。缺任一连接参数时固定 `blocked_connector_not_configured`，不回显凭据、不尝试远端调用。

## 真实经营复验

- 最新 run：`bor_19dea0c1ea1be50d6d854315`
- run Evidence：`evd_6a437f6344ff432684a7bf1335431116`
- 当前观察：32
- Ozon/1688 精确身份：2
- checkout 成本可评估：0
- 完整十五项成本：0
- downside CM3 正：0
- `profit_qualified`：0
- ERP sync rows：0
- ERPNext connector：未配置
- Supplier Order / Payment / Ozon write：0 / 0 / 0

因此本轮没有把任何候选写成 ERP “利润款”。当前下一动作仍是：不下单，补齐目标数量、MOQ、税、目标仓运费和可复核 checkout Evidence，再由服务端重算十五项悲观 CM3。

## 数据库与迁移

- Alembic single head/current：`20260727_0055`
- 真实库执行：`0054 → 0055`
- 迁移前后 Observation 冻结集合：14 个 snapshot；汇总 SHA-256 均为 `a405f29dc014211591c37f65499103d2bd1054bd092a71f74c754385ff66ee06`
- 新表 `profit_erp_item_syncs` 当前 row count：0
- 独立临时 PostgreSQL：base→0055 成功；0055→0054→0055 成功；临时库已删除

## API、容器与浏览器

- `GET /v1/erp/profit-items`
- `POST /v1/erp/profit-items/syncs`
- `POST /v1/erp/profit-items/syncs/{sync_id}/dispatch`
- 匿名 GET：401；认证 GET：200，返回 `state=no_data`、`profit_qualified=0`、`sync_records=0`
- OpenAPI 0.59.0 包含上述 3 条路由
- PostgreSQL / API / Web / media-worker：全部 healthy
- 桌面截图：`output/playwright/release-0.59.0/profit-erp-desktop.png`
- 390px 截图：`output/playwright/release-0.59.0/profit-erp-mobile-390.png`
- 移动端：`innerWidth=390`、`scrollWidth=390`；页面包含“利润款写入 ERP”真实区域

## 门禁

- `uv run python scripts/verify_secrets.py`：618 个非忽略工作树文件、581 个历史路径，通过
- `uv run ruff check .`：通过
- `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local-final3`：600 passed
- `git diff --check`：通过（仅 Git CRLF 提示）
- `web/npm ci`：通过
- `web/npm test`：49 passed
- `web/npm run build`：通过，22 个路由生成成功
- Docker API/Web/media-worker 镜像构建成功，最终四容器健康

## 未关闭项

- P0 / auto-fix next data step：缺目标仓 checkout、税与完整成本 Evidence，真实利润款仍为 0。
- P1 / defer：ERPNext 测试公司、最小权限 Item 用户、备份恢复和卸载演练尚未配置；配置前远端同步保持阻断。
- P0 / no-op：不生成采购、付款、广告或 Ozon 写入；真实出单后的采购继续遵守 `sale_triggered_jit`。
