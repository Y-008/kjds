# BAS-071 开源 ERP / Commerce 内核研究证据

## 结论

以 2026-07-20 可访问的官方仓库和文档为依据，ERPNext 是 KJDS 标准交易内核的首选隔离 PoC；它不自动安装、不进入生产，也不改变当前事实 Owner。Odoo Community 和 Dolibarr 保留为 ERP 备选；Medusa、Saleor、Vendure属于未来自有商城内核候选。

## 原始来源

- https://github.com/frappe/erpnext
- https://docs.frappe.io/framework/user/en/api/rest
- https://docs.frappe.io/framework/v14/user/en/guides/integration/webhooks
- https://docs.frappe.io/erpnext/multi-currency-accounting
- https://docs.frappe.io/erpnext/accounting-of-inventory-stock
- https://github.com/odoo/odoo
- https://github.com/Dolibarr/dolibarr
- https://github.com/medusajs/medusa
- https://github.com/saleor/saleor
- https://github.com/vendurehq/vendure

## 可复验产物

- `docs/project/12_OPEN_SOURCE_ERP_AND_COMMERCE_KERNEL_DECISION.md`
- `docs/project/registries/open_source_commerce_kernels.json`
- `docs/project/05_BUILD_BUY_REUSE.md`
- `docs/project/04_SOURCE_DECISION_UNKNOWN_REGISTER.md` 的 `SRC-016` 与 `DEC-025`

## 边界

本轮只确认公开能力、许可证与架构适配假设。没有启动容器、导入业务数据、授权 Ozon、创建 ERP 单据或证明本地税务口径。所有候选保持 `requires_review: true`；只有隔离 PoC 的七项硬门全部通过，才能提出 Owner 迁移 ADR。
