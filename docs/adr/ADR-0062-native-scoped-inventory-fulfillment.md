# ADR-0062: Native scoped inventory and fulfillment coverage

- Status: Accepted for BAS-142 implementation
- Date: 2026-07-29
- Owners: Inventory, OMS, Fulfillment, Evidence and Agent Operations
- Requirements: BR-084, BR-093–096, BR-101, BR-115, BR-116
- Depends on: ADR-0037, ADR-0047, ADR-0049, ADR-0061

## Context

Maozi's public Feishu workflow exposes single/bulk inventory operations. The
read-only local sample `D:\KJDS\ozon\荔枝OZON助手` also shows a desktop
application with local category/fee files, SQLite/Excel/image libraries and a
bundled 1688 browser extension. That extension requests cookies, all-page
content injection and broad host access. These are useful C-tier workflow and
implementation observations, but none is KJDS inventory truth or acceptable
credential architecture.

KJDS already has exact-scope formal Fact promotion and a native OMS timeline.
It lacks a canonical inventory snapshot and cannot yet distinguish “official
stock covers current open orders” from “a listing page showed something”.

## Decision

Add `ozon_inventory` to the existing versioned Ozon Fact contract. An
inventory row is one immutable snapshot with:

- explicit external snapshot ID and exact Product/SKU binding;
- warehouse, optional cluster and China Global fulfillment mode (`FBP` or
  `realFBS`);
- non-negative available, reserved, in-transit, damaged and quarantine
  quantities;
- explicit effective time and immutable source Evidence.

The canonical current-fact cell key is `(SKU, warehouse, fulfillment mode,
cluster)`. Repeated snapshots append history. If the latest candidate fails
contract, Evidence, hash, scope, Product/SKU or key validation, the cell is
blocked and an older valid snapshot is not reused as current.

Add one read-only `ScopedInventoryFulfillmentWorkspace`. It reads only formal
Facts under exact tenant/entity/store/grant and composes the same-as-of Native
OMS projection. It aggregates official available stock and explicit open order
demand server-side. OMS `no_data` never becomes zero demand; coverage remains
blocked/no_data until order authority exists.

The Agent receives only the frozen workspace snapshot and can produce an
internal Owner/SLA/next artifact. It cannot change stock, reserve units, create
fulfillment commands, buy from suppliers, pay, approve itself, issue a Permit
or call Ozon writes.

## Return compatibility

`order_external_id` becomes an optional normalized return-import field so old
files remain import-compatible. Native OMS still requires the explicit link to
use a return in current state; absence remains a fail-closed blocker.

## Data access and benchmark boundary

- Primary data: official Seller API, official exports or an admitted
  authorized connector with immutable Evidence.
- Marketplace pages, Maozi and the local Lizhi sample never provide actual
  stock, actual fees or authorization facts.
- No Cookie/localStorage transfer, internal Ozon API, CAPTCHA bypass,
  `<all_urls>` runtime or bundled unsigned extension becomes a KJDS dependency.
- Static `fee.txt` observations remain C-tier historical implementation
  evidence and cannot enter the Fee/Profit Kernel.

## Compatibility and migration

- Existing `ozon-v1` facts remain readable; the new record type is additive.
- Migration 0073 adds a partial exact-scope inventory lookup index only; it
  does not rewrite 0072 or earlier applied revisions.
- Downgrade removes only the 0073 index. Fact rows and Evidence remain intact.
- The API is authenticated `GET /v1/inventory/workspace`; anonymous access is
  401 and cross-store access is 403.

## Verification

BAS-142 covers record detection, import aliases, FBP/realFBS normalization,
non-negative quantities, exact scoped formal promotion, cross-tenant
isolation, as-of determinism, opaque pagination, latest-invalid fail-closed,
OMS demand coverage/shortage, no-data demand, bad Evidence, anonymous 401,
cross-store 403, zero read side effects, migration replay, desktop/390 Web and
all external-write flags false.

## Review trigger

Revisit only when Ozon Global CN publishes a materially different inventory
object, KJDS admits a second platform, or a governed stock-write command is
proposed. Any stock write requires a separate ADR and execution gate.
