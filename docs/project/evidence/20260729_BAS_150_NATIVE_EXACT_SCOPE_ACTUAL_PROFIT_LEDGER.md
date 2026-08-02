# BAS-150 native exact-scope actual profit ledger

- Date: 2026-07-29
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Business state: `no_data`
- External write: `false`
- Requirement: `BR-124`
- ADR: [ADR-0070](../../adr/ADR-0070-native-exact-scope-actual-profit-ledger.md)

## Outcome

BAS-150 upgrades the existing profit projection into one native deep module:

`ScopedProfitLedgerAuthority.snapshot(...)`.

It directly projects actual per-order profit from the existing exact-scope
Order Fact, Canonical Product and Finance authorities. It does not create a
second Order, Product, Cost, Profit, Approval or Permit truth store.

Canonical HTTP surfaces:

- `GET /v1/profit-ledger`;
- `GET /v1/profit-ledger/erosion`.

Canonical Web surface:

- `/profit-ledger`.

Router, React and Agent prompts do not calculate cost classification,
CM1/CM2/CM3, cash conservation or Actual Cash CM3.

## Native profit authority

Forward-only migration `20260729_0076`:

- adds complete-or-empty tenant/entity/store/grant/Evidence/as-of scope to
  the existing `fee_mappings` and `fx_rates`;
- separates legacy and scoped idempotency with PostgreSQL partial unique
  indexes;
- adds `profit_cost_type` to the existing `finance_entries`;
- constrains per-order Bank Payment cost classification and non-positive
  payment values;
- adds an exact-scope profit lookup index.

Historical legacy rows remain all-null for the new scope fields. No entity is
guessed or backfilled.

The live database and Alembic script each expose one head:

`20260729_0076`.

A temporary PostgreSQL database passed:

- empty replay from 0001 to 0076;
- downgrade from 0076 to 0075;
- forward replay from 0075 to 0076;
- deletion after verification.

Live PostgreSQL inspection confirms:

- `ck_fee_mappings_scope_complete`;
- `ck_fx_rates_scope_complete`;
- `ck_finance_entries_profit_cost_type`;
- `uq_fee_mapping_scoped_version`;
- `uq_fx_rate_scoped_observation`;
- `ix_finance_entry_scope_profit`.

## Deep-module boundary

### Scope before any raw read

The projection validates authenticated Principal, exact authorized store,
current entity authority and timezone-aware cutoff before calling:

- `FinanceService.read_scoped_sources(...)`;
- `FinanceService.read_scoped_profit_authorities(...)`;
- the exact scoped Canonical Product SQL projection.

Missing entity authority returns `no_data` with:

- zero Finance source reads;
- zero FeeMapping/FX reads;
- zero Product raw reads;
- `scoped_input_read=false`.

Malformed ready authority fails closed. Exact SQL predicates include tenant,
entity, store, ScopeGrant authority and `as_of`. Legacy and cross-scope rows
never enter the native result.

### Current Order and Product identity

For every explicit reconciliation key, the projection selects the latest
Order Fact and never falls back from a damaged latest authority to an older
record. It validates:

- Fact contract and payload hash;
- Evidence content hash and scoped binding;
- effective/recorded/scope timestamps;
- resolution status;
- exact Product ID and SKU binding.

Affected values and identifiers are withheld when the current Fact or Product
is missing, conflicting, future, damaged or outside the current scope.

### Fifteen actual cost legs

Each reconciled order must contain all fifteen legs:

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

Every leg is server-classified as `actual`, `zero` or `unknown`. Explicit zero
still requires valid Evidence. Any `unknown` blocks the affected order.

Platform fees may only be classified by a current exact-scope FeeMapping.
`FinanceService.record_entry(...)` and the projection both reject a
`platform_fee` disguised as a Bank Payment. Non-platform actual costs require
explicit per-order Bank Payment classification. SKU guessing, cross-order
netting, store allocation and proportional allocation are prohibited.

FX selection is exact-scope, provider-specific and as-of. A missing, future,
damaged or cross-scope rate blocks the affected order.

### Independent reconciliation and cash conservation

The latest Reconciliation must be:

- `matched`;
- within the same scope and cutoff;
- based on the exact current Finance Entry set;
- independently created;
- bound to current source Evidence authority;
- consistent with all applied FeeMapping and FX IDs.

The projection checks:

- Order Receivable is uniquely bound to the current Order Fact;
- expected platform settlement equals the platform settlement;
- platform settlement equals Bank Receipt;
- Bank Receipt plus explicit Bank Payments equals Actual Cash Profit;
- CM3 equals Actual Cash Profit;
- reconciliation input and authority hashes remain stable.

Only then is:

`actual_cash_cm3.status=available`.

The erosion endpoint traverses all server pages before aggregating. It does
not silently calculate only the first page.

## Failure and no-write policy

The affected business payload is withheld on:

- missing, damaged or hash-drifted Evidence;
- missing entity or malformed scope authority;
- future or cross-scope Fact, Product, Entry, Mapping, FX or Reconciliation;
- conflicting latest Order authority;
- missing or conflicting exact Product binding;
- missing or duplicate Order Receivable;
- unknown platform fee;
- missing one of the fifteen cost legs;
- stale, self-reviewed or damaged Reconciliation;
- Mapping/FX selection drift;
- cash or CM3 conservation failure;
- source collection truncation.

Excluded rows expose reason counts only:

`business_values_exposed=false`.

The versioned `kjds-profit-steward-artifact-v1` artifact may only recommend
internal tasks. Runtime output proves all writes remain false for:

- Fact;
- Product;
- FeeMapping;
- FX;
- FinanceEntry;
- Reconciliation;
- Approval;
- Permit;
- payment;
- refund;
- pricing;
- advertising;
- external systems.

Private Seller ERP endpoints, Cookies, internal Tokens and CAPTCHA bypass
remain prohibited. KJDS authorization cannot create third-party permission.
Authorized formal exports and contracted adapters remain the only Seller ERP
bridge path.

## Backend and repository verification

Focused tests cover:

- missing entity with zero raw reads;
- exact Product and Order Fact binding;
- deterministic reconciled Actual Cash CM3;
- all fifteen actual/zero cost legs;
- bad latest Order Evidence without fallback;
- missing fifteenth leg with value withholding;
- opaque cursor stability;
- exact-scope FeeMapping and FX entity isolation;
- legacy Mapping non-fallback;
- Bank Payment scope/sign/classification service checks;
- database rejection of invalid cost type;
- platform fee Bank Payment rejection;
- anonymous 401 and unauthorized store 403;
- API/OpenAPI compatibility.

Results:

- focused backend: `79 passed`;
- full backend: `905 passed`, `9 warnings`;
- Ruff: all checks passed;
- OpenAPI snapshot matches runtime;
- `verify_secrets`: passed across `889` non-ignored worktree files and `581`
  historical paths;
- `git diff --check`: passed;
- `npm ci`: passed with `0` vulnerabilities;
- Web contract tests: `89 passed`;
- Web production build: `46` routes.

## PostgreSQL and real runtime

Live native rows:

- scoped Product: `0`;
- scoped Order Fact: `0`;
- scoped FinanceEntry: `0`;
- scoped Bank Payment: `0`;
- scoped ReconciliationRun: `0`;
- scoped FeeMapping: `0`;
- scoped FX Rate: `0`;
- Actual Cash CM3 available: `0`.

PostgreSQL, API, Web and media-worker are all `healthy`.

Live API behavior:

- readiness: `200`;
- anonymous profit ledger: `401`;
- configured operator and exact store: `200`;
- unauthorized store: `403`;
- entity: `null`;
- status: `no_data`;
- rows and all counts: `0`;
- `scoped_input_read=false`;
- `native_exact_scope=true`;
- `external_write_allowed=false`.

Repeated fixed-input reads produce the same snapshot hash and do not create
Fact, Product, Finance Entry, Reconciliation, Approval, Permit or
OperatingTask.

## Web and browser

`/profit-ledger` renders:

- loading and retryable error;
- reconciled/no_data/partial/blocked states;
- current scope and server counts;
- server-side query, order/SKU grain and opaque cursor;
- fifteen named actual/zero/unknown cost legs;
- CM1, CM2, CM3 and Actual Cash CM3 as server values;
- expected settlement, platform settlement, Bank Receipt, Bank Payments and
  conservation delta;
- current Reconciliation input hash and Evidence count;
- source gaps, Owner, SLA and next workspace;
- immutable Agent and external-write boundaries.

Finance Control, OMS and Commerce OS link to the same native profit workbench.

Browser QA used an authenticated live API response in memory and the real
Graph status response. It did not persist a credential or claim a new
Supabase session. The visible global rail truthfully shows the unrelated
BAS-040 scheduler as `stale`.

- desktop: `inner/client/scrollWidth = 1440/1440/1440`;
- mobile: `inner/client/scrollWidth = 390/390/390`;
- console errors: `0`;
- page errors: `0`;
- visible business state: `no_data`.

Screenshots:

- `output/playwright/bas150-profit-ledger-desktop.png`
  - SHA-256:
    `525d884d3b6e7fa7128cf20ba396d48f4813759cf81d9a13a87aef8e371c3130`
- `output/playwright/bas150-profit-ledger-mobile-390.png`
  - SHA-256:
    `711d1b776731df61ff0f61a79586520e2444911f1fe94b339cbac819d06c8bb3`

## Harness and Graph

`scripts/seed_bas150_agent_graph.py` independently reruns and records:

- focused pytest;
- PostgreSQL and Alembic authority;
- authenticated Docker/API runtime;
- desktop and 390px browser Evidence;
- immutable BAS-150 Evidence.

Canonical Graph after BAS-150:

- tasks: `81`;
- nodes: `190`;
- edges: `192`;
- observations: `>=326`.

Only fresh external verifier observations can change BAS-150 task state.

## Gate interpretation

BAS-150 is `DONE_ENGINEERING`, not a real profit claim.

The business state remains:

- no exact entity authority;
- no scoped Product or Order Fact;
- no scoped Finance Entry, Reconciliation, FeeMapping or FX;
- no Bank Receipt or Bank Payment;
- no Actual Cash CM3;
- no Approval, Permit or external write.

The 0.59 PM/RA Release Gates and Pilot/Final Gates remain rejected or
unpassed. Real Order-to-Cash still requires official scoped operating,
platform finance, supplier cost and bank Evidence plus independent review.
