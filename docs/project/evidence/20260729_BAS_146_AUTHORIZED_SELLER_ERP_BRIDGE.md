# BAS-146 授权 Seller ERP Bridge 与 Canonical Diff Evidence

## 1. 工程结论

KJDS 已交付唯一深模块 `ScopedSellerErpBridge`。它接收平台官方导出、
Seller ERP 正式导出或明确授权 Adapter snapshot，先形成不可变 source
Evidence，再要求独立 Reviewer 与第三位 Compliance recorder 完成
exact-scope binding；`reconcile(...)` 每次重新验证 Evidence、最新 review、
binding、撤销、scope、schema、hash 与 `as_of`，然后只读组合现有 PIM、OMS
或 Inventory 权威并输出 Canonical Diff。

本切片为 `DONE_ENGINEERING`，不是第三方接管、真实数据接入或经营闭环。
当前真实 Bridge Evidence 0、Order Facts 0、Inventory Facts 0，运行态如实为
`no_data`。没有为了截图创建 Product、Listing、Order、Inventory、Approval、
Permit 或正式 Fact。

## 2. 授权与不可越过边界

- Requirement / Decision：BR-120、ADR-0066。
- 支持来源：
  `platform_official_export / seller_erp_formal_export /
  authorized_adapter_snapshot`。
- 支持授权方式：
  first-party/account-owner export、public OAuth API、contracted API 或书面授权；
  authorized Adapter 还必须引用当前 authorization Evidence。
- 店小秘等第三方不是运行依赖；删除第三方后，KJDS 的 Evidence、Canonical
  Facts、决策与结果仍保留。
- 不使用或保存私有 endpoint、Cookie、session、内部 Token；不绕过鉴权、
  CAPTCHA、限流或撤销。
- 用户对 KJDS 的控制权不能替代第三方服务所有者的授权。
- 上传快照始终是 Observation；`matched / source_only / canonical_only /
  conflict / blocked` 都不晋升 Fact。

## 3. 三方权威链与失败关闭

1. Operator 固化原始 CSV/XLSX、provider/source kind/domain/schema version、
   显式 column map、exported time、授权方式、原始 SHA-256、header hash、
   normalized-row hash 与 row count。
2. 不同 Reviewer 固化 authentic original、authorization、exact export scope、
   schema mapping 与 no-session/secret 五项检查；任一检查失败不得 accepted。
3. 与前两者都不同的 Compliance/Admin 固化 grade-A target ID/hash binding，
   并引用 accepted review ID/hash。
4. revoke 为 append-only；最新 rejected review、revocation、expiry、坏 Evidence、
   hash/scope/schema/as-of drift、重复 canonical key 或 upstream blocked 均失败关闭。

缺失/无效 entity 或 source ID 时不读取原件和 PIM/OMS/Inventory；被阻断时
不返回受影响业务行。通用 `/v1/evidence` 禁止伪造四个 Bridge 专用 source。
四类 Evidence `source_ref` 由 PostgreSQL partial unique index 保证并发幂等。

## 4. 深模块、API 与 Web

- 服务：`apps/control_plane/scoped_seller_erp_bridge.py`。
- Source：`POST /v1/seller-erp-bridge/sources`，读文件前先解析 exact entity。
- Review：`POST /v1/seller-erp-bridge/reviews`。
- Binding：`POST /v1/seller-erp-bridge/bindings`。
- Revocation：`POST /v1/seller-erp-bridge/revocations`。
- Diff：`GET /v1/seller-erp-bridge/reconcile`。
- Web：`/seller-erp-bridge`，可从 `/commerce-os` 下钻。

Catalog 以 seller SKU + offer 为 key，Order 以 external order 为 key，
Inventory 以 seller SKU + warehouse + fulfillment mode 为 key。字段归一化、
Decimal/整数/币种/时间校验、服务端 counts、筛选、opaque cursor、Owner/SLA/
next、逐字段 Diff、snapshot/artifact hash 全部位于深模块；Router、Web 和 Agent
不重算。Agent artifact 仅允许建议/内部任务，固定
`formal_fact_promotion_allowed=false`、self-approval false、Permit false、
external write false。

## 5. 工程门

- 聚焦 deep module/API/OpenAPI：`49 passed`。
- CSV 与 XLSX、Catalog/Order/Inventory、三方独立性、幂等冲突、最新拒绝、
  revoke、坏 Evidence、secret column、duplicate key、cursor/hash replay、
  匿名/越权与 missing-entity-before-file-read 均有测试。
- 全量后端：使用工作区内全新隔离 `--basetemp` 重跑为 `865 passed`，
  9 个已知依赖弃用 warning；用户 Temp 目录 ACL 错误不作为通过证据。
- Secret scan：通过。
- `uv run ruff check .`：通过。
- Web `npm ci`：0 vulnerabilities。
- Web `npm test`：`77 passed`。
- Web `npm run build`：成功，42 个 route 含 `/seller-erp-bridge`。
- OpenAPI 0.59.0 包含 5 个 Seller ERP Bridge endpoint。
- `git diff --check`：退出 0，仅有工作树既有 LF/CRLF 提示。

## 6. PostgreSQL、迁移与真实运行

- 新 forward-only Alembic `20260729_0074` 只增加四个 Bridge Evidence
  source_ref partial unique index；未建立第二套业务表。
- 当前 PostgreSQL current/head 均为唯一 `20260729_0074`。
- 临时 PostgreSQL 空库从 0001→0074 成功；0074→0073→0074 回放成功；
  四个目标 index 均实际存在；临时数据库已删除。
- PostgreSQL、API、Web、media-worker 四容器均 healthy，且镜像由本切片源码
  重新构建。
- reconcile 匿名 401；认证 exact store 200；越权 store 403。
- 固定 `as_of=2026-07-29T00:00:00Z` 连续投影产生相同
  `snapshot_sha256`：
  `50ea1d4eea073b1ff32123e22e481da720f1d5bf89624451d45c78a1eb1a874d`。
- 同一输入 Agent artifact hash：
  `d43e0a49a8f290810ff169ece1447294404af94d3d027f6c6fc1f13b75b333ef`。
- 当前响应：`status=no_data`、`entity_ref=null`、全部 Diff counts 为 0、
  `scoped_input_read=false`、`formal_fact_promoted=false`、
  `private_interface_used=false`、`external_write_allowed=false`。
- PostgreSQL 实际计数：Bridge Evidence 0、native Order Facts 0、native
  Inventory Facts 0。

## 7. 浏览器实测

真实 Supabase operator session、运行容器和 PostgreSQL：

| Artifact | SHA-256 | 结果 |
|---|---|---|
| `output/playwright/bas146-seller-erp-bridge-desktop.png` | `db7a3ecb50ea874de0febb6cce6b8536785f799009f66ba570d990c2b03b64f0` | 1440px full-page，inner/client/scrollWidth = 1440/1440/1440 |
| `output/playwright/bas146-seller-erp-bridge-mobile-390.png` | `ae2847653e258f5fb3226a4b93e702af3b1c007766c93ad243b856e4866ed8ae` | 390px full-page，inner/client/scrollWidth = 390/390/390 |

桌面与 390px 均显示真实 `no_data`、0 matched/conflict/source-only/
canonical-only/source rows、三方权威链与全部 no-write 边界，0 console error。
`/commerce-os` 的“打开授权 Seller ERP Bridge”真实导航到
`/seller-erp-bridge`。

## 8. Graph 与仍未关闭 Gate

- `task-bas146-pytest/database/runtime/web/evidence` 由独立 verifier 记录为
  `passed/fresh`；canonical Graph 为 61 tasks、162 nodes、168 edges、
  至少 303 条 append-only observations。
- Graph passed 只证明工程合同、迁移、运行、浏览器与 Evidence，不会把
  `no_data` 晋升为第三方授权、商品/订单/库存覆盖或经营完成。
- 真实 entity、正式店小秘/平台导出或授权 Adapter、三个 SKU、Order、
  Inventory、Settlement 与 Cash Facts 仍未形成。
- 0.59 PM/RA Release Gates、Pilot Gate 与 Final Gate 均未通过。
- Ozon、Seller ERP、供应商、采购、付款、库存、履约、广告和客户消息 external
  write 继续关闭。
