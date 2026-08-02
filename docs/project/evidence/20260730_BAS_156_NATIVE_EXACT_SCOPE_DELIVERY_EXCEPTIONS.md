# BAS-156 native exact-scope delivery and exception authority

- Date: 2026-07-30
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Completion meaning: `contract/no_data` engineering completion
- Business state: `no_data`
- Authorized production carrier source bound: `false`
- External write: `false`
- Requirement: `BR-130`
- ADR: [ADR-0076](../../adr/ADR-0076-native-exact-scope-delivery-exception-authority.md)

## Implemented boundary

`ScopedDeliveryExceptionWorkspace.project(...)` is the only delivery and
exception composition seam. It admits exact tenant/entity/store/as-of
authority, then composes Native OMS Order, Inventory/Fulfillment,
Procurement/Receiving, Returns, Customer Service, the fifteen-leg profit impact
and formal carrier/platform Readback. It does not create another Order,
Inventory, Return, Shipment, Finance, Approval or Permit truth.

The server owns shipment/package/leg projection, carrier/service, chargeable
weight, quoted/actual fee authority, pick-pack/handover/transit/delivery/
exception/return timeline, SLA/Owner/next, compensation readiness, filters,
opaque cursor, counts, stable snapshot and Agent artifact. The client does not
recalculate them.

Canonical surfaces are `GET /v1/delivery-exceptions/workspace`,
`/delivery-exceptions` and the runtime OpenAPI snapshot. No new persistence was
needed: Alembic remains at the single 0079 head and neither 0042 nor 0079 was
modified for this read composition.

## Failure closure

Missing entity returns no-data before any upstream read. No formal OMS Order
short-circuits before Inventory, logistics templates, carrier Readback or other
upstream reads. Inventory or rate templates cannot become a Shipment.

Contract/scope/as-of/snapshot drift and bad/latest Evidence fail closed without
older-success fallback. The module validates Order/Product/SKU,
shipment/package/quantity/weight/currency/quote/actual fee, tracking/leg,
sequence/transition/time, Evidence/hash and Readback bindings. Duplicate
tracking or leg, conflicting replay, future/revoked Evidence and unknown outcome
cannot produce ready.

## Authorized read-only Readback contract

`AuthorizedDeliveryReadbackSource` is production-bindable only through an
injected read-only reader with:

- exact tenant/entity/store/as-of;
- official public API or authorized formal export identity and version;
- independent current authorization and Readback Evidence;
- immutable source payload hash and schema contract;
- revocation, timeout and explicit success/no-data/unknown outcome semantics;
- identical replay deduplication and conflicting replay rejection.

Tests cover timeout, schema drift, revocation, identical/idempotent replay,
conflicting duplicate replay and unknown outcome. Test fakes prove this
contract only; they do not prove a carrier or platform source exists.

The production composition root uses the disabled source. Consequently the
business-ready state remains gated and live runtime stays deterministic
`no_data`. A self-reported in-memory dictionary, private ERP endpoint, Cookie,
internal Token or CAPTCHA/access-control bypass cannot become authority.

## Agent and mutation boundary

Adversarial prompt injection, self approval, fake Permit, fictional authority
and carrier/customer-contact instructions cannot change the projection
permissions or invent facts. The Agent may suggest exception triage and an
internal task only.

Shipment creation/mutation, Order/Inventory/Return mutation, compensation or
claim creation, Approval, Permit, carrier/customer contact, delivery/signature
confirmation and every external write remain false.

## Current verification

- full backend command:
  `uv run pytest -q -p no:cacheprovider --basetemp .runtime/pytest-full-bas157-freeze`;
- full backend result: `979 passed`, `9 warnings`;
- combined BAS-154/155/156 completion-audit command: `86 passed`,
  `1 warning`;
- focused warehouse continuation: `4 passed`;
- Ruff: all checks passed;
- Web executable contracts: `107 passed`;
- Web production build: `52` routes;
- executable state model covers error→retry→success and distinct
  ready/no_data/blocked DOM;
- OpenAPI snapshot matches runtime;
- Alembic current/head: single `20260730_0079`;
- empty PostgreSQL replay: `base → 0079 → 0078 → 0079`;
- no 0080 was required;
- four containers rebuilt and healthy.
- `verify_secrets`: `970` non-ignored worktree files and `581` historical
  paths passed;
- `git diff --check`: passed, with line-ending notices only.

No full-suite count is inferred from an Evidence marker.

## Live runtime

The rebuilt live runtime returned:

- anonymous `401`;
- authorized exact store `200`;
- unauthorized store `403`;
- readiness `200`;
- deterministic replay `true`;
- status `no_data`;
- total `0`;
- upstream reads `[]`;
- snapshot SHA-256
  `3c2af0f4a59837cd17107647ef871a6f9f5df7749c3e093f7a39d55359dbc6c7`;
- `external_write_allowed=false`;
- `private_erp_interface_allowed=false`.

## Browser

The rebuilt production Web rendered the real server no-data response. Temporary
authentication state and browser session data were deleted.

- desktop inner/scroll width: `1440/1440`;
- mobile inner/scroll/client width: `390/390/390`;
- console errors: `0`;
- visual inspection: passed.

Screenshots:

- `output/playwright/bas156-delivery-exceptions-desktop.png`
  - SHA-256:
    `c40c58fd4efffae64b6b0907dde2603b7251c5e9232a7957e6c44acabb7c93e5`
- `output/playwright/bas156-delivery-exceptions-mobile-390.png`
  - SHA-256:
    `a56961513ab4cce0ec231e67b53fa33743eae5ec1388ec622ec6acda2652e4ab`

## Harness and Graph

`scripts/seed_bas156_agent_graph.py` executes the focused delivery/readback/API
tests, all executable Web tests, the single-head check, live runtime and
four-container probes, browser hashes and this Evidence hash. Five verifier
categories own the task chain; the Delivery Agent cannot certify itself.

After the chained BAS-154→155→156 hash-settlement materialization, the canonical
Graph contains `111 tasks / 233 nodes / 229 edges / 397 observations`; the
latest BAS-156 tests/database/runtime/web/evidence states are fresh `passed`.

`DONE_ENGINEERING` here means the exact-scope contract and honest
no-data behavior are complete. It does not claim a real Shipment, tracking leg,
carrier Readback, fee, delivery, claim, Order, Inventory, Return, Settlement,
Cash or Actual CM3.
