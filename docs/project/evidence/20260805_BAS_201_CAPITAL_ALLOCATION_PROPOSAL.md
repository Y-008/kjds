# BAS-201 Governed Capital Allocation Proposal Evidence

## Scope and result

- Task: `BAS-201`
- Base commit: `dd5f68acf8202c6a7b98d71e4a8721668d902353`
- Deep module: `GovernedCapitalAllocationWorkspace.evaluate(...)`
- Result: immutable, content-addressed `CapitalAllocationObservation`
- Data class: repository-owned synthetic contract fixture only
- Migration, API, router, OpenAPI, runtime and dependency changes: none
- Database, provider, network and external writes: zero

This slice establishes the read-only contract and deterministic proposal Gate.
It does not create a capital ledger, approve a budget, initiate a payment,
select a security, mutate the canonical Graph or claim production admission.
The frozen synthetic fixture proves only the shape and fail-closed behavior of
the contract. Its selected production option remains `no_action` and
`production_admission=false`.

## Reused truth boundaries

| Projection | Eligible use | Explicitly ineligible use |
| --- | --- | --- |
| BAS-200 GapGraph | admitted opportunity, dependencies, alternatives, loss/downside/rollback shape | second Graph truth or action authority |
| StrategicBenchmark | bounded comparison and current benchmark status | global Top1 or causal proof |
| board-approved capital constraints | treasury balance, cash floor, runway, budget cap, maximum loss and signed finance thresholds | caller-entered money or synthetic production authority |
| ProfitTruth | cash CM3 and downside CM3 observation | treasury cash balance, cash floor, runway or available budget |
| settlement cash | settled platform cash observation | treasury balance or capital authority |
| Growth outcome | independently verified causal outcome/readiness | automatic capital approval |
| COM-002 commercial lifecycle | settled-only entitlement and commercial blockers | treasury cash, payment authority or C0 release |

The only admitted source for treasury cash, cash floor, runway, budget cap and
signed investment constraints is the Grade-A
`board_approved_cash_runway_and_investment_constraints` projection with
eligible output `capital_constraint`. A zero commercial outstanding balance or
positive `actual_cash_cm3` therefore never satisfies the treasury Gate.

Every source projection is bound to exact tenant/entity/store/current-authority
scope, source contract/version, projection reference and hash, data cutoff,
Evidence id/hash/source/ref/grade, recorded time and effective interval. Current
scope authority is revalidated at trusted server time on every invocation. A
historical data cutoff cannot rewind a rotation or revocation.

## Five-option noncompensatory Gate

The option universe is exactly:

`build`, `buy`, `partner`, `defer`, `no_action`.

Each actionable option carries current evidence coverage, dependencies, owner,
primary metric, guardrails, stop conditions, rollback, invalidation/review date,
timebox, downside/base/upside, payback, TCO, maintainability, reversibility and
replacement-cost fields. Before comparison, the workspace independently blocks
an option when any of the following is missing, unknown, stale or drifted:

- exact current scope and source authority;
- board-approved treasury cash floor, runway and signed finance thresholds;
- evidence, license/privacy and causal-growth eligibility;
- budget, maximum loss, downside, payback and timebox constraints;
- rollback, acceptance, dependencies, owner, metrics, guardrails or stop rules;
- the complete build/buy/partner/defer/no-action comparison.

Hard dimensions are not averaged into an equal-weight score. Only options that
pass every hard Gate enter a deterministic five-option lexicographic comparison,
including `no_action`. Even the
all-green synthetic fixture records only `synthetic_best_feasible`; it cannot
change `selected_option=no_action`, `proposal_status=not_admitted` or
`production_admission=false` without independent real finance authority.

Every monetary value in policy, option and comparison shapes is one exact
`Money` object: amount microunits, currency, occurred/effective time and
Evidence ref/hash. Repository option Money proves only synthetic schema shape;
it is never promoted to real finance authority. Cross-currency comparison has
no fallback FX path and is blocked. Option review dates must be after the data
cutoff, no later than the earliest source-Evidence expiry, and still current at
trusted invocation time. An expired review invalidates every action and bypasses
any earlier cached synthetic winner.

## Preserved UNKNOWN and commercial boundary

Current real board-approved cash balance, cash floor, runway, downside CM3,
payback, finance thresholds and operating uplift remain `UNKNOWN`. COM-002 also
remains `IN_PROGRESS_PREP_ONLY`/`not_for_sale`; its hosted target and RPO/RTO,
payment/invoice/tax and Contract/DPA/SLA blockers plus the outer C0 commercial
Gate are not released by this slice.

Currency mismatch is blocked unless a current exact-scope FX authority exists;
this slice includes no FX authority and therefore fails closed. Generated or
inferred values, correlations, commercial entitlement balances, settlement
totals and profit CM3 cannot replace treasury authority.

## Determinism and isolation

- Registry, fixture, source bundle, citations, request and observation identities
  use canonical JSON SHA-256.
- Same exact scope, actor, current authority, cutoff, portfolio and source bundle
  replays byte-equivalently across workspace instances.
- The winner key excludes actor/current authority while the full request
  fingerprint includes them; actor or authority drift under the same key raises
  a typed conflict before returning portfolio detail.
- Duplicate option/source ids, missing five-option alternatives, orphan
  dependencies and dependency cycles fail during contract admission.
- Scope mismatch, revocation, citation failure or adapter exception produces a
  citation-free blocked observation with safe reason codes and no raw exception
  text, customer text, secrets or provider identifiers.

## Zero-authority conservation

Every result fixes `proposal_only=true` and preserves literal zero/false for:

`Fact`, `FinanceEntry`, `Approval`, `Permit`, `Pilot`, `Outbox`, canonical Graph
write, dependency installation, payment, securities investment, network and
external write. Self-review, self-approval and self-promotion are absent.

## Verification record

Working directory: `D:\KJDS\kjds-bas201`

```text
D:\KJDS\kjds\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=D:\KJDS\.runtime\pytest-bas201-p5 tests/test_capital_allocation.py
........................................................................ [ 70%]
..............................                                           [100%]
102 passed in 1.29s
exit 0

D:\KJDS\kjds\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/capital_allocation.py tests/test_capital_allocation.py
All checks passed!
exit 0

D:\KJDS\kjds\.venv\Scripts\python.exe scripts/verify_secrets.py
Secret scan passed: 1337 non-ignored worktree files and 1358 historical paths checked
exit 0

deterministic three-workspace replay
REPLAY_HASHES=da11df0dc6948dd5b227d2c95721b89bfe3745539409d2452893e0e43a8d924d,da11df0dc6948dd5b227d2c95721b89bfe3745539409d2452893e0e43a8d924d,da11df0dc6948dd5b227d2c95721b89bfe3745539409d2452893e0e43a8d924d
REPLAY_MATCH=True
STATUS=blocked
SELECTED_OPTION=no_action
PROPOSAL_STATUS=not_admitted
PRODUCTION_ADMISSION=False
REASON_CODES=acceptance,real_finance_authority
ZERO_WRITES=True
```

Negative coverage includes all four scope dimensions, authority rotation/revoke,
future/stale/hindsight Evidence, source contract/reference/hash/version drift,
adapter failures, unsafe projection values, each noncompensatory Gate, currency
and money-bound drift across treasury/profit/settlement/commercial projections,
option budget/loss/downside/payback/timebox violations, dependency feasibility
propagation, GapGraph dependency-binding drift, duplicate/orphan/cyclic
dependencies, actor/authority replay conflict, safe scope/read/citation adapter
failures and the treasury-substitution attacks using entitlement outstanding or
positive cash CM3. It also covers every policy/option/comparison Money family,
missing currency/time/Evidence, expired or Evidence-beyond review dates,
runtime review expiry after a cached pre-review call and complete no-action
proposal fields.

Final handoff records the filesystem SHA-256 for all five authorized files after
the secret scan, deterministic replay, dual read-only review, staged diff check
and verified rollback.

## UNKNOWN retained

- real board-approved treasury balance, cash floor, runway and signed thresholds;
- real downside/base/upside CM3, payback and capital return;
- current independently admitted FX, license/privacy and causal-growth authority;
- production latency, operating cost and observed uplift;
- external payment, tax, invoice and Contract/DPA/SLA decisions;
- any production budget selection, approval or execution.

No executable capital allocation is implied by this synthetic engineering Gate.
