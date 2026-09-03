# 2026-08-19 Ozon order/schema admission audit（只读）

doc_id: KJDS-EV-20260819-OZON-SCHEMA-ADMISSION-AUDIT  
audit_mode: readonly  
external_writes: false  
frontier_review: not_required

## 1. 审计目标与方法

本审计仅盘点仓库内“已被代码、测试、保存的官方文档、或 immutable captured evidence 支撑”的 Ozon schema 证据，聚焦：

- order
- posting
- warehouse
- stock / inventory
- fulfillment
- FBS / FBO / realFBS

本审计不做以下动作：

- 不编辑既有代码或既有文档
- 不执行外部写操作
- 不绕过 CAPTCHA
- 不把 research note、probe、页面观察或领域抽象猜成正式 schema

本审计结论受以下稳定边界约束：

- `docs/project/MASTER_SPEC.md:211`（BR-115）
- `docs/project/MASTER_SPEC.md:212`（BR-116）
- `docs/project/MASTER_SPEC.md:227`（BR-131）
- `docs/adr/ADR-0061-native-scoped-oms-timeline.md:19`
- `docs/adr/ADR-0062-native-scoped-inventory-fulfillment.md:25`
- `docs/adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md:20`

## 2. 结论先行

截至 2026-08-19，仓内真正可被 admission 为“可安全继续实现”的 Ozon schema，只有四层中的前两层与一部分第三层：

1. formal layer  
   已正式固化、可继续实现：
   - `ozon_order`
   - `ozon_return`
   - `ozon_inventory`

2. runtime read-model / authority layer  
   已正式固化、可继续实现：
   - `ScopedOmsWorkspace`
   - `ScopedInventoryFulfillmentWorkspace`
   - `ScopedWarehouseFulfillmentWorkspace` 的 authority seam

3. captured readonly layer  
   已有可信只读抓取字段，但只能作为 captured evidence，不得自动晋升为 formal import contract：
   - FBS posting count
   - warehouse posting aggregate
   - product summary count 的部分聚合字段

4. research / candidate / blocked layer  
   仍不可 admission 为正式 schema：
   - posting CSV 列级 schema
   - FBO order / inventory / warehouse schema
   - official warehouse execution event schema
   - `/v1/analytics/stock_on_warehouses` / `/v1/analytics/stock-on-warehouses` response schema

结论：如果后续工作要继续推进，安全边界应是“继续围绕 formal `ozon_order` / `ozon_return` / `ozon_inventory` 和只读 research/preflight 层实现”；凡缺真实官方样本、缺 immutable readonly response evidence、或仅有 probe / abstract enum 的部分，一律按 blocked 收口。

## 3. Formal layer：已 admission 的正式 schema

### 3.1 Ozon order / return formal fact

约束来源：

- `docs/project/MASTER_SPEC.md:211`  
  BR-115 明确：Ozon 订单工作台只能读取正式晋升的 `ozon_order` / `ozon_return` Fact；legacy `orders`、页面观察和模型推断都不得升格为 truth。

正式合同：

- `apps/control_plane/ozon_contracts.py:31-59`
  - `ozon_order` required:
    - `external_id`
    - `sku`
    - `quantity`
    - `currency`
    - `gross_revenue`
    - `effective_at`
  - `ozon_order` optional:
    - `status`
    - `store_ref`
  - `ozon_return` required:
    - `external_id`
    - `sku`
    - `quantity`
    - `effective_at`
  - `ozon_return` optional:
    - `amount`
    - `currency`
    - `order_external_id`
    - `return_reason`
    - `status`

导入 alias：

- `apps/control_plane/imports.py:42-54`
  - `external_id` 接受：
    - `order_id`
    - `order_number`
    - `номер отправления`
    - `номер возврата`
  - `order_external_id` 接受：
    - `parent_order_id`
    - `original_order_id`

测试锚点：

- `tests/test_ozon_contracts.py:42-59`
- `tests/test_imports.py:82-108`
- `tests/test_scoped_oms.py:87-214`

admission 结论：

- `ozon_order` / `ozon_return` 已经是 formal schema。
- 可以继续安全实现 scoped OMS、return linkage、只读分析与决策支持。
- 不得把 legacy `orders` 表或页面观察补进 truth。

### 3.2 Ozon inventory formal fact

约束来源：

- `docs/project/MASTER_SPEC.md:212`  
  BR-116 明确：库存单元必须是 `SKU + warehouse + FBP/realFBS + cluster`。

- `docs/adr/ADR-0062-native-scoped-inventory-fulfillment.md:25-38`  
  ADR-0062 明确引入 `ozon_inventory` 合同，并要求 exact inventory row。

正式合同：

- `apps/control_plane/ozon_contracts.py:72-95`
  - required:
    - `external_id`
    - `sku`
    - `warehouse_ref`
    - `fulfillment_mode`
    - `available_quantity`
    - `reserved_quantity`
    - `effective_at`
  - optional:
    - `cluster_ref`
    - `damaged_quantity`
    - `in_transit_quantity`
    - `quarantine_quantity`
    - `store_ref`

- `apps/control_plane/ozon_contracts.py:158-169`
  - `fulfillment_mode` 只允许 `FBP` 或 `realFBS`

- `apps/control_plane/ozon_contracts.py:196-209`
  - natural key = `sku:warehouse_ref:fulfillment_mode:cluster_ref`

导入 alias：

- `apps/control_plane/imports.py:91-119`
  - `warehouse_ref` 接受：`warehouse_id`, `warehouse`, `склад`
  - `fulfillment_mode` 接受：`delivery_scheme`, `scheme`, `схема работы`, `схема доставки`
  - `available_quantity` 接受：`available_stock`, `present`, `доступно`
  - `reserved_quantity` 接受：`reserved_stock`, `reserved`, `резерв`

测试锚点：

- `tests/test_ozon_contracts.py:115-156`
- `tests/test_imports.py:65-81`
- `tests/test_scoped_inventory.py:164-228`

admission 结论：

- `ozon_inventory` 已经是 formal schema。
- formal fulfillment mode 当前只 admission `FBP` / `realFBS`。
- `FBS` 当前不在 formal inventory contract 内。

## 4. Runtime read-model / authority layer：已 admission 的只读权威边界

### 4.1 Scoped OMS

证据：

- `docs/adr/ADR-0061-native-scoped-oms-timeline.md:19-36`
- `docs/adr/ADR-0061-native-scoped-oms-timeline.md:49-55`
- `docs/adr/ADR-0061-native-scoped-oms-timeline.md:66-71`
- `apps/control_plane/scoped_oms.py:58-220`
- `apps/control_plane/scoped_oms.py:198-209`
- `tests/test_scoped_oms.py:170-214`

已确认边界：

- 只读正式 `ozon_order` / `ozon_return` facts
- 最新事实 invalid 时 fail-closed / blocked
- 返回 opaque cursor
- `legacy_orders_read = 0`
- `authority = decision_support_only`
- external write=false

admission 结论：

- scoped OMS 已可安全继续实现。
- 其 truth 边界已经封死，不能通过 legacy rows 或页面观测“补全订单”。

### 4.2 Scoped inventory fulfillment

证据：

- `docs/adr/ADR-0062-native-scoped-inventory-fulfillment.md:40-49`
- `docs/adr/ADR-0062-native-scoped-inventory-fulfillment.md:59-65`
- `docs/adr/ADR-0062-native-scoped-inventory-fulfillment.md:74-75`
- `apps/control_plane/scoped_inventory.py:58-211`
- `apps/control_plane/scoped_inventory.py:213-281`
- `apps/control_plane/scoped_inventory.py:189`
- `tests/test_scoped_inventory.py:205-225`

已确认边界：

- 只读 formal inventory facts
- 严格复验 evidence / payload hash / warehouse / mode / quantity / natural key
- `marketplace_observations_inferred = 0`
- 缺 exact entity scope 时返回 `no_data`

admission 结论：

- scoped inventory 已可安全继续实现。
- 不允许从商品页、竞品页或 observation 反推库存。

### 4.3 Scoped warehouse fulfillment authority

证据：

- `docs/project/MASTER_SPEC.md:227`
- `docs/adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md:20-38`
- `docs/adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md:40-48`
- `docs/adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md:54-61`
- `docs/adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md:84-86`

已确认边界：

- admitted event 必须绑定：
  - official public API
  - authorized formal export
  - explicitly authorized adapter / warehouse system
- 当前 production DB 无 admitted warehouse execution event
- 无真实 admitted source 时只能返回：
  - `no_data`
  - `scan_evidence_pending`

admission 结论：

- warehouse authority seam 已建立。
- 但真实 warehouse execution importer / projector 当前仍 blocked。

## 5. Captured readonly layer：可信只读抓取字段，但不是 formal schema

### 5.1 FBS posting count / warehouse aggregate

只读抓取脚本：

- `scripts/capture_w2_ozon_cdp_snapshot.mjs:1-4`
- `scripts/capture_w2_ozon_cdp_snapshot.mjs:83-97`
- `scripts/capture_w2_ozon_cdp_snapshot.mjs:102-137`

已捕获 endpoint：

- `POST /api/posting-service/v2/fbs/posting/count/by-status-alias`
- `POST /api/posting-service/posting/count-by-warehouses`

已捕获 request / response 结构：

- `count/by-status-alias` request body 可见：
  - `company_id`
  - `processed_at_from`
  - `processed_at_to`
  - `status_alias`

- `count-by-warehouses` response 可见：
  - `result.warehouses[]`
  - `warehouse_id`
  - `warehouse_name`
  - `status`
  - `posting_count`

下游消费锚点：

- `scripts/run-w2-readonly-snapshot.ps1:79-89`

immutable evidence：

- `docs/project/evidence/20260815_W2_BLOCK_FORENSICS.md:55-57`
- `docs/project/evidence/20260815_W2_WAREHOUSE_RECOVERY_MATRIX.md:22-67`

admission 结论：

- 这些字段可 admission 为 captured readonly schema。
- 它们可以支持只读观测、法证说明、blocked/warehouse summary 结论。
- 它们不能自动晋升为 formal `ozon_order` / `ozon_inventory` / warehouse execution contract。

### 5.2 Product summary count

证据：

- `scripts/capture_w2_ozon_cdp_snapshot.mjs:142-155`

已捕获字段：

- `POST /api/site/product/list/summary-count`
- `visibilities['15'] -> in_sale`
- `visibilities['14'] -> to_supply`

admission 结论：

- 这只是 captured summary evidence。
- 不得把它当作正式库存快照 schema。

## 6. Research layer：已保存官方/镜像文档，但仍只能停留在 candidate

### 6.1 订单异步报告链

证据：

- `docs/project/evidence/20260814_OZON_SELLER_API_RECON_FIELDS_RESEARCH.md:23-46`

已保存候选 endpoint：

- `POST /v1/report/postings/create`
- `POST /v1/report/info`

已保存候选信息：

- `report/postings/create` request filter 可带：
  - `processed_at_from`
  - `processed_at_to`
  - `sku`
  - `offer_id`
  - `delivery_schema`
  - `statuses` / `status_alias`
  - `warehouse_id`
  - `is_express`

- `report/info` response metadata 可见：
  - `code`
  - `created_at`
  - `status`
  - `file`
  - `error`
  - `report_type`
  - `params`
  - `expires_at`

限制：

- 同文件已明确：真正 CSV 列名必须由真实下载文件首行校验，不能凭 OpenAPI / 文档推断。

admission 结论：

- 可 admission 为 research / preflight-only contract。
- 不可 admission 为 formal posting CSV schema。

### 6.2 Finance / accrual / realization candidate fields

证据：

- `docs/project/evidence/20260814_OZON_SELLER_API_RECON_FIELDS_RESEARCH.md:50-93`
- `docs/project/evidence/20260814_OZON_SELLER_API_RECON_FIELDS_RESEARCH.md:107-111`
- `tests/test_imports.py:111-158`

已保存候选 endpoint：

- `POST /v1/finance/accrual/postings`
- `POST /v1/finance/accrual/by-day`
- `POST /v1/finance/accrual/types`
- `POST /v1/finance/realization/posting`
- `POST /v2/finance/realization`

admission 结论：

- 这些可用于 research catalog、candidate adapter、只读字段对照。
- 当前不能直接 promotion 成正式 order / posting / settlement reconciliation schema。

## 7. Blocked layer：仓内没有可信 admission 证据的部分

以下项目必须直接按 blocked 处理，不得猜测：

### 7.1 FBO formal schema blocked

现状：

- `apps/control_plane/enterprise_control.py:79-82`
- `apps/control_plane/enterprise_control.py:713-728`

结论：

- FBO 仅在领域抽象 / 状态机层出现。
- 仓内没有已验证的官方字段级 order / inventory / warehouse schema。
- 不得把 FBO 自动等同为 `FBP`。

### 7.2 FBS inventory formal schema blocked

现状：

- `apps/control_plane/ozon_contracts.py:158-169`
- `tests/test_ozon_contracts.py:115-156`

结论：

- `realFBS` 被正式接受。
- `FBS` 在 formal inventory contract 中被测试明确拒绝。
- 因此 FBS 目前只有 captured posting evidence，没有 formal inventory admission。

### 7.3 Official warehouse execution event schema blocked

现状：

- `docs/adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md:40-48`

结论：

- production DB 当前无 admitted warehouse execution event。
- 不能实现真实 warehouse execution importer / projector。

### 7.4 Posting / report CSV 列级 schema blocked

现状：

- `docs/project/evidence/20260814_OZON_SELLER_API_RECON_FIELDS_RESEARCH.md:33-46`

结论：

- 当前仓内没有真实官方导出文件样本来锚定 CSV 列名。
- 不能把 `posting_number`、`status`、`warehouse_id`、`sku`、金额列等猜成正式导入合同。

### 7.5 Stock analytics response schema blocked

现状：

- `scripts/probe_ozon_paths.py:41`
- `scripts/probe_ozon_diagnostics.py:43`
- `scripts/probe_ozon_full_market.py:275-283`

候选 endpoint：

- `/v1/analytics/stock_on_warehouses`
- `/v1/analytics/stock-on-warehouses`

结论：

- 这里只有 probe，没有正式 response field evidence。
- 不能 admission 为官方库存 schema。

## 8. FBS / FBO / realFBS 分层结论

### FBS

- 有 captured readonly evidence：FBS posting count / warehouse aggregate  
  见 `scripts/capture_w2_ozon_cdp_snapshot.mjs:83-137`
- 无 formal inventory admission  
  见 `tests/test_ozon_contracts.py:115-156`

结论：FBS 当前只可用于 captured posting 观测，不可当 formal inventory schema。

### FBO

- 有领域抽象 evidence  
  见 `apps/control_plane/enterprise_control.py:79-82`, `:713-728`
- 无已验证官方字段级 schema

结论：FBO 当前整体 blocked。

### realFBS

- 有 formal inventory admission  
  见 `apps/control_plane/ozon_contracts.py:158-169`
- 有测试支撑  
  见 `tests/test_ozon_contracts.py:115-156`
- 有运营/法证只读 evidence  
  见 `docs/project/evidence/20260815_W2_BLOCK_FORENSICS.md:33-42`

结论：realFBS 是仓内证据最完整的 fulfillment mode，但其证据仍主要支撑 formal inventory contract 与 readonly运营事实，不能自动补齐 posting / FBO / warehouse execution 的 schema 缺口。

## 9. 可安全继续实现的项

基于现有 admission 证据，以下工作可安全继续：

1. 围绕 formal `ozon_order` / `ozon_return` / `ozon_inventory` 继续实现 scoped read models、投影、只读分析与决策支持。
2. 为以下 endpoint 实现 research-only / preflight-only contract：
   - `POST /v1/report/postings/create`
   - `POST /v1/report/info`
   但只固化已确认 request/response 元字段，不固化导出文件列 schema。
3. 为以下 finance endpoint 维护 candidate read adapter / catalog：
   - `POST /v1/finance/accrual/postings`
   - `POST /v1/finance/accrual/by-day`
   - `POST /v1/finance/accrual/types`
   - `POST /v1/finance/realization/posting`
   但必须明确标记为 research/candidate，不能 formal promotion。
4. 继续把 W2 CDP 只读抓取作为 captured evidence 使用于法证、运营解释与 blocked 判断。

## 10. 禁止猜测项

以下内容本轮及后续实现中都不应猜测：

- 不猜 FBO 的 order / inventory / warehouse response 字段
- 不猜 FBS/FBO 报表 CSV 的列名、类型和业务含义
- 不猜 `/v1/analytics/stock_on_warehouses` 或 `/v1/analytics/stock-on-warehouses` 的 response schema
- 不猜 `posting_number` 是否已可作为正式 order → accrual → realization → bank reconciliation key
- 不把 enum、状态机、help center、页面观察或 CDP 聚合结果升格为 formal import contract

## 11. 最终 admission / blocker 决议

最终建议如下：

- admission：
  - `ozon_order`
  - `ozon_return`
  - `ozon_inventory`
  - `ScopedOmsWorkspace`
  - `ScopedInventoryFulfillmentWorkspace`
  - `ScopedWarehouseFulfillmentWorkspace` 的 authority seam
  - W2 FBS posting / warehouse readonly captured aggregate

- blocked：
  - FBO formal schema
  - FBS formal inventory schema
  - official warehouse execution event schema
  - posting/report CSV 列级 schema
  - stock analytics candidate endpoint schema

在新增真实官方导出样本、官方只读 response evidence、或 admitted warehouse execution source 之前，上述 blocked 项应保持 blocked，不得以推断补齐。
