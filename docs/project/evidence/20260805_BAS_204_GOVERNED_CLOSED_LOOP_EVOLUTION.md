# BAS-204 Governed Closed-Loop Evolution Evidence

## Scope and result

- Task: `BAS-204`
- Base commit: `230ecc5eb66fc9e525ba5089673a56c3b99f556c`
- Contract: `kjds-governed-closed-loop-evolution-v1` / `1.0.0`
- Migration: `20260805_0096`
- Deep module: `GovernedClosedLoopEvolutionWorkspace`
- Production causal claims: disabled
- Candidate creation, transition and promotion: disabled
- Fact, FinanceEntry, Approval, Permit, Pilot, Outbox and external writes: zero
- New command, POST, provider, network and public OpenAPI surface: none

This slice establishes an append-only, exact-scope Evidence ledger for one
closed-loop evolution observation. It binds a governed AgentRun to independent
experiment, cost and business-outcome authority receipts, preserves valid-time
and transaction-time cutoffs, and emits only an observation handoff for
BAS-177. It does not create or promote a TeamAgent candidate, assert a causal
business result, change code or permissions, approve spend, or execute an
external action.

## Exact authority and independent Evidence

Tenant, entity, store and current scope authority are derived from `Principal`
and `ScopeGrantAuthority.current(trusted_now)`. Caller data `as_of` remains a
separate historical cutoff and cannot rewind a later authority rotation or
revocation. Scope is checked before admission, after authority reads, before
commit and before a read projection is returned.

The three supporting purposes are exactly `experiment`, `cost` and
`business_outcome`. Each uses a separately registered Grade-A issuer contract,
schema seal, database principal and canonical Evidence envelope. A fourth
independent review authority is required for review, invalidation, revocation
or supersession events. Issuer actors must be distinct from each other, the
bundle recorder and the review requester. A receipt cannot be reused across
purpose, scope, authority, event, bundle or replacement.

Authority payloads, claims, metadata, scope objects, root requests, bundle
snapshots and event requests use exact key sets with no additional properties.
Payload status and customer-data/external-write flags are fixed to their safe
values. PostgreSQL recomputes or binds canonical hashes rather than accepting a
caller-provided digest as authority. Reserved Evidence sources cannot be
captured, listed, downloaded, scanned or linked through the generic Evidence
surface.

## Governed AgentRun boundary

The workspace consumes the BAS-172 governed AgentRun read authority instead of
reconstructing run truth. It validates the complete event prefix, ordinals,
hash chain, terminal `run_succeeded` event, governed receipt, exact scope and
every event Evidence record/blob at the common data cutoff and trusted current
time. Late-recorded, future, stale, revoked, tampered or nonterminal Evidence
fails before a bundle is written.

AgentRun Evidence metadata is exactly the canonical eleven-field contract with
`retention_class=security` and `legal_hold=false`. Safe event payloads are
frozen by event type, including their key sets, scalar/list types and ranges.
The database independently rejects a jointly re-signed run row and Evidence
blob carrying an extra or malformed payload.

## Temporal and causal boundary

All supporting Evidence must satisfy:

`recorded_at <= data_as_of <= authority_checked_at < review_due_at <= effective_until`.

Experiment, cost and outcome windows end no later than the common data cutoff.
AgentRun event and Evidence recording times also end no later than that cutoff.
Historical reads validate only the event prefix visible at their transaction
cutoff; later review events cannot leak backwards. Current scope authority and
Evidence validity are still checked at trusted current time.

Version 1 fixes `causal_claim_allowed=false`. Method labels, sample sizes,
confidence values or authority-provided booleans cannot turn an association
into causality. Monetary outcome metrics require an explicit ISO currency and
must agree with the cost currency; no implicit FX path exists. The BAS-177
handoff therefore uses `association_only_outcome` and
`learning_eligibility=observation_only`.

Authority admission is exactly representable in PostgreSQL before any
Evidence write: confidence is constrained to `NUMERIC(8,6)` and the outcome
value to `NUMERIC(30,12)` with fewer than 18 integer digits. Value-changing
excess scale and numeric overflow fail closed; trailing-zero overrepresentation
is accepted without rounding.

## Append-only ledger and atomicity

Migration 0096 adds canonical bundle, supporting-link and review-event rows,
authority receipt and issuance relations, named deferred conservation
constraints, immutable triggers and a hash-chained event stream. The first
`bundle_recorded` event is bound to the root actor, idempotency key, request
hash and trusted record time. Review events bind an independent current
authority receipt; supersession additionally binds an exact-scope current
replacement bundle.

The AgentRun prefix must begin with a fully bound `run_started` event. Python
and PostgreSQL use strict integer-not-boolean payload checks, exact JSON key and
null matrices, and literal JSON booleans. Jointly re-signing row and Evidence
JSON cannot introduce a false textual boolean, null required field or skipped
first event.

The Grade-D event Evidence issuer is a fixed-search-path SECURITY DEFINER
boundary, separate from the Grade-A authorities. It runs through the same
SQLAlchemy Session and transaction as the bundle/event insert. Generic runtime
code cannot insert a reserved event Evidence row directly or read private
receipt tables. An issuer-only commit, an event-row failure or a deferred
constraint failure rolls back the Evidence record/blob and every bundle, link
and event row in the same transaction.

Same-scope, same-key concurrent writers produce one bundle and one Evidence
set. The loser returns the byte-equivalent immutable winner. Actor, request,
authority or content drift under that key fails before an additional write.
Read-time verification recomputes root, request, bundle, link and event seals
and revalidates their Evidence, so database corruption cannot be projected as a
current observation.

## Migration and privilege lifecycle

Upgrade obtains the shared lifecycle advisory lock before any 0096 mutation.
It rejects pre-existing reserved Evidence, related or orphan lineage and stale
closed-loop catalog objects while preserving the 0095 database byte-for-byte.
It does not adopt, alter or delete pre-existing roles without an exact ownership
receipt.

The managed privilege surface is an exact 15-cell matrix. Upgrade records each
cell's direct/effective baseline and grants only privileges absent from the
baseline. Receipt rows are immutable, including against a privileged owner and
TRUNCATE. Downgrade revalidates the receipt hash, all role attributes, both
membership directions, managed cells and non-managed ACLs before any mutation;
it revokes only privileges introduced by 0096. Mixed direct/PUBLIC baselines
and PostgreSQL NULL default ACL normalization restore to the same effective
privilege set without writing system catalogs.

A populated ledger blocks downgrade with SQLSTATE `55000` and preserves the
0096 head and all data. An empty database replays exactly through
0096 -> 0095 -> 0096, including relation, function, trigger, role and membership
catalog projections.

## Read-only projections

BAS-203 receives two server-owned adapters: `verified_outcomes` and
`invalidation_review`. They expose opaque, scope-bound citations and safe
summaries only. Current bundles produce a non-empty no-review-due display item;
review-due, invalidated, revoked and superseded states use the latest visible
event time and never retain actionable display data. Every projected item keeps
all write, candidate, transition and promotion flags at zero/false.

The BAS-177 handoff is a typed immutable observation sealed with a server-owned
HMAC over its full payload. It binds opaque scope and citation tokens, bundle
and event hashes, status, reason, times and invalidation conditions. Recomputing
an unkeyed content hash after changing `invalidated` to `ready` cannot forge a
valid handoff.

## Verification record

Working directory: `D:\KJDS\kjds-bas204`

```text
in-memory sealed-checkout line-ending shim + memory repository + per-run sealing key
uv run pytest (core six-file focused batch)
tests/test_evidence.py tests/test_evidence_integrity.py
tests/test_closed_loop_evolution.py tests/test_strategic_capital_dashboard.py
tests/test_strategic_capital_dashboard_api.py tests/test_health_loop.py
211 passed, 1 warning in 14.61s
exit 0

uv run pytest (API/G1/integration five-file focused batch)
tests/test_security.py tests/test_api_contract.py tests/test_g1_harness_contract.py
tests/test_growth_composition_integration.py tests/test_optional_provider_boundaries.py
87 passed, 2 cross-thread in-memory SQLite harness failures, 1 warning in 12.00s
the two harness-affected API nodes passed with a shared temporary SQLite file
2 passed, 2 warnings in 0.57s; temporary database removed
exit 0

.venv/Scripts/python.exe -m pytest -q tests/test_closed_loop_evolution.py
129 passed in 9.28s
exit 0

.venv/Scripts/python.exe -m pytest -q tests/test_closed_loop_evolution_postgres.py
101 passed, 12 warnings in 42.14s
exit 0

disposable PostgreSQL 17 cluster + tests/test_global_data_coverage_ledger_postgres.py
76 passed, 12 warnings in 21.89s
container cleanup PASS; main-cluster pre-existing GDC roles unchanged
exit 0

uv run ruff check <changed Python paths>
All checks passed!
exit 0

D:\KJDS\kjds\.venv\Scripts\python.exe scripts/verify_secrets.py
Secret scan passed: 1355 non-ignored worktree files and 1376 historical paths checked
exit 0

git diff --check
exit 0

git diff --cached --check
exit 0; staged path count 0

post-PostgreSQL cleanup
management Alembic head=20260803_0094
target databases=0; ephemeral CLOE/G1 roles=0; fixed leases=0
```

Named PostgreSQL coverage includes workspace record/replay/review, record and
review deferred-failure rollback, issuer-only orphan rollback, two-session
concurrent winner/replay with drift rejection, populated downgrade rejection,
empty downgrade/re-upgrade replay, legacy reserved-source preflight, the
15-cell ACL matrix, dynamic role/membership drift, ORM/migration catalog parity
and named deferred-constraint attribution.

This evidence record does not by itself authorize release or production use.
Final acceptance remains bound to the frozen file hashes, independent review
and repository final Gates.

## UNKNOWN retained

- real independently verified business uplift and causal effect;
- real estimator, confidence interval, randomization integrity, attrition and
  parallel-trends authorities;
- real production experiment, cost, outcome and review receipts;
- external payment, finance, tax, contract, provider or network authority;
- BAS-177 candidate creation, Shadow transition, promotion or rollback approval;
- any production change, budget action or commercial Gate release.
