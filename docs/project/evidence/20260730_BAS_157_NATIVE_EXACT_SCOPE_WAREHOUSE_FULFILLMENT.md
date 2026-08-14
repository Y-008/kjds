# BAS-157 native exact-scope warehouse fulfillment authority

- Date: 2026-07-30
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Completion meaning: `contract/no_data` engineering completion
- Business state: `no_data`
- Real Order / Inventory / warehouse execution event: `0 / 0 / 0`
- Authorized production warehouse source bound: `false`
- External write: `false`
- Requirement: `BR-131`
- ADR: [ADR-0077](../../adr/ADR-0077-native-exact-scope-warehouse-fulfillment-authority.md)

## Implemented boundary

`ScopedWarehouseFulfillmentWorkspace.project(...)` is the single warehouse
composition seam. It admits exact tenant/entity/store/warehouse/order/as-of
authority, then composes the existing Canonical Product/SKU, Native OMS Order,
Inventory/Fulfillment, Procurement/Receiving, BAS-156 Delivery, Evidence,
Rule/OperationsQueue and Approval/Permit authorities. It does not create a
second Product, SKU, Order, Inventory, Shipment, Return, Finance, Approval or
Permit truth.

Forward-only 0080 introduces only the append-only
`warehouse_execution_events` observation authority. PostgreSQL rejects UPDATE
and DELETE and enforces exact source/aggregate sequence plus one-time
Permit/Readback uniqueness. Neither 0042 nor 0079 was modified.

The server owns location/bin/lot/reservation/wave/pick/pack/parcel, scan and
measured-weight authority, carrier handoff state, counts, filters, opaque
cursor, stable snapshot and versioned Agent artifact. The client renders one
projection and does not recalculate quantities, states, readiness or
permissions.

Canonical surfaces are:

- `GET /v1/warehouse-fulfillment/workspace`;
- `POST /v1/warehouse-fulfillment/events`;
- `/warehouse-fulfillment`;
- the runtime OpenAPI snapshot.

## Failure closure

Missing entity returns `no_data` before any raw or upstream read. No formal OMS
Order short-circuits before PIM, Inventory, Procurement, Delivery or warehouse
event reads. Inventory or logistics templates cannot become a wave, parcel or
handoff fact.

Current Evidence, exact scope, contract/schema, as-of and immutable payload
hash are revalidated at projection time. Latest bad authority fails closed
without older-success fallback. Tests cover cross-scope/snapshot drift,
canonical PIM empty, negative inventory, duplicate or excess reservation,
lot/bin drift, pick/reservation and pick-pack quantity conservation, unknown
weight source, out-of-order or duplicate scan, label/order conflict, duplicate
Permit/receipt and formal Delivery handoff binding.

Only `official_public_api`, `authorized_formal_export` and
`authorized_warehouse_system` sources are admissible. Private ERP endpoints,
Cookies, internal Tokens, CAPTCHA/access-control bypass and fictional authority
are rejected.

## Independent high-risk chain

Inventory adjustment, outbound confirmation, label purchase and carrier
handoff are L4 `policy_only` actions. The Write Path Registry has no request
entry, service entry, external call, executor or formal business write for
them.

A governed successful Readback observation must bind:

- an approved database Approval whose requester and decider differ and whose
  payload binds exact scope, Order, event and source;
- current versioned `kjds-warehouse-one-time-permit-v1` Evidence with
  `single_use=true`, issued/expiry bounds and no revocation;
- independent `kjds-warehouse-execution-readback-v1` Evidence with
  `outcome=succeeded`, `mutation_applied=true`, authorized Adapter identity,
  remote operation identity and resulting-state SHA-256;
- exact-scope Kill Switch release and Compensation Evidence bound to the same
  Approval, Permit, Readback, Order and source event.

Self approval, expired/revoked Permit, uncertain outcome, fictional Adapter,
binding drift and Permit/receipt reuse fail closed.

## Agent and mutation boundary

Adversarial prompt injection, self approval, fake Permit, fictional authority,
inventory or shipment mutation and carrier/customer-contact instructions cannot
change permissions or invent facts. The Agent may suggest a wave or exception
classification and create an internal task only.

Inventory adjustment, outbound confirmation, label purchase, carrier handoff,
Order/Inventory/Shipment/Return mutation, Approval, Permit, carrier/customer
contact, private ERP access and every external write remain false.

## Current verification

- full backend:
  `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-full-bas157-rerun`;
- full backend result: `1007 passed`, `9 warnings`;
- focused warehouse authority/workspace/API: `32 passed`, `1 warning`;
- Ruff: all checks passed;
- `verify_secrets`: `987` non-ignored worktree files and `581` historical
  paths passed;
- `git diff --check`: passed, with line-ending notices only;
- Web clean install: `npm ci`, `0 vulnerabilities`;
- Web executable tests: `111 passed`;
- Web production build: `53` routes including `/warehouse-fulfillment`;
- OpenAPI snapshot matches runtime;
- Alembic current/head: single `20260730_0080`;
- empty PostgreSQL replay:
  `base → 0080 → 0079 → 0080`;
- actual PostgreSQL 0080 downgrade/re-upgrade: passed;
- four rebuilt containers: healthy.

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
- snapshot SHA-256:
  `14d1c89ee03591e4c2b893511eb0a601db0f0507b4cc09b8b45f8b92160cc97a`;
- `external_write_allowed=false`;
- `private_erp_interface_allowed=false`.

No real Product/Order/Inventory/Shipment/Warehouse Event is inferred from this
contract/no-data result.

## Browser

The rebuilt production Web rendered the real server `no_data` response with
total `0`. The page exposed ready/no_data/blocked/error/retry through executable
state-model and component tests. Temporary Supabase browser authentication
state was deleted after capture.

- desktop inner/scroll width: `1440/1440`;
- mobile inner/scroll width: `390/390`;
- console errors: `0`;
- desktop/mobile visual inspection: passed.

Screenshots:

- `output/playwright/bas157-warehouse-fulfillment-desktop.png`;
  - SHA-256:
    `bae4ab65bff99c5027634d2c8e42891490cbc86991378430c38962cf24bd2734`;
- `output/playwright/bas157-warehouse-fulfillment-mobile-390.png`.
  - SHA-256:
    `4e56a98d3c4d7f7f14c93cce058f3fb5e5e1596ece811f5b266761f38dd94a4a`.

## Harness and Graph

`scripts/seed_bas157_agent_graph.py` executes focused authority/workspace/API
tests, the PostgreSQL migration replay, single-head check, live runtime,
four-container health probe, all executable Web tests, browser hashes and this
Evidence hash. Five external verifier categories own the chain; the Warehouse
Agent cannot certify itself.

After materialization, the canonical Graph contains
`116 tasks / 242 nodes / 237 edges / 404 observations`. The latest BAS-157
tests/database/runtime/web/evidence observations are all fresh `passed` through
2026-08-06. The evidence verifier records this file's current SHA-256 rather
than accepting a status marker as proof.

`DONE_ENGINEERING` means the exact-scope contract, append-only authority and
honest no-data boundary are complete. It does not claim a real Order,
Inventory, reservation, wave, pick, pack, parcel, measured weight, label,
handoff, Shipment, Settlement, Cash or Actual CM3, and it does not complete the
global 0.59→M4 goal.
