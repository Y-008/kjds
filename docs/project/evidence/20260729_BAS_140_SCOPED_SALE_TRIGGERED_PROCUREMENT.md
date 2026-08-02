# BAS-140 Exact-scope 真实订单触发采购审查 Evidence

## 1. 结论

`SaleTriggeredProcurementPolicy` 已从 legacy/unscoped 历史 Fact 读取升级为
`sale-triggered-jit/1.1.0` 深模块：在 scoped Batch Opportunity 内只接受同一
tenant/entity/store/grant、同一 Canonical Product、`as_of` 可见且 Evidence
完整的正式 Ozon Order Fact。按 `external_id` 取当前状态，后续取消覆盖旧触发，
多个不同当前订单按正整数数量守恒汇总。

本切片是 `DONE_ENGINEERING`，真实经营状态仍为 `no_data`：真实 PostgreSQL
`fact_records=0`，因此没有真实订单触发采购，也没有创建采购单、付款、Approval、
Permit 或平台写入。

## 2. 深模块与唯一 seam

- 需求：`BR-114`
- ADR：`docs/adr/ADR-0060-scoped-sale-triggered-procurement-review.md`
- 深模块：`apps/control_plane/sale_triggered_procurement.py`
- 唯一调用入口：scoped `BatchOpportunityWorkspace`
- 内部任务账：复用 `OperatingIntelligenceService.ensure_internal_task` 与现有
  `OperatingTask/OperationsQueue`，没有第二套采购队列或工作流引擎。
- 数据权威：正式 `FactRecordRow`、同 scope `ProductRow`、不可变
  `EvidenceRecord/Blob`；页面观察、Listing 草稿和 legacy Fact 不能触发 scoped
  采购审查。

## 3. 当前订单与失败关闭合同

- exact scope：tenant/entity/store/scope-grant/product 必须全部一致。
- 时间：`scope_as_of`、`effective_at`、`recorded_at` 均不得晚于 cutoff。
- 当前态：同一 external order 只取 effective/recorded/id 排序后的最新事实。
- 取消覆盖：最新 `cancelled/returned` 不得保留旧 `awaiting_packaging` 触发。
- 数量：只接受正整数；同一订单重放不重复计数，不同订单数量相加。
- 商业语义：SKU 必须等于 scoped Product；收入必须为正 Decimal；币种必须为
  三位大写 ASCII；合同必须为 `ozon-v1`。
- Evidence：记录必须存在、内容哈希可重算且等于 Fact 冻结的
  `source_evidence_sha256`。
- 供货与利润：current checkout 可购买且完整 downside CM3 为正时只生成内部
  review task；漂移时只生成内部 escalation task。

所有结果固定：

- `supplier_order_created=false`
- `payment_created=false`
- `automatic_procurement=false`
- `approval_created=false`
- `permit_created=false`
- `external_purchase_write=false`

## 4. 0072 PostgreSQL 迁移

迁移 `20260729_0072` 只在 `fact_records` 增加
`ix_fact_scope_order_product_effective` 局部复合查询索引，不修改任何业务行。

独立临时 PostgreSQL `kjds_mig_0072_verify` 已完成：

1. empty base → single head `20260729_0072`；
2. 索引存在且唯一计数为 1；
3. `0072→0071` 后索引计数为 0；
4. `0071→0072` 后 current 为 `20260729_0072`、索引计数为 1；
5. 核验当前数据库名后删除显式临时库，删除后存在计数为 0。

真实库只执行 forward `0071→0072`。迁移前后下列冻结行数与按 ID 排序的
内容 SHA-256 完全一致：

| 表 | 行数 | SHA-256 |
|---|---:|---|
| `fact_records` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `marketplace_observation_snapshots` | 26 | `983c2e129f27aa128244f756da5372089859d434790ddbaa4eb627391d94c86d` |
| `marketplace_observation_items` | 49 | `c5a0caf4ad6ecac53c359c14c2118609eecaac29f91d1b4120ee3c5581f05763` |
| `evidence_records` | 110 | `0292ba18a250f8fb14f7dc5c773e438ceac23e63437c33c172007f60de384033` |
| `products` | 1 | `16bdc29a2f877d4f9e465be7babdb475b3d29fe216fc22fdd9ee5d36a4835ab5` |
| `operating_tasks` | 2 | `fbcae62fccc471b331d4d0775820746fb084d5b7ea7928c7ed0769b987424102` |

真实库 current/head 均为单一 `20260729_0072`，索引计数为 1。

## 5. 测试与全门禁

- 聚焦合同：
  `tests/test_sale_triggered_procurement.py`、
  `tests/test_batch_opportunity.py`、
  `tests/test_scoped_batch_opportunity.py`：`46 passed`。
- 覆盖：跨租户/跨 grant、legacy 不回退、未来事实、坏 Evidence、SKU 错配、
  非整数数量、零收入、非法币种、取消覆盖、多订单数量守恒、重放去重、内部
  review task、零外部副作用。
- `uv run python scripts/verify_secrets.py`：
  792 个非忽略工作树文件、581 个历史路径通过。
- `uv run ruff check .`：通过。
- 全量后端：`817 passed`，9 个已知依赖弃用 warning。
- `git diff --check`：通过；仅 Git 的 CRLF 提示，无 whitespace error。
- Web `npm ci`：0 vulnerabilities。
- Web `npm test`：`66 passed`。
- Web `npm run build`：36 路由生产构建通过。

## 6. 运行验收

- PostgreSQL/API/Web/media-worker 四容器均 `healthy`。
- `/health/ready`：HTTP 200，database `ok`，version `0.59.0`。
- 运行镜像 Alembic current/head：`20260729_0072`。
- 运行镜像采购策略：`sale-triggered-jit/1.1.0`。
- 匿名 `GET /v1/batch-opportunities/latest`：HTTP 401。
- 认证 exact store：HTTP 200，`status=no_data`，当前 scoped Catalog、
  Observation、Evidence、Supplier cohort 均为 0。
- 认证越权 `store_ref=other-store`：HTTP 403。
- OpenAPI 包含 `/v1/batch-market-scans` 与
  `/v1/batch-opportunities/latest`。
- 运行读取前后 `operating_tasks=2`，无读取副作用。
- 首次全镜像并行构建遇到 Docker Hub Node 匿名令牌 EOF；未替换运行容器。
  随后只重试本切片所需 API/media-worker 构建并成功，Web 源码未变且已通过
  本地生产构建。

## 7. Graph/Harness 投影

`scripts/seed_bas140_agent_graph.py` 将 BR-114→ADR-0060→策略模块→聚焦测试
→0072→运行边界→本 Evidence→BAS-140 计划形成稳定节点/边，并使用注册
Verifier 的追加式 Observation 驱动状态。状态栏展示的是 pytest、PostgreSQL、
容器/API 与本 Evidence 的真实观测；模型文字不能自证。

## 8. 未关闭的真实经营 Gate

- 正式 Ozon Order Fact：0。
- 正式采购审查任务：本次未新增。
- Supplier Offer/完整 landed cost/订单对应实际 CM3：无当前真实订单输入。
- 独立采购 Approval、一次性采购 Permit、付款页 Readback、Kill Switch 与
  Compensation：未建立，外部采购保持关闭。
- 0.59 PM/RA Release Gates：继续 `REJECTED`。
- Pilot/Final Gates：未通过。
- Ozon、供应商、采购、付款、广告 external write：全部关闭。

因此本 Evidence 只证明 AI ERP 的 M3 OMS→采购审查软件链路和失败关闭治理，
不证明已经出单、已经下单或已经盈利。
