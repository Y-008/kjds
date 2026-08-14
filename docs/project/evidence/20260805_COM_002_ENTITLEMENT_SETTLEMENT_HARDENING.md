# COM-002 Entitlement Settlement Hardening Evidence

- Date: 2026-08-05
- Status: ENGINEERING COMPLETE / COMMERCIAL GATE BLOCKED
- Scope: internal exact-scope entitlement balance projection only
- External write: false
- Sale activation: false

## Closed finding

The commercial entitlement projection previously derived `outstanding_total` from
`payment_total - refund_total`. That inverted the receivable and treated payment
provider progress states as settled cash. The projection now applies the same
conservation rule independently to every latest exact-scope invoice and then sums
the results:

```text
invoice outstanding = invoice gross - settled payments + paid refunds
scope outstanding   = sum(invoice outstanding)
```

The following rules are frozen in `CommercialLifecycleService`:

- Only the latest subscription in the exact scope contributes invoices to the
  current entitlement; invoices from superseded subscriptions remain auditable
  but do not leak into the new subscription balance.
- Only collectible invoice states `issued`, `partially_paid`, and `paid` enter
  the receivable. `draft`, `void`, and `closed` remain auditable but contribute
  zero; payments and refunds against them fail before write.
- An issued invoice with no settled payment retains its full gross amount and
  keeps entitlement in `grace`, or `read_only` after its unpaid due date. An
  invoice state named `paid` does not substitute for settled-cash Evidence.
- Only payment state `settled` reduces the balance. `succeeded` is provider
  progress and is not a bank-settled cash fact.
- Only refund state `paid` reopens the balance, and it must reference an exact
  latest `settled` payment attempt for the same invoice and currency. Cumulative
  paid refunds are capped independently by that exact payment amount. `approved`
  is not a paid cash refund; a later `reversed` state removes the previously paid
  refund from the latest-state projection. `paid` may transition only to
  `reversed`; relabelling paid cash as `rejected` is rejected.
- Invoice, payment-attempt, and refund record identities freeze their parent,
  currency, amount, and kind-specific money tuple on first append. A new
  idempotency key cannot replay the same state or rebind an existing record to a
  different invoice, subscription, payment, or amount.
- Exact-scope invoice, payment, and refund idempotency winners are resolved and
  full-request-hash checked before current parent, capacity, identity, or state
  validation. The original request therefore replays its frozen response without
  adding an event, Evidence link, or entitlement even after later state changes;
  payload drift on the same key fails closed.
- Append-only state changes are counted once per immutable invoice, payment
  attempt, and refund identity by selecting the latest explicitly admitted state.
- Multiple invoices conserve gross, settled cash, paid refunds, and outstanding
  balance across the full exact scope.
- Invoice, payment, and refund currency must agree. Missing invoice gross,
  cross-invoice refund references, overpayment, and refunds above settled cash
  fail before a new event is committed.
- PostgreSQL per-scope writes take the scope advisory lock before any read or
  validation. Competing settlements/refunds therefore re-read capacity after the
  winner commits, while a different exact scope remains independently lockable.
  Recorded-time stamps are strictly increasing within each scope so rapid state
  transitions cannot make an older entitlement projection appear current solely
  because random event identifiers sort differently.
- Entitlement events are refreshed when totals change even if state and reason
  remain unchanged, so partial settlement cannot leave a stale balance payload.

## Focused acceptance matrix

The focused contract tests cover:

1. gross 100 with no payment -> outstanding 100 / `grace`;
2. `succeeded` 100 only -> settled total 0 / outstanding 100;
3. settled 40 -> outstanding 60 and remaining capacity 60;
4. settled 100 -> outstanding 0 / `active`;
5. settled 100 plus paid refund 20 -> outstanding 20 / `grace`;
6. an approved refund does not reopen outstanding before state `paid`;
7. payment and refund state evolution is counted once and refund reversal closes
   the reopened balance;
8. multiple invoices conserve all four monetary totals without duplicate state
   rows;
9. another tenant/entity/store scope contributes zero to the requested scope;
10. an unpaid overdue invoice produces `read_only`;
11. invoice/payment/refund currency drift and missing invoice gross fail closed;
12. a refund above settled cash and a payment above outstanding capacity are
    rejected without a partial write;
13. superseded-subscription invoices do not enter the current entitlement;
14. draft/void invoices contribute zero and reject settlement writes, while an
    invoice state `paid` with no settled payment remains outstanding;
15. a paid refund linked to a non-settled payment is rejected, and cumulative
    refunds cannot exceed the exact settled payment they reference;
16. record identity/money drift, non-idempotent same-state replay, and
    `paid -> rejected` refund relabelling fail before append;
17. a full-size paid refund can be reversed without being treated as a second
    refund capacity claim;
18. real PostgreSQL two-session settlement/refund races admit one capacity
    winner, reject the loser, preserve strict recorded-time order, and prove a
    different exact scope does not share the same advisory lock;
19. invoice/payment/refund exact winners replay before current-state checks with
    zero new event/Evidence/entitlement, while same-key drift and different-key
    same-state attempts are rejected.

All monetary operations continue to use `Decimal`, explicit allowlisted currency,
exact scope, append-only events, and the existing idempotency/state-machine
contracts.

## Explicit non-claims and remaining blockers

- Payment or subscription settlement Evidence in this ledger is not independently
  proven bank receipt Evidence and is not promoted into a bank-cash fact.
- Real PSP/payment processor integration, acquiring settlement, bank readback,
  chargeback handling, invoicing authority, and tax/accountant authority remain
  `UNKNOWN`.
- Router-level actor separation and independent settlement reviewer SoD remain
  open; this slice changes no router, API, runtime composition, or public write
  path.
- Hosted target, TLS, backup/restore, RPO/RTO, payment/invoice/tax contracts, and
  Contract/DPA/SLA authority remain external C0 blockers.
- No Approval, Permit, Fact, FinanceEntry, Pilot, Outbox, payment, refund, tax
  filing, customer communication, or external system write is created.
- COM-002 remains preparation-only/not-for-sale until the external commercial
  closure package and independent authority evidence are complete.
