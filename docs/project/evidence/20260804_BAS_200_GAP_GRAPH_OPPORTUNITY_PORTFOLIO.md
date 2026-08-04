# BAS-200 Governed GapGraph Opportunity Portfolio Evidence

## Scope and result

- Task: `BAS-200`
- Base commit: `4415eda5ac37a94c9aa3b1525d55999708325ca2`
- Deep module: `GovernedGapGraphWorkspace.evaluate(principal, store_ref, as_of, portfolio_ref)`
- Result type: immutable, content-addressed `GapGraphObservation`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none
- Data class: repository-owned synthetic contract fixture only
- External/network/platform writes: zero

This Gate establishes a read-only, exact-scope decision projection. It does not
create a second PrimarySource, StrategicBenchmark, Retrieval, canonical Graph or
profit truth. Upstream data is accepted only through a narrow read-authority
bundle and an independent citation-authority receipt.

## Reused truth boundaries

| Source | Reused contract | Eligible use |
| --- | --- | --- |
| PrimarySource | `kjds-primary-source-intake-v1` | current problem evidence |
| StrategicBenchmark | `kjds-strategic-benchmark-kernel-v1` | dimension/cohort/window comparison only |
| BAS-173 retrieval | `kjds-retrieval-benchmark-observation-v1` | cited retrieval observation |
| canonical Graph | `kjds-canonical-graph-temporal-read-v1` | temporal read projection only |
| profit truth | `kjds-profit-truth-readiness-v1` | bounded policy claims only |

Every source binding freezes tenant, entity, store, current authority SHA-256,
data `as_of`, contract/version, source reference, Evidence id/hash/source/ref,
`recorded_at`, effective interval and claims hash. All five bindings share one
exact scope and one data cutoff. Current authorization is checked at trusted
server time on every invocation; a historical data cutoff cannot rewind an
authority rotation or revocation.

## Admission model

### Nodes and edges

- Every node and edge resolves to a current, exact-scope, content-addressed
  citation receipt with a verified source contract and valid-time interval.
- Citation currentness is revalidated at trusted server time before every cache
  replay; the historical data cutoff is used only for recorded/effective-time
  eligibility.
- `generated` and `inferred` projections remain observations and are never Gate
  eligible.
- `causes/causal` requires the frozen independent causal-authority contract,
  a separate authority adapter, exact-scope current receipt, receipt hash and
  Evidence claims binding. Ordinary canonical-Graph citations cannot satisfy
  that authority. Without it, the result is `UNKNOWN/not_admitted` rather than
  a causal extrapolation.
- `supports`, `compared_with`, `depends_on` and `causes` have distinct
  relation/source/derivation/authority eligibility rows.
- No canonical Graph node or edge is written.

### Benchmark gaps

- Gap comparison is bound to one metric, cohort, market and effective window.
- The output carries `global_top1_claim=false`; a dimension leader is not
  promoted to a universal market leader.
- Cohort, window, comparison-state, source hash or required-edge drift blocks
  the gap.

### Opportunity portfolio

The frozen strategy set is `build/buy/partner/defer/no_action`. Selection
requires all alternatives to be known, all dependencies admitted, all
invalidation conditions present, and these independent policy projections:

- decision policy id/version/hash and alternatives hash;
- maximum-loss status, finite non-negative value, unit and policy id/version/hash;
- downside status, finite non-negative value, unit and policy id/version/hash;
- rollback status, artifact hash, trigger codes and policy id/version/hash.
- invalidation conditions and rollback trigger codes are themselves frozen as
  canonical claim hashes, rather than trusted as uncited control text.

Each policy claim is projected from its declared source item and bound to an
independently verified Evidence claims hash. A missing, stale or `UNKNOWN`
input produces `not_admitted` and `selected_action=no_action`. Immutable actor
or source-content drift under the same replay scope raises
`GapGraphConflictError` instead of returning an action.
Exact-scope failures after source admission return a citation-free no-action
stub; pre-scope failures return no portfolio detail.

## Preserved uncertainty states

`no_data`, `UNKNOWN`, `blocked`, `not_visible`, `stale` and `partial` remain
distinct. They are not averaged into a score and none can satisfy a hard Gate.
Raw sensitive values, email-like values, provider identifiers and credential
field names are rejected before request hashing or output projection.

## Determinism and isolation

- Registry, fixture, source, item, request, node, edge, gap, opportunity and
  observation identities use canonical JSON SHA-256.
- Same exact scope/authority/cutoff/portfolio and byte-equivalent source
  projection plus verified citation receipts replays byte-equivalently across
  workspace instances even when the trusted check clock advances.
- A cached ready result is never returned until current scope and every
  citation and independent causal-authority receipt have been revalidated.
- Ready request identity includes normalized citation and causal-authority
  receipt fingerprints. Blocked request identity includes normalized status,
  reason codes, source statuses and the content-addressed failing citation or
  causal-authority subject, so distinct failures cannot share a run ID.
- Same idempotency scope with actor or source-content drift conflicts.
- Tenant/entity/store/authority drift returns no nodes, edges, gaps or
  opportunities. Rotation/revocation is checked before the replay cache.
- Duplicate IDs, orphan edges and dependency cycles fail during fixture
  admission; valid opportunity DAGs execute in stable topological order.

## Zero-authority conservation

The registry, every ready result and every blocked result preserve literal zero
authority for:

`Fact`, `FinanceEntry`, `Approval`, `Permit`, `Pilot`, `Outbox`, canonical Graph
write, dependency installation, network and external write.

## Verification record

Working directory: `D:\KJDS\kjds-bas200`

```text
D:\KJDS\kjds\.venv\Scripts\python.exe -m pytest -q tests/test_gap_graph.py --basetemp D:\KJDS\pytest-bas200-p1-5
...............................................................          [100%]
63 passed in 1.37s
exit 0

D:\KJDS\kjds\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/gap_graph.py tests/test_gap_graph.py
All checks passed!
exit 0

git diff --check
exit 0
```

Covered negative contracts include current scope and authority rotation/revoke,
future/stale/tampered citation, source binding drift, benchmark cohort/window and
global-Top1 drift, inferred and independently unsupported causal edges, policy
claim/invalidation/rollback-trigger drift, every strategic Gate `UNKNOWN`,
duplicate/orphan/cyclic fixture structures, stable forward dependencies, unsafe
projections, cross-workspace replay, cached citation/causal-receipt revocation,
distinct blocked-run identities across both subjects and failure kinds, and
immutable-input conflict.

## Artifact hashes

The final handoff records filesystem SHA-256 for all five allowed files after
the final secret scan and dual read-only review. Registry and fixture also carry
their own canonical content hashes and reject content drift during load.

## UNKNOWN retained

- real customer opportunity coverage and real market uplift;
- production source latency, availability, P95/P99 and operating cost;
- real monetary maximum-loss/downside values and Finance/Risk signatures;
- independently admitted real causal-edge authority;
- human portfolio review throughput and production action-selection thresholds.

No production `selected_action` or external execution is implied by this
synthetic engineering Gate.
