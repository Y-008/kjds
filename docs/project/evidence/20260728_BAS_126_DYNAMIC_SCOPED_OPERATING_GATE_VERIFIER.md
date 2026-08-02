# BAS-126 Dynamic Scoped Operating Gate Verifier — Engineering Evidence

## Decision

`BAS-126` engineering acceptance is `PASS`. Release, Pilot and Final Gates remain
open. This Evidence proves a dynamic verification mechanism; it does not provide the
missing owner decisions, source artifacts, real candidates, orders, settlements or
bank records.

## Implemented contract

- Requirement: `BR-102`
- Architecture: `ADR-0050`
- Pure deep module:
  `apps/control_plane/operating_gate_verifier.py`
- Runtime adapter:
  `scripts/seed_m0_m4_gate_graph.py`
- State authority:
  authenticated `CommerceOperatingSystem.workspace()` plus real PostgreSQL aggregate
  support observations
- Sink:
  registered `m0m4-commerce-os@1` Agent Harness verifier with a one-hour freshness
  window

The module has one public `evaluate()` seam and performs no I/O. It validates the
Commerce OS contract, exact thirteen-stage set, qualified-record counts, current
scope, source snapshots, formal Fact and real-profit-loop claims, support counts and
the complete closed external-write/self-approval envelope. It then derives M0→M4 in
strict order. A later stage cannot pass when an earlier stage is not passed.

The observer uses the UTC hour boundary as the Commerce OS `as_of` and hash bucket.
The same semantic workspace and database counts replay to the same five input hashes;
a real source/count or bucket change creates new append-only observations. Observed
Commerce Graph nodes keep stable IDs while their version and content hash follow the
current verifier observation.

## Failure-closed verification

Focused interface tests cover:

- empty real-like workspace → M0 `no_data`, M1–M4 `blocked`;
- partial data cannot bypass missing formal Fact support;
- a fully complete scoped workspace and all support authorities → five `passed`;
- downstream completed stages cannot bypass an incomplete upstream Gate;
- missing stage, duplicate stage and open external write → five `failed`;
- deterministic same-bucket replay and hash change on count or bucket change.

Focused module plus Agent Harness regression: `11 passed`.

## Authority boundary

- `ready_for_internal_action` is not a completed Gate.
- A database row count cannot establish scope or business completion by itself.
- Model output is not a business Fact and cannot certify a TODO.
- The observer records only aggregate counts and content hashes; it does not copy
  business payloads or credentials into Graph state.
- No Fact, Approval, Permit, accounting entry, Ozon write, supplier message,
  purchase, payment, price, inventory or advertising action is created.
- External writes remain `false`.

The live project is expected to remain blocked until actual owner-controlled inputs
arrive. A blocked result is the correct observation, not a failed engineering test.

## Live acceptance

The real adapter observed Alembic `20260728_0067` and an authenticated Commerce OS
workspace at UTC bucket `2026-07-28T12:00:00+00:00`:

- current entity scope: absent;
- formal Fact count: `0`;
- all twelve support counts (grant, native import/Product/Fact, content asset,
  profit scenario, listing draft, native Pilot, limited-execution receipt, order,
  finance entry and reconciliation run): `0`;
- result: M0 `no_data`; M1–M4 `blocked`;
- result SHA-256:
  `930e25e08772c15e88333aea8190334d63efa580ce7c932753d5c3355f54dcba`.

Two consecutive seed executions in the same bucket produced the same result hash and
the same `17 tasks / 22 observations / 43 nodes / 39 edges`; no replay row was added.
The live aggregate API and all seven Graph projections returned `200`, with `12`
fresh passed engineering tasks, four blocked operating tasks, one no-data operating
task, zero failed/stale/pending tasks, project status `blocked`, external write
`false` and model self-certification `false`.

Current delivery-browser acceptance at `1280×720` showed `17/43/39`, M0 no-data,
M1–M4 blocked and the persistent fresh five-attention status rail. Document
`clientWidth` and `scrollWidth` both measured `1265`; the rail was bounded at
`830.8..1250.8px`; browser logs were empty. The existing real `390×844` acceptance
from BAS-125 remains applicable because BAS-126 changes no Web source or responsive
layout; the Web contract suite continues to assert the explicit 390px bounds.

Final quality:

- backend: `761 passed`, 9 third-party deprecation warnings;
- Ruff: clean;
- Web: `55 passed`;
- production build: `33/33` pages, 33 routes;
- dependency audit: `0 vulnerabilities`;
- secret scan: `735` non-ignored worktree files and `581` historical paths;
- `git diff --check`: no whitespace errors (line-ending notices only);
- PostgreSQL, API, media worker and Web delivery containers: healthy.
