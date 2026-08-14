# BAS-144 原生 exact-scope PIM 商品主数据工作台 Evidence

## 1. 工程结论

KJDS 已交付唯一的 PIM 读模型深模块
`ScopedPimWorkspace.project(...)`。它复用现有
`ScopedMarketplaceCatalogAuthority` 与
`ScopedProductContentAuthority`，以 Canonical Product 归并 Ozon
Listing/offer、marketplace SKU 绑定、未绑定 Listing、Product 主档、三类
Passport、ContentAsset、媒体 QA、身份及刊登前 readiness。Router、Web 与
Agent 均不重算业务状态。

本切片为 `DONE_ENGINEERING`，不是经营闭环。真实 exact-scope entity
authority 尚未建立，因此运行结果如实为 `no_data`，Product groups、Listing
与绑定数均为 0；系统没有合成 Product、Passport、Listing 或媒体事实。
Agent artifact 仅允许建议和内部任务，不得自批、签发 Permit 或外部写。

## 2. 深模块与失败关闭

- Requirement / Decision：BR-118、ADR-0064。
- 深模块：`apps/control_plane/scoped_pim.py`。
- API：认证 `GET /v1/pim/workspace`。
- Web：`/pim`，并可从 `/commerce-os` 下钻。
- 输入固定为 exact `tenant/entity/store/as_of`；缺 entity authority 时两个
  上游 raw authority 读取均为 0。
- 上游 contract、scope、`as_of` 或 snapshot hash 冲突时整体 blocked，不把
  冲突结果拼接成商品事实。
- 最新坏 Evidence、坏 Product/Passport/Listing/Asset 记录继续由既有 scoped
  authority 失败关闭，PIM 不回退到旧有效记录冒充 current。
- 查询、状态筛选、opaque cursor、全结果 counts 和 snapshot hash 均由服务端
  生成；游标页不会重算总数。
- 纯读组合没有 schema 变化，因此未强造 `0074`。

## 3. 接口与前端验证

- 后端聚焦服务/API：`42 passed`。
- `uv run ruff check`（本切片 Python）：通过。
- Web `npm test`：`72 passed`。
- Web `npm run build`：成功，构建包含 `/pim`。
- OpenAPI 0.59.0 包含 `/v1/pim/workspace`。
- `git diff --check`：退出 0，仅存在工作树既有 LF/CRLF 提示。
- `/pim` 覆盖 ready、partial/blocked、`no_data`、error、retry、稳定游标和
  source gaps；blocked 不再被伪装为空数据。

## 4. PostgreSQL 与真实运行

- Alembic current/head 均为唯一 `20260729_0073`。
- PostgreSQL、API、Web、media-worker 四容器均 healthy。
- `/health/ready` 为 200，版本为 0.59.0。
- PIM 匿名 401；认证 exact store 200；越权 store 403。
- 固定 `as_of=2026-07-29T00:00:00Z` 连续投影产生相同
  `snapshot_sha256`：
  `89272a8d2d58a08ab857ff4cd84b2d8fc7c2d14ccc0ff3d2f34ba1ebca0d8ee3`。
- 同一输入的 Agent artifact hash：
  `ae4cfe0612119fec635e4b77881b21d151f550e4baf4e052c9ca2c0c943aa751`。
- 当前响应：`status=no_data`、`entity_ref=null`、
  `total_product_groups=0`、`unbound_listings=0`、
  `source_gap=pim_entity_scope_authority_missing`、
  `external_write_allowed=false`。

## 5. 浏览器实测

真实 Supabase operator session、运行容器和 PostgreSQL：

| Artifact | SHA-256 | 结果 |
|---|---|---|
| `output/playwright/bas144-pim-desktop.png` | `7cc5541ae710bd4e8e30e56c020aff98d550fa9d4dacd533470fb1516d22e3b6` | 1440px，inner/client/scrollWidth = 1440/1440/1440 |
| `output/playwright/bas144-pim-mobile-390.png` | `449ced6859c3087b75fd332e8ed003f85c67fc01de626451d9b9b1b3f7af4d02` | mobile emulation，inner/client/scrollWidth = 390/390/390 |

两种尺寸均显示真实 `no_data` 与 external write false，0 console error。
`/commerce-os` 的“打开商品主数据 PIM”真实导航到 `/pim`。

## 6. 仍未关闭的经营 Gate

- 真实 Catalog、Product、Listing、Passport、媒体、订单、库存、结算与到账
  Facts 仍未形成 exact-scope 经营闭环。
- BAS-143 的市场能力映射不等于原生实现或真实验证。
- 0.59 PM/RA Release Gates、Pilot Gate 与 Final Gate 均未通过。
- Ozon、供应商、采购、付款、库存、履约、客户消息和广告 external write
  继续关闭。
- BAS-144 Harness/Graph 只记录测试、运行、浏览器和 Evidence 的 fresh
  外部观察；它不会把 `no_data` 提升为经营完成。
- `task-bas144-pytest/database/runtime/web/evidence` 均为
  `passed/fresh`；canonical Graph 当前为 51 tasks、148 nodes、156 edges、
  至少 292 条 append-only observations。
