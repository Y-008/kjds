# BAS-217 Single-SKU Actual Cash Attribution Evidence

## 1. Scope and truthful claim

- task: `BAS-217`
- machine-CAS commit: `515883eec42955df67fdd9cc2975d55cce2dda70`
- exact12 expansion CAS: `760a40e46953a8990d254d9a5d06ae1d86bcc304`
- exact14 expansion CAS: `58d3fa0e8a546d0069ed6059e03bf69afa7e537c`
- implementation base: `58d3fa0e8a546d0069ed6059e03bf69afa7e537c`
- owner thread: `019fd4c1-60c9-79a0-9338-8c204ba0f312`
- claim: an exact-scope reconciled order cycle can be projected as current
  as-of canonical Product/SKU cash attribution only when a strict
  order-grain Profit authority proves one matching Product/SKU row, Actual
  Cash CM3 and cash conservation.
- not claimed: Ozon offer mapping, a closed return/refund observation window,
  final full-lifecycle SKU cash truth, thirteen-week cash, cash floor,
  maximum loss, Gate PASS, Top1 or a real operating result.
- excluded: router, API/OpenAPI, Web, database,
  migration, PostgreSQL/G-1 and external writes.

## 2. Exact write set

1. `apps/control_plane/scoped_profit_ledger.py`
2. `apps/control_plane/scoped_settlement_cash.py`
3. `apps/control_plane/team_control_tower.py`
4. `apps/control_plane/runtime.py`
5. `docs/project/registries/team_control_tower_registry.json`
6. `tests/test_scoped_profit_ledger.py`
7. `tests/test_scoped_settlement_cash.py`
8. `tests/test_team_control_tower.py`
9. `tests/test_profit_receipt_runtime_composition.py`
10. `docs/project/MASTER_SPEC.md`
11. `docs/adr/ADR-0069-native-exact-scope-settlement-cash-control.md`
12. `docs/adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md`
13. `docs/project/18_TEAM_CONTROL_TOWER.md`
14. `docs/project/evidence/20260808_BAS_217_SINGLE_SKU_ACTUAL_CASH_ATTRIBUTION.md`

The Team Control registry is an input to the trusted Enterprise AI ERP source
bundle. Its intentional policy change therefore updates the pinned source
bundle and compiled Program snapshot in `TeamControlTower`; the Program
registry hash itself remains unchanged. This is a content-addressed contract
upgrade, not acceptance of caller-reported hashes.

## 3. Authority predicate and negative controls

`ScopedSettlementCashWorkspace` now requires the Profit dependency to prove:

- the named native exact-scope Profit contract, matching tenant/entity/store
  and current scope-grant authority;
- the same data cutoff, a valid content-addressed snapshot, read-only control
  envelope and complete order-grain pagination;
- exactly one reconciled row for the reconciliation key, `order_count=1`, a
  valid row snapshot and no unallocated/excluded value;
- exact equality between the current Order Fact Product/SKU identity and the
  Profit row Product/SKU identity;
- row-level Actual Cash CM3 equality and a finite zero conservation delta.
- a Profit-issued `canonical_order_sku_receipt_v1` independently re-read from
  `kjds-profit-order-sku-receipt-authority-v1`, binding exact scope/current
  grant, Order Fact receipt, canonical Product/SKU and stable Profit row basis.

Runtime constructs a server-owned `ScopedProfitOrderSkuReceiptAuthority` from
canonical dependencies as an object distinct from the mutable Profit adapter.
Settlement never discovers the verifier on that adapter, and requires the
authority's `source_profit_snapshot_sha256` to equal the exact Profit snapshot
it consumed. The receipt therefore cannot be replaced by an adapter that merely
reports `native_exact_scope=true`, exposes a verified-looking method or
recomputes its own row/top-level snapshot.
Missing/error receipt authority, wrong issuer/scope/grant/order/Product/SKU,
or a jointly resealed profit/Actual Cash/cost/conservation projection remains
`no_data`.

Only this predicate emits `single_sku_attribution.status=verified`. The output
contains SHA-256 identities and a lineage hash; raw Product, SKU, Order and
amount values are not copied into the Team Control authority projection.
Malformed time, snapshot, numeric, scope, pagination, identity or conservation
data fails closed to `no_data`. Two current Order Facts with equal payloads but
different Product/SKU identities conflict rather than being selected.

`TeamControlTower` requires that attribution before incrementing
`verified_single_sku_cycle_count` and setting the independent
`single_sku_attribution_status=VERIFIED`. The legacy outer
`actual_cash_truth.status` remains `PARTIAL`, so the existing owner-page “real
SKU cash loop” label and Russia operating truth readiness cannot be promoted
while offer mapping and the return window remain unproved. A legacy/weak
adapter with an otherwise reconciled cash cycle is also `PARTIAL`, with
`single_sku_cash_attribution_missing`. The semantic lineage binds the order
key, exact scope/current grant, Product/SKU, Order Fact receipt, stable Profit
row basis, row and receipt hashes. It excludes observation `as_of` and the
top-level Profit snapshot, which remain audit-only. Therefore a real semantic
change invalidates the old continuation, while the same business state at
T/T+5 keeps the decision and continuation stable. Product-only, SKU-only,
joint Product/SKU, wrong-order and wrong-row-basis resigning fails closed.

Verified counts are candidate counts until source completeness is proven.
Unless source=`ready`, pagination is complete, excluded=0, gaps/blockers are
empty and `order_count=identity_count=1`, both verified counts are forced to
zero.

The registry fixes `offer_mapping_proven=false` and
`return_window_closed_proven=false`. Absence of a return Fact is not interpreted
as a closed return/refund window.

## 4. Verification record

- Python compile for the eight exact Python implementation/test paths: PASS.
- Ruff exact Python set with `--no-cache`: PASS (`All checks passed!`).
- focused Profit + Settlement + Team Control + runtime composition result:
  `113 passed in 8.60s` after the import-only Ruff correction.
- task-owned pytest basetemps are reproducible test artifacts. Their exact
  cleanup command was declined by tool policy; per control instruction no
  deletion was retried, and they are outside the exact14 manifest.
- secret verifier: PASS (`1436` non-ignored worktree files and `1432`
  historical paths checked).
- `git diff --check` and `git diff --cached --check`: PASS; staged set empty.
- DB/PostgreSQL/G-1: NOT RUN.

## 5. Frontier review

`frontier_review=not_required`. This slice corrects an existing authority and
type-safety defect. It installs no dependency, model, provider, protocol or
external integration and does not refresh the frontier registry. No frontier
candidate affects the fail-closed Product/SKU accounting predicate.

## 6. Remaining evidence gates

The following remain `BLOCKED_EVIDENCE` and must be supplied by later named,
exact-scope authorities before any “real SKU full lifecycle cash loop” claim:

1. one current Ozon offer deterministically mapped to the canonical Product;
2. complete order-line pagination and one unambiguous SKU identity;
3. a signed current return/refund policy and observation-window closure, or a
   reconciled non-zero return/refund adjustment for the same line;
4. independent platform settlement, bank and Evidence lineage for the same
   order without proportional allocation.

Engineering completion cannot create a Fact, FinanceEntry, Approval, Permit,
external write, real SKU result or market claim.
