# BAS-096 已有 Ozon Listing 受控绑定验收

- 日期：2026-07-26
- Requirement：BR-071、BAS-096
- ADR：`docs/adr/ADR-0022-existing-marketplace-listing-binding.md`
- 实现分支：`feat/existing-listing-binding`

## 真实输入

本次只使用已经进入不可变 Marketplace Catalog 的 Ozon Seller 原始响应：

- 店铺作用域：`ozon-primary`
- Seller Offer ID：`2105343364UB`
- Marketplace SKU：`2216781923`
- Catalog Evidence：`evd_dc94091bb94d490ba8866caad7548415`
- Catalog item hash：`8631d985815528f7eec912dd73d48f40e2cd10bc6e472fba265a98c21f4fa55d`
- Catalog 观察时间：2026-07-24 13:26:19 UTC

目录商品标题仍含俄语机器翻译污染；目录媒体仍为
`unverified_external_reference`。本验收没有把这些事实提升为合规、素材权利或实际供应成本。

## 受控写入结果

通过正式
`POST /v1/marketplace-catalog/items/bind-existing`
提交当前 hash 与 `confirmed=true` 后：

- 创建 Canonical Product：`prd_2215304aca03f42ab0921102a2d58de9`
- Canonical SKU：`ozon:ozon-primary:2105343364UB`
- 市场/渠道/状态：`RU / OZON / active`
- 创建一条 `marketplace_product_bindings` 一对一身份映射
- PostgreSQL 触发器拒绝绑定表的 `UPDATE` 与 `DELETE`
- 创建一条 `product.existing_listing_growth_workspace_created` 事件
- 创建 `existing_listing_basis` Evidence 血缘
- 最新目录读取已投影 `canonical_product_id`
- 第二次相同 API 请求返回 `created=false`

数据库核对同时证明：

- `product.existing_listing_growth_workspace_created`：1 条
- `product.candidate_sourcing_workspace_created`：0 条
- `SKU-001 current`：0

因此已有 Listing 可以进入报价、Passport、CM3 和只读增长工作台，但没有被伪装成新候选。

预合并复核发现原始 Product SKU 只使用 `offer_id` 会在店群中冲突，因此最终合同改为
`ozon:{store_ref}:{offer_id}`。本地已创建的验收投影被精确更新，并追加
`product.identity_scope_corrected` 审计事件；尝试删除验收历史时，不可变账本触发器拒绝了整个事务，
没有任何 Ledger 记录被删除。单元测试另验证两个店铺使用相同 offer 文本时会获得两个不同 Product
ID 和两个店铺作用域 SKU。

## 外部动作边界

API 响应明确返回：

- `counts_as_new_candidate=false`
- `automatic_procurement=false`
- `automatic_listing=false`
- `automatic_marketplace_write=false`

本次没有修改 Ozon、发布 Listing、改价、创建广告、采购、联系供应商或创建订单。

## 前台验收

Playwright 在真实 Compose Web 上读取 `#growth`：

- `/auth/session`、目录、Product、readiness 等业务请求均为 HTTP 200
- 页面显示“已建立标准商品档案”
- 页面显示 Product ID `prd_2215304aca03f42ab0921102a2d58de9`
- 已绑定条目不再显示重复绑定按钮
- 浏览器控制台 0 error、0 warning

验收截图保存于本地忽略目录：
`output/playwright/BAS-096-existing-listing-bound.png`。

## 当前仍阻塞

- Product、Compliance、Quality 三本 Passport 仍缺失，`ready_for_validation=false`
- 正式供应商报价仍为 0；必须取得三家独立、当前有效且已复核的精确报价
- 还没有最终物流账单、十五项成本、CM3 场景、真实转化率和同行同款证据
- `SKU-000` 至 `SKU-003` 当前均为 `needs_input`
- 广告、改价、采购、发布和 Ozon 写入仍不能执行

这是真实业务链路被打开，但不是把缺失业务事实自动判定为完成。

## 工程验收

```text
uv run python scripts/verify_secrets.py
Secret verification passed

uv run python scripts/validate_write_paths.py
Write-path registry and source boundaries are valid

uv run ruff check .
All checks passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-existing-listing-final-2
457 passed

cd web
npm ci
npm test
33 passed
npm run build
Compiled successfully；TypeScript 与 13 个页面生成通过

uv run alembic heads
20260726_0048 (head)

全新临时 PostgreSQL 从空库迁移至 20260726_0048，并确认
trg_marketplace_product_bindings_immutable 存在；临时库随后已删除。

当前 PostgreSQL /health/ready
status=ok，database.status=ok
```

## 复核结论

- P0/P1：无未处理工程发现。
- auto-fix：补齐店群作用域 Canonical SKU、绑定表数据库不可变触发器，以及跨适配器失败时
  `paused → active` 的 fail-closed 恢复语义。
- Info/defer：真实 Passport、三家确认报价、最终物流/费用、CM3、转化和同行证据仍由业务输入阻塞；
  不以工程测试替代这些事实。
