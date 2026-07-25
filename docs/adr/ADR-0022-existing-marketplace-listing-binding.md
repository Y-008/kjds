# ADR-0022：已有 Marketplace Listing 与 Canonical Product 的受控绑定

- 状态：Accepted
- 日期：2026-07-26
- Owner：商品负责人、供应链负责人
- 影响范围：已有 Ozon 商品增长、供应商报价、Passport、CM3

## 背景

KJDS 已能把真实 Ozon Seller API 商品响应导入 `MarketplaceCatalogWorkspace`，但目录条目的
`canonical_product_id` 为空，正式 `products`、`source_offers` 和 `profit_scenarios` 仍为零。
因此真实在售商品只能展示，不能进入供应链成本、Passport、内容和增长闭环。

候选上新路径不能直接复用：已有 Listing 并不是经过需求研究筛出的新候选，把它伪装成
`product.candidate_sourcing_workspace_created` 会污染 `SKU-001` 三候选 readiness。

## 决策

新增已有 Listing 受控绑定：

1. 绑定只接受最新、完整性通过的 Ozon Catalog Evidence，并使用 `store_ref + offer_id` 定位。
2. 客户端必须提交当前 `item_hash` 和显式 `confirmed=true`；目录更新后旧页面不能静默绑定。
   已绑定 Listing 在后续目录快照上重放时仍复验当前 Evidence/hash，但保持最初绑定的
   `source_evidence_id` 与 `item_hash`，不改写原始身份依据。
3. 服务端以 `marketplace + store_ref + offer_id` 生成稳定 Product ID，并以
   `ozon:{store_ref}:{offer_id}` 作为店群安全的 Canonical SKU；卖家 `offer_id` 与 Marketplace
   SKU 继续保存在绑定表，名称来自不可变目录快照。
4. 绑定写入独立身份映射表，并生成
   `product.existing_listing_growth_workspace_created` 内部事件与 `existing_listing_basis` 血缘。
5. 绑定后的 Product 状态为 `active`，但不产生候选交接事件、不计入 `SKU-001`、不满足新上新 G0。
6. 已有 Listing 可以进入供应商确认报价、Passport、CM3 和增长诊断；仍需各自的证据与审批。
7. Catalog 媒体继续为 `unverified_external_reference`，绑定不授予素材权利。
8. 绑定不修改 Ozon，不创建 Listing、不采购、不投广告、不联系供应商。

## 数据模型

`marketplace_product_bindings` 保存一个外部 Listing 身份到一个 Canonical Product 的不可变映射：

- `(marketplace, store_ref, offer_id)` 唯一；
- `product_id` 唯一；
- 固化 `marketplace_sku`、`item_hash`、`source_evidence_id`、绑定人和时间。

目录快照仍不可变；读取最新目录时投影绑定结果，不覆盖历史快照。
Product 与绑定跨两个持久化适配器时采用 fail-closed 恢复语义：Product 先以 `paused` 创建，只有绑定
成功后才切换为 `active`；中途失败不会产生已有 Listing 交接事件，使用相同稳定身份重试可恢复。

## 被否决方案

- 把已有 Listing 伪装成新候选：会错误解除 `SKU-001`。
- 仅更新每个快照的 `canonical_product_id`：后续快照会再次断链，且需要覆盖历史读模型。
- 用商品标题或 Marketplace SKU 猜 Product：标题可变，Marketplace SKU 与卖家 offer ID 语义不同。
- 直接把 `offer_id` 当全局 SKU：同一 offer 文本可在两个店铺出现，会破坏店群隔离。
- 自动绑定全部目录：缺少逐商品确认，可能把测试、重复或错误店铺商品建成正式 Product。

## 复核

当支持第二 Marketplace 或多法人店群时，复核 SKU 作用域与 Product 唯一性。最迟于 2026-10-26
复核本 ADR。
