# Ozon browser observation current state

**Checked:** 2026-09-07

The existing logged-in Chrome session was read through CDP on `127.0.0.1:9225` without restarting or closing the browser. The seller page was `https://seller.ozon.ru/app/products` for store `BEIJIXINGYOUXUAN` and showed 17 items, all in the selling state.

The complete visible DOM capture is stored at `output/playwright/ozon-products-evidence.json` with SHA-256 `7bc71947f9d786d0b8e4982c7ca0b4d39a2d61e7f136e3d8d406e6e87dc943ed`. The capture is C-grade browser evidence. Prices retain the page's `¥` display symbol; the currency code is unresolved and must not be inferred.

The local control plane was started and database migrations through `20260907_0120` were applied. `/version` returned service `kjds-control-plane`, version `0.59.0`, schema `v1`; `/health/ready` returned HTTP 200. The browser capture inbox is therefore available for a future submission after the currency and exact evidence contract are resolved.

This browser observation does not establish official Seller API readback or production acceptance. The latest official origin gate remains blocked by HTTP 403/antibot, and no Ozon external write was performed.

The automatically generated next-action queue is `output/playwright/ozon-next-action-queue.json`. It prioritizes content review for low content scores and replenishment review for low visible own-warehouse stock. Price, inventory, and listing writes remain gated by exact command scope, managed lease, Permit, economic guard, external readback, and rollback.
