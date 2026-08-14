# ADR-0070: Native exact-scope actual profit ledger

- Date: 2026-07-29
- Status: Accepted for BAS-150
- Requirement: BR-124
- Decision owner: Profit and finance control-plane engineering

## Context

The existing `ProfitLedgerService` predates native scope. It reads global
legacy Orders, Charges, Facts, fee mappings, FX and Finance Entries. The
current `ScopedProfitLedgerAuthority` calls that global projection first and
then excludes rows whose Evidence cannot prove scope. Post-materialization
filtering is not an exact tenant/entity/store authority and therefore cannot
support Actual Cash CM3.

BAS-149 correctly refuses to expose actual profit unless its profit dependency
advertises native exact-scope authority. KJDS must close that authority gap
without creating another Product, Order, cost or profit truth.

## Decision

Upgrade the existing deep module:

`ScopedProfitLedgerAuthority.snapshot(...)`.

The module owns exact-scope source admission, current Order selection, Product
binding, fifteen-leg classification, monetary conversion, reconciliation,
failure policy, pagination, counts and stable artifact hashes. Router, Web,
Agents and `ScopedSettlementCashWorkspace` consume this projection and do not
recompute profit.

### Existing-ledger extension

Forward-only migration `0076` extends existing ledgers:

- `fee_mappings` and `fx_rates` receive complete-or-empty tenant/entity/store,
  ScopeGrant, source Evidence and scope-cutoff authority;
- `finance_entries` receives an optional native `profit_cost_type`;
- `FinanceEntryKind.BANK_PAYMENT` represents an explicitly allocated,
  independently reviewed bank outflow for exactly one reconciliation key.

Legacy rows keep null scope and null profit classification. Legacy and scoped
mapping/FX uniqueness use separate partial indexes. No historical row is
updated, inferred or copied.

`profit_cost_type` is limited to the fifteen `ChargeType` cost legs. It is
allowed only on scoped `BANK_PAYMENT` entries, whose amount must be zero or an
outflow. A zero entry is not an implicit default: it still requires immutable
Evidence and exact scope.

Platform deductions remain existing `PLATFORM_FEE` entries and receive their
cost or revenue-erosion classification only from the current exact-scope
approved FeeMapping. The projection never trusts a Router, Web field, model
answer or source label as an accounting category.

### Exact-scope projection

Before materialization, all source queries apply:

- exact tenant, entity, store and ScopeGrant authority;
- `scope_as_of`, `effective_at`, `recorded_at <= as_of`;
- native scoped Product and resolved Order Fact predicates;
- bounded collection limits.

Missing or invalid entity authority performs zero Product, Fact, Finance,
mapping, FX and reconciliation reads.

For each explicit order reconciliation key the latest Order Fact must:

- have valid immutable Evidence and an intact payload hash;
- bind exactly one Product in the same scope;
- agree on Product ID and SKU;
- bind an independently recorded Order Receivable through `source_fact_id`.

Older good Order state may remain history but never replaces a bad latest
candidate.

### Fifteen actual cost legs

The authoritative cost contract is:

1. product cost;
2. domestic logistics;
3. international logistics;
4. packaging;
5. warehousing;
6. customs;
7. tax;
8. last mile;
9. platform fee;
10. advertising;
11. return;
12. FX;
13. capital cost;
14. customer compensation;
15. damage.

Each leg is `actual`, `zero` or `unknown`. `unknown` is never converted to
zero. Actual and zero legs must be backed by valid scoped Evidence. Costs may
come from a scoped platform-fee mapping or a scoped per-order Bank Payment;
unclassified values remain isolated.

Discount and refund remain revenue erosion rather than being relabelled as one
of the fifteen costs.

CM1, CM2 and CM3 use `Decimal`, a named quote currency and an applicable
exact-scope FX rate. Missing or invalid FX blocks the affected order.

### Actual Cash CM3

Actual Cash CM3 is available only when:

- current Order revenue and the Order Receivable agree;
- the latest valid independent ReconciliationRun is `matched` and its input
  hash matches the as-of entry set;
- all platform fee mappings and FX rows are exact-scope and valid;
- all fifteen cost legs are actual or explicitly evidenced zero;
- unknown fees and review-required entries are absent;
- platform settlement and bank receipt conserve;
- gross revenue plus platform adjustments and bank payments equals bank
  receipt plus bank payments.

No SKU guess, cross-order netting, store-wide allocation or proportional split
is allowed.

### Failure and disclosure

Bad latest Evidence, future state, source/hash/scope drift, current
Order/Product conflicts, reconciliation drift, unknown fees or incomplete
fifteen-leg coverage fail closed. The affected row is withheld; only bounded
reason counts may be returned. Business amounts, order keys and Evidence IDs
from excluded rows are not exposed.

### Agent and write boundary

Projection and Agent artifacts can only recommend or create internal work.
They cannot create or mutate a Product, Fact, FeeMapping, FX, FinanceEntry,
ReconciliationRun, Approval or Permit and cannot pay, refund, price, advertise
or write to an external platform.

Private Seller ERP endpoints, Cookies, internal Tokens, CAPTCHA bypass and
fabricated authorization remain prohibited. Authorized exports and contracted
APIs continue through immutable Evidence and independent review.

## Consequences

- BAS-149 can consume a real native profit authority without a circular or
  second ledger.
- Existing legacy reports remain readable through legacy services but cannot
  satisfy native Actual Cash CM3.
- Real runtime remains `no_data` until scoped Order, expense, settlement, bank,
  mapping and FX Evidence exist.
- Engineering completion does not mean KJDS has earned profit.
