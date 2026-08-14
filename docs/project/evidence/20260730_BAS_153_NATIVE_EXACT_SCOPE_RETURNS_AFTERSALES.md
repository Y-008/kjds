# BAS-153 native exact-scope returns and after-sales control

- Date: 2026-07-30
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Business state: `no_data`
- External write: `false`
- Requirement: `BR-127`
- ADR: [ADR-0073](../../adr/ADR-0073-native-exact-scope-returns-aftersales-control.md)

## Implemented boundary

`ScopedReturnsAfterSalesWorkspace.project(...)` is the only Return/Finance
composition seam. It reads Native OMS first and reads Finance Control only
when a real accepted Return exists. It does not create another Order, Return,
Product, FinanceEntry, Reconciliation, refund, service case or message truth.

Canonical surfaces:

- `GET /v1/returns/workspace`;
- `/returns`.

The server owns Return/order quantity conservation, duplicate detection,
Product/SKU/order/currency binding, stage, Finance-cycle binding, filters,
opaque cursor, counts, Owner/SLA/next, artifact and snapshot hashes.

## Failure closure and gated authority

Tests prove:

- missing entity performs zero OMS and Finance reads;
- OMS without a real Return short-circuits before Finance;
- bad OMS snapshot fails before Finance;
- bad Finance snapshot withholds all affected business values;
- duplicate/over-return, scope, contract, as-of and pagination drift fail
  closed;
- repeated fixed input produces the same snapshot;
- cross-store access is rejected.

No customer-service case/message, platform dispute or RMA authority currently
exists. Runtime therefore reports all four as `false` with `status=gated`.
Agent suggestions remain internal and cannot self-approve, issue Permit,
create a refund/message/dispute or write externally.

Private Seller ERP endpoints, Cookies, internal Tokens and CAPTCHA bypass
remain prohibited. KJDS authorization cannot confer third-party permission.

## Verification

- focused backend API/module: `52 passed`;
- full backend: `934 passed`, `9 warnings`;
- Ruff: all checks passed;
- `verify_secrets`: `921` non-ignored worktree files and `581` historical
  paths passed;
- `git diff --check`: passed (line-ending notices only);
- Web contracts: `99 passed`;
- Web production build: `49` routes;
- OpenAPI snapshot matches runtime;
- Alembic current/head: single `20260730_0078`;
- no migration was created because this is a pure read composition;
- PostgreSQL, API, Web and media-worker: healthy.

One pre-existing test used a runtime-created FinanceEntry with an as-of fixed
to the beginning of the same UTC day. When UTC crossed that instant, correct
as-of filtering excluded the row. The test cutoff now deterministically
covers the write; the production filter was not weakened.

## Live runtime

Authenticated runtime verification returned:

- anonymous `401`;
- authorized exact store `200`;
- unauthorized store `403`;
- entity `null`;
- status `no_data`;
- returns `0`;
- `scoped_input_read=false`;
- `refund_created=false`;
- `customer_message_sent=false`;
- `external_write_allowed=false`;
- `private_erp_interface_allowed=false`.

This is not a real Return/refund closed loop and is not Actual Cash CM3.

## Browser

The real application bundle rendered the authenticated live no-data response.
The existing global Agent status rail was also supplied from its authenticated
live endpoint. No credential was persisted.

- desktop `inner/scrollWidth = 1440/1440`;
- mobile `inner/scrollWidth = 390/390`;
- console errors `0`;
- page errors `0`.

Screenshots:

- `output/playwright/bas153-returns-desktop.png`
  - SHA-256:
    `8291fcf6a43cf2ac277783467802f0065645fc4ca2e31faee95fb7a89208b870`
- `output/playwright/bas153-returns-mobile-390.png`
  - SHA-256:
    `95eee28a3e435a22736edd5b87ea95eea553a2c5cbfcaaa0a05763e83a9f6ebb`

## Harness and Graph

`scripts/seed_bas153_agent_graph.py` independently reruns focused tests,
checks the single 0078 PostgreSQL authority with no BAS-153 schema change,
probes authenticated runtime, verifies both browser Evidence hashes and then
records the immutable Evidence hash.

The first BAS-153 materialization produced:

- tasks: `96`;
- nodes: `211`;
- edges: `210`;
- observations: `344`;
- latest tests/database/runtime/web/evidence states: fresh `passed`.

Only the five registered external verifiers can advance the BAS-153 task
chain. The workspace Agent cannot certify its own implementation.

`DONE_ENGINEERING` does not mean that a real Return, refund, customer case,
message, dispute, bank Readback or Actual Cash CM3 exists. Real business state
remains `no_data`, and all external writes remain disabled.
