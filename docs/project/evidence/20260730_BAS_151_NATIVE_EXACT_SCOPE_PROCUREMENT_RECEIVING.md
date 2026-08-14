# BAS-151 native exact-scope procurement and receiving control

- Date: 2026-07-30
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Business state: `no_data`
- External write: `false`
- Requirement: `BR-125`
- ADR: [ADR-0071](../../adr/ADR-0071-native-exact-scope-procurement-receiving-control.md)

## Outcome

BAS-151 adds one native deep read module:

`ScopedProcurementReceivingWorkspace.project(...)`.

It projects the existing Sample Purchase Order and append-only procurement
events through exact tenant/entity/store/grant/as-of authority. It reuses the
Canonical Product, Supplier Offer, Profit Scenario, independent procurement
Approval and scoped Evidence services. It does not create a second Product,
Supplier, Offer, Scenario, Approval, purchase-order, receipt or payment truth.

Canonical HTTP surface:

- `GET /v1/procurement/workspace`.

Canonical Web surface:

- `/procurement`.

Router, React and Agent prompts do not calculate the order value, current
stage, event validity, receipt quantities or inspection conservation.

## Native procurement authority

Forward-only migration `20260729_0077` adds complete-or-empty:

- tenant;
- entity;
- store;
- ScopeGrant authority SHA-256;
- source Evidence SHA-256;
- scope as-of;

to the existing `sample_purchase_orders` and
`sample_procurement_events`. A scoped purchase order additionally references
one immutable authority Evidence record.

Historical rows remain all-null legacy rows. They are not guessed into an
entity or admitted by the native projection.

The live database and Alembic script each expose one head:

`20260729_0077`.

A temporary PostgreSQL database passed:

- empty replay from 0001 to 0077;
- downgrade from 0077 to 0076;
- forward replay from 0076 to 0077;
- deletion after verification.

Live PostgreSQL inspection confirms:

- `ck_sample_purchase_orders_scope_complete`;
- `ck_sample_procurement_events_scope_complete`;
- `ix_sample_order_scope_created`;
- `ix_sample_order_scope_product`;
- `ix_sample_event_scope_timeline`.

Database model tests reject partially scoped order and event rows.

## Deep-module boundary

### Scope before any raw read

The projection validates authenticated Principal, authorized store, current
entity authority, authority hash and timezone-aware cutoff before reading
procurement sources or Product rows.

Missing entity authority returns `no_data` with:

- zero procurement source reads;
- zero Product raw reads;
- `scoped_input_read=false`.

Malformed ready authority and unauthorized store fail closed. Exact SQL
predicates include tenant, entity, store, ScopeGrant authority and as-of.
Legacy and cross-scope rows never enter the result.

### Exact decision basis

Every admitted purchase order is bound to:

- one exact Canonical Product and SKU;
- one Supplier Offer;
- one complete positive-CM3 Profit Scenario;
- one approved `procurement.place_order` decision for that Scenario;
- a matching Product/Offer/Scenario/quantity payload;
- a different requester and approver;
- current exact-scope authority Evidence.

Offer and Scenario timestamps must precede the cutoff. Every Scenario and
cost Evidence reference must be current, content-valid and exact-scope.
Missing or conflicting authority excludes the order and withholds its
identity and monetary values.

### Deterministic receiving timeline

The server validates the existing state machine:

`approved_to_order → order_confirmed → shipped → received → inspected`

and the existing golden-sample approval, rejection, rework and cancellation
branches.

Every event requires:

- a contiguous unique sequence;
- a legal transition from the current state;
- required structured facts;
- effective, recorded and scope timestamps at or before the cutoff;
- immutable Evidence content matching the stored source hash;
- exact-scope Evidence authority;
- no duplicate event/Evidence authority.

Receipt quantity cannot exceed ordered quantity, damaged quantity cannot
exceed received quantity, inspected quantity cannot exceed received
quantity, and passed plus defects must equal inspected. A bad latest event
fails the whole order closed; no older successful stage is substituted.

The service returns server-owned:

- stage and next events;
- Product/SKU and supplier;
- quantity, unit price, currency and order value;
- receipt, damage and inspection facts;
- decision basis;
- Owner, SLA and next workspace;
- counts, filters and opaque cursor;
- versioned Agent artifact and stable snapshot hash.

## AP and payment boundary

KJDS currently has no authoritative supplier invoice, payable or supplier
payment object. BAS-151 therefore exposes:

- `accounts_payable_invoice_authority_available=false`;
- `supplier_payment_authority_available=false`;
- `invoice_or_payment_claim_allowed=false`;
- status `gated`.

It does not call the current surface Purchase-to-Pay. A separate later slice
must establish invoice, payable, payment, independent Approval, one-time
Permit, bank Readback and compensation authority.

## Failure and no-write policy

Affected business values are withheld on:

- missing or malformed entity authority;
- cross-scope, future or truncated sources;
- damaged, revoked or hash-drifted Evidence;
- missing or conflicting exact Product;
- Offer, Scenario, Approval or quantity binding drift;
- self-approved or non-approved procurement decision;
- incomplete, unknown-cost or non-positive-CM3 Scenario;
- event sequence, transition, facts, time or authority drift;
- duplicate event authority;
- receipt or inspection quantity non-conservation.

Excluded results expose reason counts only:

`business_values_exposed=false`.

The versioned `kjds-procurement-steward-artifact-v1` may only recommend
internal tasks. Runtime output proves all writes remain false for:

- Product;
- Offer and Scenario;
- supplier contact;
- purchase order;
- receipt and inspection;
- Approval and Permit;
- Inventory;
- invoice and payable;
- supplier payment;
- refund and dispute;
- external systems.

Private Seller ERP endpoints, Cookies, internal Tokens and CAPTCHA bypass
remain prohibited. KJDS authorization cannot create third-party permission.
Official APIs, formal exports and explicitly authorized adapters remain the
only Seller ERP bridge paths.

## Backend and repository verification

Focused tests cover:

- missing entity with zero raw reads;
- exact Product and scoped procurement SQL isolation;
- deterministic stage, order value and snapshot;
- independent exact Approval/Offer/Scenario binding;
- bad latest event Evidence without fallback;
- receipt and inspection quantity conservation;
- stable server cursor and filters;
- cross-store rejection before raw reads;
- AP/payment gated and all writes false;
- database rejection of partial scope;
- anonymous 401 and unauthorized store 403;
- API/OpenAPI compatibility.

Results:

- focused backend: `55 passed`;
- full backend: `915 passed`, `9 warnings`;
- Ruff: all checks passed;
- OpenAPI snapshot matches runtime;
- `verify_secrets`: passed across `899` non-ignored worktree files and `581`
  historical paths;
- `git diff --check`: passed;
- `npm ci`: passed with `0` vulnerabilities;
- Web contract tests: `93 passed`;
- Web production build: `47` routes.

## PostgreSQL and real runtime

Live native rows:

- scoped Sample Purchase Order: `0`;
- scoped Procurement Event: `0`;
- AP Invoice authority: `0 / not implemented`;
- supplier Payment authority: `0 / not implemented`.

PostgreSQL, API, Web and media-worker are all `healthy`.

Live API behavior:

- readiness: `200`;
- anonymous procurement workspace: `401`;
- configured operator and exact store: `200`;
- unauthorized store: `403`;
- entity: `null`;
- status: `no_data`;
- orders and all stage counts: `0`;
- `scoped_input_read=false`;
- AP invoice authority: `false`;
- supplier payment authority: `false`;
- `external_write_allowed=false`.

Repeated fixed-input reads produce the same snapshot hash and do not create
Product, purchase order, event, Approval, Permit, invoice, payment or
OperatingTask.

## Web and browser

`/procurement` renders:

- loading and retryable error;
- ready/no_data/partial/blocked states;
- exact scope, source gaps and server counts;
- server-side query, stage filter and opaque cursor;
- Product/SKU, supplier and server order value;
- ordered event and Evidence timeline;
- receipt, damage and inspection quantities;
- decision basis, Owner, SLA and next action;
- explicit AP/payment gate;
- immutable Agent and external-write boundaries.

Commerce OS, Sourcing Intelligence, OMS and Inventory link to the same native
procurement workbench.

Browser QA used an authenticated live API response frozen in memory and the
real application bundle. It did not persist a credential or claim a new
Supabase session. The visible global rail truthfully reports its independent
Graph verifier state.

- desktop: `inner/scrollWidth = 1440/1440`;
- mobile: `inner/scrollWidth = 390/390`;
- console errors: `0`;
- page errors: `0`;
- visible business state: `no_data`.

Screenshots:

- `output/playwright/bas151-procurement-desktop.png`
  - SHA-256:
    `fbb9c1b1c5f6715623a05bbb1e50c9dc09adfe7800a2db9fb3fcbdb6b77bea56`
- `output/playwright/bas151-procurement-mobile-390.png`
  - SHA-256:
    `9f04f4360cb0e9aa6518805c538d9b66dc1447f81e8b9a864535bb3cad765e7d`

## Harness and Graph

`scripts/seed_bas151_agent_graph.py` independently reruns and records:

- focused pytest;
- PostgreSQL and Alembic authority;
- authenticated Docker/API runtime;
- desktop and 390px browser Evidence;
- immutable BAS-151 Evidence.

Canonical Graph after BAS-151:

- tasks: `86`;
- nodes: `197`;
- edges: `198`;
- observations: at least `331`;
- latest BAS-151 tests/database/runtime/web/evidence observations:
  `passed` and fresh.

Task state can advance only from the five registered external verifiers.
Neither the workspace Agent artifact nor the implementation process can
self-certify a task.

## Completion classification

`DONE_ENGINEERING` means the native exact-scope projection, database
authority, API, Web surface, tests, migration replay, runtime observation and
external verifier Evidence are implemented.

It does not mean:

- a supplier order was placed;
- a shipment was received;
- an invoice was accepted;
- a supplier was paid;
- real Product, Order, Inventory, Settlement or Cash Facts exist;
- Actual Cash CM3 is available;
- 0.59 Release, Pilot or Final Gates passed.

The truthful business state remains `no_data`, and all external writes remain
disabled.
