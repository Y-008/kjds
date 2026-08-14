# BAS-203 Strategic Capital Dashboard Evidence

## Scope and result

- Task: `BAS-203`
- Base commit: `349eaf9530e44ea897180fa32af85fee12c87568`
- Server contract: `kjds-strategic-capital-dashboard-v1` / `1.0.0`
- HTTP surface: one authenticated `GET /v1/strategic-capital-dashboard`
- Web surfaces: `/strategy-center` and `/portfolio-cockpit`
- Migration, dependency and database-schema changes: none
- POST, command, provider, network and external-write paths: none

This slice adds one read-only, server-owned aggregation boundary. It does not
recalculate a Fact, benchmark leader, gap, opportunity, experiment Gate,
capital ranking, budget authority or outcome. It presents existing authoritative
read projections and preserves missing production adapters as explicit
`not_connected`, `no_data` or `UNKNOWN` states.

## Exact current authority and temporal boundary

The browser supplies only a store selected from the authenticated server
session. The service derives tenant/entity/current authority from `Principal`
and `ScopeGrantAuthority.current(trusted_now)`. The caller's data `as_of` is
kept separate from the trusted authority check, cannot be in the future and
cannot rewind a later rotation or revocation.

Primary Source Intake and Strategic Benchmark were tightened so list/get bind
tenant, entity, store, current authority, valid-time cutoff and transaction-time
cutoff. Their trusted internal dashboard calls also pass an
`expected_scope_authority_sha256` seam. A mismatch fails non-enumerably before
projection, while routers expose neither that internal parameter nor the raw
authority hash. The dashboard rechecks current authority after every section is
read; an in-flight rotation invalidates the whole response.

The connected read-role intersection is exactly `operator`, `reviewer`,
`compliance`, `monitor` and `admin`. The API does not admit a role that either
upstream service would silently reject.

## Source and citation aggregation

The eight sections and their display order are frozen as:

1. `primary_source_coverage`
2. `strategic_benchmark`
3. `strategic_gaps`
4. `opportunity_portfolio`
5. `experiment_portfolio`
6. `capital_proposals`
7. `verified_outcomes`
8. `invalidation_review`

Every section carries the canonical content seal of its registered upstream
contract. Registry loading recomputes those source-registry seals and fails on
drift. Production composition connects only Primary Source Intake and Strategic
Benchmark because those two have current persisted read services. Gap Graph,
opportunity, experiment, capital proposal, outcome and invalidation-review
production adapters remain explicitly `not_connected`; repository synthetic
fixtures are never loaded into runtime.

Primary Source citations are HMAC-derived opaque `psc_...` tokens bound to
section, tenant, entity, store, current authority, source id and source hash.
Raw Evidence ids and raw authority hashes do not enter dashboard JSON. Tokens
cannot be replayed across scope, authority or source-hash rotation. Every
available section requires at least one citation, one invalidation condition and
one safe reason. `ready`/`partial` also require display data;
`stale`/`invalidated` retain citations but expose zero display items.

Primary multi-pack time is conservative: aggregate `data_as_of` is the earliest
selected cutoff, `effective_at` is the latest effective instant,
`recorded_at` is the latest recording time and `review_due_at` is the earliest
review deadline. Nonterminal pagination and latest-key ties return `UNKNOWN`
rather than claiming a current aggregate.

Strategic Benchmark preserves explicit upstream state:
`invalidated` dominates, then `stale`; all-`no_data` remains `no_data`; mixed
comparable/non-comparable data is `partial`. No invalidated or stale display
row is retained. A bounded nonterminal page and a latest timestamp tie fail
closed.

## HTTP and Web response contract

The API uses extra-forbid Pydantic models and a status-discriminated section
union:

- `ready` / `partial`: required projection, four times, Evidence citation,
  display item and invalidation condition;
- `stale` / `invalidated`: required projection, times, citation and
  invalidation condition with an empty display list;
- `no_data` / `not_connected` / `UNKNOWN`: null projection/times and empty
  citation/display/invalidation lists.

Top-level validation requires exactly eight unique sections in frozen order,
matching display indexes and the same opaque scope binding. OpenAPI emits the
three section modes as `oneOf` with a `status` discriminator.

Both Web pages were detached from `SellerOsConsole`; they no longer execute its
Ozon impact POST. They first resolve `/auth/session`, honor the existing
401-to-login and 428-to-MFA transitions and accept only a store returned by the
server session. There is no hard-coded default store. A strict runtime validator
checks exact keys, contract/version, section order, common scope binding,
available/unavailable field matrices, literal false authority flags and all ten
zero side-effect counters before rendering. Missing values are not converted to
zero, candidates are not sorted and the client performs no ranking, percentage,
FX, budget or Gate calculation.

## Production truth preserved

- `global_top1_claim=false`
- `production_admission=false`
- `budget_authority=false`
- Evidence, Fact, FinanceEntry, Graph, Approval, Permit, Pilot, Outbox,
  network and external-write counters are all literal zero.
- BAS-200/BAS-201 synthetic contracts are not presented as current operating
  results.
- BAS-204 outcome/reconciliation remains `not_connected`/`no_data`/`UNKNOWN`.
- COM-002 external blockers and C0 `not_for_sale` remain unchanged.

## Regression evidence

The real integration Gate creates actual SQLite-backed
`PrimarySourceIntake` and `StrategicBenchmarkKernel` projections, reads both
through one dashboard, verifies `ready/ready`, opaque citations, valid cutoffs
and no raw Evidence/authority leakage, then rotates the shared current authority
and proves both old projections disappear as `no_data/no_data`.

Negative tests cover tenant/entity/store/current-authority drift, historical
authority rewind, recorded-after-cutoff rows, source contract/hash drift,
pagination, latest ties, citation scope/hash rotation, role mismatch, malformed
authority adapters, status/payload matrix drift, duplicate/order drift,
cross-scope section hashes, stale display leakage, nonzero authority/write flags
and Web session/store mismatch.

## Verification record

Working directory: `D:\KJDS\kjds-bas203`

```text
D:\KJDS\kjds\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_strategic_capital_dashboard.py tests/test_strategic_capital_dashboard_api.py tests/test_primary_source_intake.py tests/test_strategic_benchmark.py
111 passed, 1 warning; exit 0

in-memory sealed-checkout shim + pytest tests/test_strategic_benchmark_api.py tests/test_strategic_capital_dashboard_api.py tests/test_primary_source_intake_api.py tests/test_api_contract.py
87 passed, 1 warning; exit 0

node --test lib/*.test.ts
142 passed; exit 0

D:\KJDS\kjds\web\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.bas203-check.json
exit 0; temporary config and declarations deleted after the check

D:\KJDS\kjds\.venv\Scripts\ruff.exe check --no-cache <all changed Python paths>
All checks passed!; exit 0

D:\KJDS\kjds\.venv\Scripts\python.exe scripts/verify_secrets.py
Secret scan passed: 1348 non-ignored worktree files and 1363 historical paths checked; exit 0

git diff --check
exit 0

git diff --cached --check
exit 0; staged path count 0

OpenAPI canonical export through the sealed checkout shim
SHA256=e1512ef0f25f98247657af43ca38401a04faf28dacd9c1baa23671b8a2aec0f5;
dashboard section oneOf branches=3; public StrategicBenchmark authority field=false
```

Final focused counts, Ruff, secret scan, OpenAPI, diff checks and frozen path
hashes are recorded in the BAS-203 handoff after the final byte freeze.
