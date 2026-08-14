# BAS-152 native exact-scope accounts payable control

- Date: 2026-07-30
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Business state: `no_data`
- External write: `false`
- Requirement: `BR-126`
- ADR: [ADR-0072](../../adr/ADR-0072-native-exact-scope-accounts-payable-control.md)

## Outcome

BAS-152 adds one native deep read module:

`ScopedAccountsPayableWorkspace.project(...)`.

It projects an immutable exact-scope Supplier Invoice subledger together
with the existing procurement/receiving, Canonical Product, independent
review Evidence, payment Approval, one-time LimitedExecutionCommand and
scoped FinanceEntry Bank Payment authorities. It does not introduce a second
Product, purchase order, receipt, Approval, Permit, Bank Payment or profit
truth.

Canonical HTTP surfaces:

- `GET /v1/accounts-payable/workspace`;
- `POST /v1/accounts-payable/invoices`;
- `POST /v1/accounts-payable/invoices/{invoice_id}/authority-review`.

Canonical Web surface:

- `/accounts-payable`.

Router, React and Agent prompts do not calculate invoice totals, three-way
match, stage, paid amount, open balance or payment authority.

## Native invoice authority

Forward-only migration `20260730_0078` creates:

- `supplier_invoices`;
- `supplier_invoice_lines`.

The immutable header binds exact tenant/entity/store/grant/as-of authority,
purchase order, supplier, source Evidence and hash, issue/due timestamps,
currency, net, tax and gross values. Every immutable line binds the same
scope, one Canonical Product, quantity, unit price, tax and extended values.
The service verifies line extensions and header/line monetary conservation
before intake.

The same migration adds nullable, complete-or-empty bindings to the existing
`finance_entries`:

- Supplier Invoice;
- supplier;
- independent payment Approval;
- one-time LimitedExecutionCommand.

A complete binding is valid only for an exact-scope negative Product Cost
`BANK_PAYMENT`. The migration owns the PostgreSQL foreign keys and constraint;
the narrow SQLAlchemy finance test metadata does not manufacture duplicate
table authority.

The live database and Alembic script each expose one head:

`20260730_0078`.

A temporary PostgreSQL database passed:

- empty replay from 0001 to 0078;
- downgrade from 0078 to 0077;
- forward replay from 0077 to 0078;
- deletion after verification.

Live PostgreSQL inspection confirms the two invoice tables, their complete
scope and positive-line constraints, the FinanceEntry complete-or-empty
payment binding constraint, foreign keys and scoped indexes.

Live native rows:

- Supplier Invoice: `0`;
- Supplier Invoice Line: `0`;
- invoice-bound Bank Payment: `0`.

No synthetic invoice or payment was inserted to make the workspace appear
ready.

## Deep-module boundary

### Scope before any raw read

The projection validates authenticated Principal, authorized store, current
entity authority, authority hash and timezone-aware cutoff before reading
Invoice, Procurement or Finance sources.

Missing entity authority returns `no_data` with:

- zero Invoice source reads;
- zero Procurement source reads;
- zero Finance, Approval and command reads;
- `scoped_input_read=false`.

Malformed authority and unauthorized store fail closed. Exact SQL predicates
include tenant, entity, store, ScopeGrant authority and as-of. Legacy,
cross-scope and future rows never enter the projection.

### Immutable intake and independent review

Invoice intake requires current, content-valid and exact-scope original
Evidence. It freezes the supplier/invoice reference, purchase order, header,
lines, payload hash and scope. A repeated identity with changed content fails
closed; an exact replay is idempotent.

The uploader cannot review their own invoice. Review is a separate immutable
Evidence attestation of:

- source authenticity;
- supplier/legal entity;
- purchase order;
- receipt/inspection;
- quantity and price;
- currency, tax and totals;
- issue and due dates.

Every check must pass for acceptance. A current rejection blocks the
invoice. A damaged latest review fails closed and cannot fall back to an
older accepted record. Invoice review is not payment Approval.

### Server-owned three-way match

For each admitted invoice the deep module composes the existing
`ScopedProcurementReceivingWorkspace` using the exact purchase order query.
It validates:

- Supplier and currency identity;
- Canonical Product identity;
- ordered, received, inspected and passed quantities;
- invoice quantity and unit-price agreement;
- line extension, tax and header totals;
- procurement Evidence and latest event validity.

The server alone returns current stage, blockers, amounts, open balance,
Owner, SLA, next action, counts, filters, opaque cursor, versioned Agent
artifact and stable snapshot hash.

### Controlled payment observation

An invoice payment is accepted only when the observed chain binds the exact
scope, invoice, supplier, amount and currency through:

`independent Approval → one-time command → successful immutable receipt →
negative FinanceEntry BANK_PAYMENT → exact bank Readback Evidence`.

Self-approval, wrong action/payload, expired or reused command, missing
receipt, non-bank Evidence, positive payment, duplicate allocation,
cross-invoice binding, overpayment and paid/open/gross non-conservation fail
closed. A bank debit without the complete chain is not promoted to a
controlled supplier payment.

The server state contract covers:

`invoice_captured`, `review_pending`, `rejected`,
`three_way_match_pending`, `matched`, `payment_approval_pending`,
`payment_permit_pending`, `payment_readback_pending`, `partially_paid`,
`settled`, `variance` and `blocked`.

## Agent and no-write boundary

The versioned `kjds-accounts-payable-steward-artifact-v1` may recommend
internal work only. Projection and Agent cannot:

- create or modify Invoice, line or review;
- change Product, purchase order, receipt or inspection;
- create or decide Approval;
- issue, queue or consume a Permit/command;
- create FinanceEntry or payment allocation;
- contact a supplier;
- initiate payment, refund or dispute;
- call a bank, PSP, Seller ERP or any external write surface.

Runtime reports:

- `invoice_created=false`;
- `approval_created=false`;
- `permit_created=false`;
- `payment_initiated=false`;
- `external_write_allowed=false`;
- Agent self-approval and Permit issuance: `false`.

BAS-152 does not register or enable a payment Adapter. Supplier payment
remains L4 and requires independent Approval. Private Seller ERP endpoints,
Cookies, internal Tokens and CAPTCHA bypass remain prohibited: KJDS
authorization cannot confer third-party permission. Official APIs, formal
exports and explicitly authorized adapters remain the only Seller ERP bridge
paths.

## Backend and repository verification

Focused tests cover:

- missing entity with zero raw reads;
- exact Invoice/line SQL isolation and deterministic source replay;
- immutable, idempotent intake and independent review;
- header/line and purchase-order/receipt/inspection conservation;
- bad latest review Evidence without fallback;
- rejected review and quantity mismatch;
- stable server filters, cursor, artifact and snapshot;
- cross-store rejection before source reads;
- partial DB scope/payment bindings and invalid line quantity;
- existing FinanceEntry and Procurement behavior;
- anonymous 401 and unauthorized store 403;
- API/OpenAPI compatibility.

Results:

- focused backend: `73 passed`;
- full backend: `926 passed`, `9 warnings`;
- Ruff: all checks passed;
- OpenAPI snapshot matches runtime;
- `verify_secrets`: passed across `911` non-ignored worktree files and `581`
  historical paths;
- `git diff --check`: passed (line-ending notices only);
- `npm ci`: passed with `0` vulnerabilities;
- Web contract tests: `97 passed`;
- Web production build: `48` routes.

The first full-suite attempt was interrupted by a Windows global pytest
temporary-directory permission error, not a test assertion. A repository
local fresh `--basetemp` then exposed one genuine coverage-registry drift:
the new direct transaction module was absent from
`outbox_coverage.json`. The registry now classifies
`accounts_payable.py` as internal-only with no cross-boundary delivery, and
the complete suite passes.

## PostgreSQL and real runtime

PostgreSQL, API, Web and media-worker are all `healthy`.

Live API behavior:

- readiness: `200`;
- anonymous accounts-payable workspace: `401`;
- configured operator and exact store: `200`;
- unauthorized store: `403`;
- entity: `null`;
- status: `no_data`;
- invoices, lines and payments: `0`;
- `scoped_input_read=false`;
- stable repeated snapshot: `true`;
- payment authority and external write: `false`.

Repeated fixed-input reads do not create Product, Invoice, line, review,
Approval, Permit, FinanceEntry, payment or OperatingTask.

## Web and browser

`/accounts-payable` renders:

- loading and retryable error;
- ready/no_data/partial/blocked states;
- exact scope, source gaps and server counts;
- server query, stage filter and opaque cursor;
- invoice header/lines and Product/SKU identity;
- three-way match and procurement/receiving lineage;
- payment Approval, Permit, Readback and balance chain;
- Owner, SLA, next action and explicit L4 control boundary.

Commerce OS, Procurement and Finance link to the same native AP workbench.

Browser QA used an authenticated live API response frozen in memory and the
real application bundle. It did not persist a credential or claim a new
Supabase session.

- desktop: `inner/scrollWidth = 1440/1440`;
- mobile: `inner/scrollWidth = 390/390`;
- console errors: `0`;
- page errors: `0`;
- visible business state: `no_data`.

Screenshots:

- `output/playwright/bas152-accounts-payable-desktop.png`
  - SHA-256:
    `b548fa8c8dc415ac1803f1150080fd59d93841a595c0c4ecd4ff18ea8f855d7d`
- `output/playwright/bas152-accounts-payable-mobile-390.png`
  - SHA-256:
    `9137c9011b9fc875998a6d62faed257e2502465e57eac7a6460b27312e5f4897`

## Harness and Graph

`scripts/seed_bas152_agent_graph.py` independently reruns and records:

- focused pytest;
- PostgreSQL and Alembic authority;
- authenticated Docker/API runtime;
- desktop and 390px browser Evidence;
- immutable BAS-152 Evidence.

Canonical Graph after the first BAS-152 materialization contained:

- tasks: `91`;
- nodes: `204`;
- edges: `204`;
- observations: `338`;
- latest BAS-152 tests/database/runtime/web/evidence observations:
  `passed` and fresh.

Task state can advance only from the five registered external verifiers.
Neither the workspace Agent artifact nor the implementation process can
self-certify a task.

## Completion classification

`DONE_ENGINEERING` means the native AP authority, deep exact-scope
projection, API, Web surface, tests, migration replay, runtime observation
and external verifier Evidence are implemented.

It does not mean:

- a real supplier invoice exists;
- a supplier payment was approved or executed;
- an actual bank Readback exists;
- real Product, Order, Inventory, Settlement or Cash Facts exist;
- Actual Cash CM3 is available;
- 0.59 Release, Pilot or Final Gates passed.

The truthful business state remains `no_data`, and all external writes remain
disabled.
