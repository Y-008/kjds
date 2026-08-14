# ADR-0072: Native exact-scope accounts payable control

- Date: 2026-07-30
- Status: Accepted for BAS-152
- Requirement: BR-126
- Decision owner: Finance and procurement architecture
- Approval owner: Finance leadership

## Context

BAS-151 now proves the exact procurement decision, supplier order, receipt
and inspection timeline. KJDS also has exact-scope FinanceEntry Bank Payment,
independent Approval, governed execution commands and immutable Evidence.

The missing authority is an accounts-payable subledger. The existing
`CostEvidenceAuthorityService` can attest that an Evidence document is
suitable for one actual-cost leg, but it intentionally has no invoice
header, line, due date, open balance, three-way match or payment allocation.
Treating that attestation as AP would lose liabilities, duplicate detection,
tax, ageing and payment conservation.

## Decision

### One deep projection

Add:

`ScopedAccountsPayableWorkspace.project(...)`.

It owns exact-scope validation, invoice selection, line conservation,
three-way matching, payment-chain verification, server filtering,
pagination, counts, blockers, artifact and snapshot hashing. Router, Web and
Agent prompts remain shallow.

It composes:

- immutable Supplier Invoice headers and lines;
- `ScopedProcurementReceivingWorkspace`;
- Canonical Product;
- immutable Evidence and independent Invoice Review Evidence;
- existing Approval;
- existing one-time `LimitedExecutionCommand`;
- existing exact-scope `FinanceEntry.BANK_PAYMENT` as bank Readback.

It does not create another Product, purchase order, receipt, Approval,
Permit, Bank Payment or profit store.

### Forward-only 0078 authority

Migration 0078 creates:

- `supplier_invoices`;
- `supplier_invoice_lines`.

Invoice header and every line are immutable and exact-scope. The header binds
one purchase order, supplier, source Evidence hash, issue/due timestamps,
currency, net, tax and gross totals. Lines bind Product, quantity, unit
price, net, tax and gross values. Header totals must conserve with lines.
Legacy authority is not inferred.

0078 adds nullable payment bindings to the existing `finance_entries`:

- supplier invoice;
- supplier;
- payment Approval;
- limited execution command.

The bindings are all absent or all present. A complete binding is only valid
for an exact-scope negative `bank_payment`. Existing unbound Bank Payments
remain valid for other actual-cost legs but cannot prove a supplier invoice
payment.

### Invoice intake and review

An invoice intake freezes the original Evidence, header, lines, payload hash
and exact scope. Repeated supplier/invoice references with different content
fail closed.

Independent review is an immutable Evidence attestation with:

- authentic original;
- supplier and legal entity match;
- purchase order match;
- receipt and inspection match;
- line quantity and price match;
- currency, tax and total match;
- issue and due dates checked.

The uploader cannot review their own invoice. Any current valid rejection
blocks the invoice. A review is not a payment Approval.

### Payment-chain observation

The workspace can call an invoice paid only when:

- the invoice is accepted and three-way matched;
- Approval action is `finance.pay_supplier_invoice`;
- requester and approver differ;
- Approval payload and hash bind the exact invoice and amount;
- the limited command binds that Approval decision, is one-time, unexpired
  at execution and has a successful immutable receipt;
- the FinanceEntry is a negative Bank Payment bound to the same invoice,
  supplier, Approval and command;
- Bank Payment Evidence is a current exact-scope bank Readback;
- payment allocations do not duplicate, cross invoices or exceed gross due;
- gross due equals paid plus open balance.

An externally observed debit without this chain remains
`payment_authority_missing`; it is not silently promoted to a controlled KJDS
payment.

### State contract

Server stages are:

- `invoice_captured`;
- `review_pending`;
- `rejected`;
- `three_way_match_pending`;
- `matched`;
- `payment_approval_pending`;
- `payment_permit_pending`;
- `payment_readback_pending`;
- `partially_paid`;
- `settled`;
- `variance`;
- `blocked`.

The latest damaged authority fails closed. The module never substitutes an
older accepted review, Approval, command or payment.

### Agent and execution boundary

The projection and Agent artifact may recommend internal tasks only. They
cannot:

- create or modify Invoice, line or review;
- change Product, purchase order, receipt or inspection;
- create or decide Approval;
- issue or queue a Permit/command;
- create FinanceEntry or payment allocation;
- contact a supplier;
- initiate payment, refund or dispute;
- call a bank, PSP, Seller ERP or any external write surface.

BAS-152 does not register or enable a payment Adapter. Payment remains L4 and
requires independent human Approval even in future autonomous phases.

## Rejected alternatives

- Reuse cost Evidence attestation as AP: rejected because it has no payable
  identity, lines, due/open balance or payment allocation.
- Add a second payment ledger: rejected because exact-scope FinanceEntry Bank
  Payment is already the accounting payment truth.
- Mark any bank debit as paid: rejected because it cannot prove invoice,
  supplier, Approval or Permit authority.
- Let the Agent approve or issue the command: rejected because that destroys
  separation of duties.
- Integrate a payment provider in this slice: rejected because no authorized
  payment Adapter, credential boundary or compensation drill exists.
- Use private Seller ERP or supplier-site endpoints: rejected because KJDS
  cannot manufacture third-party permission or reliable revocation.

## Verification

BAS-152 must prove:

- zero raw read before valid entity authority;
- exact invoice/line scope and as-of isolation;
- immutable duplicate-safe intake and independent review;
- header/line and PO/receipt/inspection conservation;
- latest bad Evidence/review failure without fallback;
- Approval/command/Readback separation and binding;
- negative, non-duplicate, non-overpay payment conservation;
- anonymous 401 and unauthorized 403;
- forward-only 0078 empty/live/downgrade-forward replay;
- Web all states at desktop and 390px;
- fresh Harness/Graph observations;
- no payment Adapter, self-approval, Permit issuance or external write.
