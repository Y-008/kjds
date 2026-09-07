# Ozon browser observation current state

**Checked:** 2026-09-07

The existing logged-in Chrome session was read through CDP on `127.0.0.1:9225` without restarting or closing the browser. The seller page was `https://seller.ozon.ru/app/products` for store `BEIJIXINGYOUXUAN` and showed 17 items, all in the selling state.

The complete visible DOM capture is stored at `output/playwright/ozon-products-evidence.json` with SHA-256 `7bc71947f9d786d0b8e4982c7ca0b4d39a2d61e7f136e3d8d406e6e87dc943ed`. The capture is C-grade browser evidence. Prices retain the page's `¥` display symbol; the finance page in the same session showed the account balance in `₽`, and its visible text is preserved at `output/playwright/ozon-finance-visible.txt`. The account settlement currency is recorded as RUB while the raw product symbol is preserved.

The local control plane was started and database migrations through `20260907_0120` were applied. `/version` returned service `kjds-control-plane`, version `0.59.0`, schema `v1`; `/health/ready` returned HTTP 200. The 17-item envelope was admitted to the browser capture inbox as `bci_dd8ddcde1b2b44c7bb6268a46a40bbeb` with status `pending_independent_binding`. Its evidence scope was then bound through the independent chain: submission `evd_50fd54f2da9e41c7a785af8c0a81f4e0`, owner review `evd_a5b6ec35efeb4ad0889ce0df7c5313f3`, and compliance binding `evd_944e05fc6bd34c66ae56dd65e2ecf425`. The inbox projection now reports `promotion_readiness=ready`.

This browser observation does not establish official Seller API readback or production acceptance. The inbox submission is internal C-grade evidence only; it has not created a formal marketplace observation, approval, permit, listing, or external write. The latest official origin gate remains blocked by HTTP 403/antibot, and no Ozon external write was performed.

The automatically generated next-action queue is `output/playwright/ozon-next-action-queue.json`. It prioritizes content review for low content scores and replenishment review for low visible own-warehouse stock. Price, inventory, and listing writes remain gated by exact command scope, managed lease, Permit, economic guard, external readback, and rollback.

The current cross-system acceptance snapshot is `output/playwright/ozon-production-acceptance-snapshot.json`. At capture time the exact scope grant was ready and the browser evidence projection was ready, while the official production gate remained blocked because the managed runtime identity configuration, official Ozon readback, RealFBS confirmation, and bank evidence were not all available.

The snapshot also records seven historical managed leases for this scope and zero current unrevoked, unexpired leases. The latest historical lease expired on 2026-08-07, so it is not valid production evidence.

The live project graph `kjds-059-bas123` was queried with the exact store scope. Its frontier summary is preserved at `output/playwright/ozon-project-graph-frontier-summary.json`: status `BLOCKED`, 238 frontier nodes, 611 blockers, and state counts of 354 `STALE`, 33 `NO_DATA`, and 13 `BLOCKED`. The next safe action is monitor-owned refresh of stale observations; no external dispatch is permitted from this snapshot.
