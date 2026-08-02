# BAS-145 原生 exact-scope 供应智能 Evidence

## 1. 工程结论

KJDS 已交付唯一的供应智能读模型深模块
`ScopedSourcingIntelligenceWorkspace.project(...)`。它组合现有 PIM、
Market Radar、Scoped Batch Opportunity、Scoped Evidence、RFQ package、
RFQ dispatch proof 与 Supplier Quote authority，服务端统一输出 exact
identity 研究对象、Canonical Product 关联、三报价/RFQ readiness、原生候选
和十五项 downside CM3；Router、Web 与 Agent 不重算这些状态。

本切片为 `DONE_ENGINEERING`，不是采购或经营闭环。真实 exact-scope entity
authority 仍未建立，因此运行结果如实为 `no_data`：research cohort、
supplier observation、RFQ、accepted quote、native candidate 与十五项
downside ready 均为 0。没有合成 Product、Supplier、Quote、CM3、订单或现金
事实。

## 2. 市场基准与原生边界

- Requirement / Decision：BR-119、ADR-0065。
- Accio 当前公开 JTBD 冻结到
  `docs/project/registries/accio_sourcing_capability_benchmark.json`，来源为
  Accio 官方 About 与官方使用指南，Evidence tier C。
- Accio 不是运行依赖，未配置授权 Adapter；`mapping_is_implementation=false`。
- KJDS 不使用私有 endpoint、Cookie、session、内部 Token、CAPTCHA 绕过或
  第三方 UI/代码。
- 供应观察不升格 Supplier Offer；accepted quote 必须有独立复核和 exact-scope
  Evidence binding；screening CM3 不升格 Formal/Actual Cash CM3。
- Agent artifact 只允许建议和内部任务；不得联系供应商、发送 RFQ、接受报价、
  创建 Supplier Offer/PO/Payment/Product/Listing/Approval/Permit 或外部写。

## 3. 深模块与失败关闭

- 服务：`apps/control_plane/scoped_sourcing_intelligence.py`。
- API：认证 `GET /v1/sourcing-intelligence/workspace`。
- Web：`/sourcing-intelligence`；可从 `/commerce-os` 与 `/pim` 下钻。
- 输入固定 exact `tenant/entity/store/as_of`；缺失或无效 entity authority
  时 PIM、Market Radar、Batch、RFQ、dispatch、quote 和 scoped Evidence
  原始读取全部为 0。
- PIM/Market Radar/Batch 的 contract、scope、`as_of` 或 snapshot hash 漂移
  时，在读取 RFQ/quote 前失败关闭。
- RFQ/dispatch/quote 只有在最新 Evidence 有效且全部具备当前 exact-scope
  binding 后才可投影；坏/未绑定/跨 Product 记录使结果 blocked，并隐藏业务载荷。
- 查询、readiness 筛选、opaque cursor、全结果 counts 和 snapshot/artifact
  hash 均由服务端生成。
- 本切片是纯读组合，没有 schema 变化，未强造 `0074`。

## 4. 工程门

- 聚焦服务、API、导入与 Accio Registry：`48 passed`。
- 全量后端：`852 passed`，9 个已知依赖弃用 warning。
- Secret scan：839 个非忽略工作树文件、581 个历史路径通过。
- `uv run ruff check .`：通过。
- Web `npm ci`：0 vulnerabilities。
- Web `npm test`：`74 passed`。
- Web `npm run build`：成功，41 个 route 含 `/sourcing-intelligence`。
- OpenAPI 0.59.0 包含 `/v1/sourcing-intelligence/workspace`。
- `git diff --check`：退出 0，仅有工作树既有 LF/CRLF 提示。

## 5. PostgreSQL 与真实运行

- Alembic current/head 均为唯一 `20260729_0073`。
- PostgreSQL、API、Web、media-worker 四容器均 healthy。
- sourcing-intelligence 匿名 401；认证 exact store 200；越权 store 403。
- 固定 `as_of=2026-07-29T00:00:00Z` 连续投影产生相同
  `snapshot_sha256`：
  `8d633f8c3b4ec43ae25240349f7debdb119411c838c1548becc8e5d6141d1679`。
- 同一输入 Agent artifact hash：
  `37d6805ba42b988a62302fe87880be6f285b7353f68c9742020aa29cee73d422`。
- 当前响应：`status=no_data`、`entity_ref=null`、全部业务 counts 为 0、
  `scoped_input_read=false`、`supplier_contacted=false`、
  `rfq_dispatched=false`、`purchase_order_created=false`、
  `payment_created=false`、`external_write_allowed=false`。

## 6. 浏览器实测

真实 Supabase operator session、运行容器和 PostgreSQL：

| Artifact | SHA-256 | 结果 |
|---|---|---|
| `output/playwright/bas145-sourcing-desktop.png` | `85a0430fd3476dda0f58e53ca27d73f5ee9764ad39363ed9201d552ae4e93dbd` | 1440px，inner/client/scrollWidth = 1440/1440/1440 |
| `output/playwright/bas145-sourcing-mobile-390.png` | `192f3392097bc3069b69600089b362a2186e04054f99c84a857d24a1c41f2bce` | 390px full-page，inner/client/scrollWidth = 390/390/390 |

桌面与 390px 均显示真实 `no_data`、0 研究/报价/CM3 与全部 no-write
边界，0 console error。`/commerce-os` 的“打开原生供应智能”真实导航到
`/sourcing-intelligence`。

## 7. Graph 与未关闭 Gate

- `task-bas145-pytest/database/runtime/web/evidence` 均由注册的独立 verifier
  记录为 `passed/fresh`；canonical Graph 为 56 tasks、155 nodes、162 edges、
  至少 298 条 append-only observations。
- Graph 的 passed 只证明工程合同、运行、浏览器和 Evidence，不会把
  `no_data` 晋升为供应覆盖或采购完成。
- 真实 entity、三个 SKU、Ozon demand、三报价、RFQ 回执、样品、正式
  downside CM3、Order、Settlement 与 Cash Facts 仍未形成。
- 0.59 PM/RA Release Gates、Pilot Gate 与 Final Gate 均未通过。
- Ozon、供应商、采购、付款、库存、履约、广告和客户消息 external write
  继续关闭。
