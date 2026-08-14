# BAS-110 · tenant/entity/store 利润事实隔离

| 项 | 结果 |
|---|---|
| 记录时间 | `2026-07-28T11:19:19+08:00` |
| 分支 | `feature/batch-opportunity-mining-059` |
| 基线 HEAD | `b34a3a7`（当前 0.59 集成工作树尚未提交） |
| 版本 | API/Web `0.59.0` |
| 范围 | BR-086 / BAS-110 / ADR-0037 |
| 外部写 | 全部关闭 |

## 发现与修复

审计确认旧 `ProfitLedgerService.snapshot(store_ref=...)` 会读取全局 Product、Order、
Fact、Finance 表，再把调用方给出的 `store_ref` 放到结果里；Profit 路由也没有调用
Principal 店铺校验。这会让请求参数冒充事实归属。

运行时现只暴露 `ScopedProfitLedgerAuthority`：

1. 先验证 Principal 对 store 的权限；
2. 从 append-only ScopeGrant 读取显式 `as_of` 的 entity；
3. entity 缺失/歧义时返回 `no_data`，不调用 raw ledger；
4. 有 entity 时，逐行将订单、费用、正式 Fact、场景、结算与银行 Evidence 交给
   `ScopedEvidenceAuthority`；
5. excluded 行只返回数量与 reason count，不返回金额、SKU、订单号或 source ID；
6. 从 scoped 集合重新计算 coverage、状态、Decimal 侵蚀桥与守恒。

Raw ledger 同时增加显式 `as_of`：晚于 cutoff 的 Product/Order/Charge、Fact/Finance
recorded/effective 时间、FX、Evidence 和 Approval 被排除；未来生效或已经到期的
Evidence 不再算 current。

## API 与异常扫描

- `GET /v1/profit-ledger`
- `GET /v1/profit-ledger/erosion`
- `GET /v1/operating-intelligence/metrics` 及兼容 `/v1/metrics`
- `POST /v1/operating-intelligence/anomaly-scans` 及兼容 `/v1/anomaly-scans`

以上路径现在使用同一个 Principal/store/entity cutoff；Profit GET 新增可选
`as_of`。缺 entity 时 metrics 全部 `no_data`，anomaly scan 返回
`persisted=false/id=null`，不写 OperatingTask 或 scan run。

## 自动化验证

```text
uv run ruff check <scoped profit/runtime/router/test slice>
All checks passed

uv run pytest -p no:cacheprovider --basetemp=.tmp/pytest-scoped-profit \
  tests/test_scoped_profit_ledger.py tests/test_profit_ledger.py \
  tests/test_operating_intelligence.py tests/test_truth_governance.py \
  tests/test_api_contract.py -q
54 passed

uv run python scripts/verify_secrets.py
Secret scan passed: 645 non-ignored worktree files and 581 historical paths checked

uv run ruff check .
All checks passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
637 passed, 1 existing deprecation warning

cd web && npm ci && npm test && npm run build
50 passed; 0 vulnerabilities; Next.js production build passed

uv run python scripts/export_openapi.py
fixed OpenAPI snapshot matches runtime

git diff --check
passed
```

回归覆盖：无 entity 时 raw ledger 零读取、非法店铺 403、跨店 Evidence 排除且不泄露
业务值、显式 `as_of` 重放、晚记录排除、未来/过期/坏 Evidence、Decimal 侵蚀守恒、
scope 缺失 anomaly 零持久化、匿名 401 和 OpenAPI `as_of`。

## 真实运行证据

标准 Dockerfile 已完成 API 与 media-worker clean build；四容器均 healthy，API
`0.59.0`，Alembic current/head 为单一 `20260727_0056`。

真实 `ozon-primary` 当前没有正式 entity grant，认证调用返回：

```text
profit.status=no_data
profit.scope.status=no_data
entity_ref=null
rows=0
raw_snapshot_sha256=null
external_write_allowed=false
metrics.scope_status=no_data
metric_ready_count=0
scan.status=no_data
scan.id=null
scan.persisted=false
anomaly_scan_runs before=4 after=4
```

匿名 Profit 请求为 `401`，越权 store 为 `403`；运行 OpenAPI 含 `as_of`。本次扫描
未产生数据库写。

原冻结三条 Marketplace Observation 的 snapshot/Evidence/blob/item hashes 全部保持：

- snapshot `mos_893969993df54dc9ab0ead01c588a215`
- snapshot SHA-256
  `91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1`
- Evidence `evd_294c9c496acb4c25bd74bccd92b18780`
- Blob SHA-256
  `0d8e17d3191d42572dec874d459686c4c0d6f3948354cff8195297252c307812`
- item count `3`
- items：
  `2f18ac875e737eba84987f279f6eb4ea9f5a9a2c95f448ed7833cc4c30b74504`、
  `5d652608a84aed15f603d6a25ec43612f05057752d7fd7724e71a84c24566171`、
  `69c79e876f3a2c9c17688e11b25a467014596bb7efec592a298e918838f3fe92`

## Gate 边界

- 当前无正式 scope-bound 利润行，实际利润仍为 `no_data`，不是 0。
- 0.59 PM/RA Release Gates 继续 `REJECTED`。
- Pilot/Final Gates 未通过。
- Ozon、供应商、采购、付款、库存、价格和广告外部写继续关闭。
- pricing 继续 `not_for_sale`。
