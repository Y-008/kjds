# 20260819 BR-150 Multi-Session Pilot Verification

## Metadata

- Date: 2026-08-19
- Scope: single-process TeamAgentCoordinator pilot verification for multi-session, multi-thread, multi-subagent orchestration
- Requirement: BR-150
- ADR references:
  - ADR-0102
  - ADR-0103
  - ADR-0104
- External write: false
- Business truth promotion: false
- Runtime durable completion claimed: false
- Runtime `0099 + 0100` reconcile claimed: false
- Multi-replica / cross-process production orchestration claimed: false

## Exact files reviewed

- `AGENTS.md`
- `docs/project/MASTER_SPEC.md`
- `docs/adr/ADR-0102-harness-graph-teamagent-orchestration-resilience.md`
- `docs/adr/ADR-0103-teamagent-postgresql-persistence-cas.md`
- `docs/adr/ADR-0104-teamagent-runtime-durable-session-checkpoint.md`
- `apps/control_plane/runtime.py`
- `apps/control_plane/agent_team_orchestration.py`
- `apps/control_plane/routers/agent_control.py`
- `apps/control_plane/team_agent_persistence.py`
- `apps/control_plane/team_agent_checkpoint_store.py`
- `tests/test_agent_team_orchestration.py`
- `tests/test_agent_team_orchestration_resilience.py`
- `tests/test_agent_team_orchestration_edge_contracts.py`
- `tests/test_agent_team_handoff_lineage.py`
- `tests/test_agent_team_router_guards.py`
- `tests/test_team_agent_checkpoint_store.py`
- `tests/test_team_agent_persistence.py`
- `tests/test_team_agent_persistence_postgres.py`

## Requirement boundary recorded

- BR-150 requires exact-scope multi-session control inside a single-process pilot, with per-session event-chain isolation, dependency barriers, handoff, leases, retry, circuit breaker, kill switch, checkpoint/restore, authority revalidation, and fail-closed worker identity rules.
- ADR-0102 defines the current orchestration boundary as an in-process, deterministic, side-effect-free control kernel rather than a second durable runtime authority.
- ADR-0103 defines `0099` as the task/lease/event CAS seam, but not as complete runtime session recovery.
- ADR-0104 keeps the runtime durable wiring gate `NOT PASSED` until sidecar restore reconciles against `0099` and multi-instance recovery tests pass.

## What is implemented and verified

### Single-process pilot boundary

- `runtime.py` currently composes `TeamAgentCoordinator()` directly in process.
- This confirms the active runtime boundary is still single-process pilot, not cross-process orchestration.

Evidence:

- `apps/control_plane/runtime.py`
- `docs/project/MASTER_SPEC.md`
- `docs/adr/ADR-0104-teamagent-runtime-durable-session-checkpoint.md`

### Multi-session / multi-thread / multi-subagent control

- `TeamAgentCoordinator` supports multiple sessions with bounded session capacity.
- Each session creates a root thread and may fork additional child threads.
- Tasks represent TeamAgent/Subagent work units and carry `thread_ref`, `agent_id`, `role`, dependency, idempotency, evidence, handoff, reviewer and budget fields.

Evidence:

- `apps/control_plane/agent_team_orchestration.py`
- `tests/test_agent_team_orchestration.py`
- `tests/test_agent_team_orchestration_resilience.py`
- `tests/test_agent_team_orchestration_edge_contracts.py`

### Exact-scope, authority and worker identity fail-closed boundaries

- Session creation records exact scope and optional `authority_sha256`.
- Cross-session dependency, parent-task and handoff scope drift are rejected.
- router guard revalidates current authority and requires `worker_id == authenticated actor`.

Evidence:

- `apps/control_plane/agent_team_orchestration.py`
- `apps/control_plane/routers/agent_control.py`
- `tests/test_agent_team_router_guards.py`

### Dependency barriers, handoff lineage, lease/retry/breaker, kill switch, checkpoint/restore

- dependency barriers block claim until upstream completion
- handoff requires exact scope, evidence and acceptance contract
- task lease, heartbeat, expiry reclaim, retry budget and provider circuit breaker are implemented
- pause / kill switch revoke active execution and fail closed
- checkpoint / restore validates hash, scope, references and event-chain integrity

Evidence:

- `apps/control_plane/agent_team_orchestration.py`
- `tests/test_agent_team_orchestration.py`
- `tests/test_agent_team_orchestration_resilience.py`
- `tests/test_agent_team_orchestration_edge_contracts.py`

### Control boundary remains observation-only

- Harness terminal publish remains observation-only and `external_write_allowed=false`.
- No review in this receipt proves Fact, FinanceEntry, Approval, Permit, marketplace write, Ozon current fact, order, fulfillment, settlement, bank or customer outcome.

Evidence:

- `apps/control_plane/agent_team_orchestration.py`
- `docs/project/MASTER_SPEC.md`

## Test execution record

### Focused orchestration capability run

Command executed:

```text
uv run pytest D:\KJDS\kjds\tests\test_agent_team_orchestration.py::test_multiple_threads_and_subagents_run_with_dependency_barrier D:\KJDS\kjds\tests\test_agent_team_orchestration.py::test_kill_switch_revokes_active_leases_and_stops_new_work D:\KJDS\kjds\tests\test_agent_team_orchestration.py::test_checkpoint_restore_and_event_merge_keep_session_chains_independent D:\KJDS\kjds\tests\test_agent_team_orchestration_resilience.py::test_structured_handoff_requires_exact_scope_evidence_and_contract D:\KJDS\kjds\tests\test_agent_team_orchestration_resilience.py::test_checkpoint_restore_tamper_scope_and_deterministic_snapshot D:\KJDS\kjds\tests\test_agent_team_orchestration_edge_contracts.py::test_cross_thread_dependency_barrier_waits_for_parent_completion D:\KJDS\kjds\tests\test_agent_team_orchestration_edge_contracts.py::test_kill_switch_cannot_be_cleared_through_pause_or_resume D:\KJDS\kjds\tests\test_agent_team_orchestration_edge_contracts.py::test_circuit_breakers_are_isolated_by_session_and_provider D:\KJDS\kjds\tests\test_agent_team_router_guards.py -q
```

Observed result:

```text
..........                                                               [100%]
10 passed in 1.41s
```

### PostgreSQL persistence suite status in current shell

Command executed:

```text
uv run pytest D:\KJDS\kjds\tests\test_team_agent_persistence_postgres.py -q
```

Observed result:

```text
sssss                                                                    [100%]
16 skipped in 0.32s
```

Interpretation:

- the repository defines PostgreSQL contract coverage for `0099` persistence and `0100` checkpoint-side tables
- this shell did not fresh-prove those contracts because `KJDS_TEAM_AGENT_DATABASE_URL` was unavailable to the test process
- this receipt therefore records the scope of those tests but does not upgrade them to a fresh executed proof here

## Transient failures observed during this verification

### T1: multi-session event-count test drift was real and then corrected

Initial broad command:

```text
uv run pytest D:\KJDS\kjds\tests\test_agent_team_orchestration.py D:\KJDS\kjds\tests\test_agent_team_orchestration_resilience.py D:\KJDS\kjds\tests\test_agent_team_orchestration_edge_contracts.py D:\KJDS\kjds\tests\test_agent_team_router_guards.py D:\KJDS\kjds\tests\test_team_agent_persistence_postgres.py -q
```

Observed intermediate result:

```text
36 passed, 1 failed, 5 skipped
```

The failing assertion was:

- `tests/test_agent_team_orchestration.py::test_multiple_sessions_isolate_idempotency_and_event_cursors`

Observed drift:

- `session-1` event stream actually contained:
  - `session.created`
  - `thread.forked`
  - `task.submitted`
- `session-2` event stream contained:
  - `session.created`
  - `task.submitted`

Interpretation:

- the session-isolation contract itself still held
- the failing expectation undercounted `session-1` because helper `_coordinator()` creates an additional thread before the task submit
- this was a test drift, not evidence that the two sessions had merged event chains

Action taken:

- the test was updated to explicitly assert `thread.forked` for `session-1`
- it continued to assert that event `session_ref` values do not cross sessions and that a cross-session cursor read fails closed

### T2: a later `_projection_clone` AttributeError was transient and not reproducible

After the test drift fix, one intermediate four-file run reported:

```text
35 passed, 2 failed
```

The two failures surfaced as:

- `tests/test_agent_team_orchestration.py::test_checkpoint_restore_and_event_merge_keep_session_chains_independent`
- `tests/test_agent_team_orchestration_resilience.py::test_event_cursor_merge_resume_and_conflicts`

Reported exception text:

```text
AttributeError: 'TeamAgentCoordinator' object has no attribute '_projection_clone'
```

Subsequent verification established:

- source inspection showed `_projection_clone()` is present in `apps/control_plane/agent_team_orchestration.py`
- direct interpreter inspection confirmed `hasattr(TeamAgentCoordinator, "_projection_clone") == True`
- rerunning the two failing tests alone produced:

```text
2 passed in 0.07s
```

Interpretation:

- this receipt does not treat that transient failure as a proved current production gap
- no reproducible code defect remained after source re-inspection and rerun

## Final rerun result used as the stable proof

Command executed:

```text
uv run pytest D:\KJDS\kjds\tests\test_agent_team_orchestration.py D:\KJDS\kjds\tests\test_agent_team_orchestration_resilience.py D:\KJDS\kjds\tests\test_agent_team_orchestration_edge_contracts.py D:\KJDS\kjds\tests\test_agent_team_router_guards.py -q
```

Observed result:

```text
.....................................                                    [100%]
37 passed in 1.49s
```

Ruff command:

```text
uv run ruff check D:\KJDS\kjds\tests\test_agent_team_orchestration.py D:\KJDS\kjds\tests\test_agent_team_orchestration_resilience.py D:\KJDS\kjds\tests\test_agent_team_orchestration_edge_contracts.py D:\KJDS\kjds\tests\test_agent_team_router_guards.py
```

Observed result:

```text
All checks passed!
```

## Continuation rerun after public-export hardening

The resumed verification added explicit detached exports for public thread and
handoff values. Nested handoff mappings are copied before crossing the public
API boundary. Test fixtures also create sessions and threads at the same fixed
`T0` / `AS_OF` used by later events; the production event-time regression guard
was not weakened.

Focused orchestration, edge, resilience, and handoff-lineage command:

```text
uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-resume-harness-focused-20260819 tests/test_agent_team_orchestration.py tests/test_agent_team_orchestration_edge_contracts.py tests/test_agent_team_orchestration_resilience.py tests/test_agent_team_handoff_lineage.py
```

Observed result:

```text
90 passed in 0.56s
```

Expanded seven-file command:

```text
uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-resume-harness-seven-20260819 tests/test_agent_team_orchestration.py tests/test_agent_team_orchestration_edge_contracts.py tests/test_agent_team_orchestration_resilience.py tests/test_agent_team_handoff_lineage.py tests/test_agent_team_router_guards.py tests/test_team_agent_checkpoint_store.py tests/test_team_agent_persistence.py
```

Observed result:

```text
116 passed in 2.00s
```

Additional verification:

```text
uv run ruff check apps/control_plane/agent_team_orchestration.py tests/test_agent_team_orchestration.py tests/test_agent_team_orchestration_edge_contracts.py tests/test_agent_team_orchestration_resilience.py tests/test_agent_team_handoff_lineage.py tests/test_agent_team_router_guards.py tests/test_team_agent_checkpoint_store.py tests/test_team_agent_persistence.py
All checks passed!

uv run python -m py_compile apps/control_plane/agent_team_orchestration.py
exit 0

uv run python scripts/verify_secrets.py
Secret scan passed: 1660 non-ignored worktree files and 1705 historical paths checked

git diff --check
exit 0 (line-ending warnings only)
```

This rerun supersedes the earlier transient missing-export and event-time test
noise for the seven in-memory / repository-backed files above. It does not
upgrade the PostgreSQL, runtime atomicity, restore reconcile, or multi-replica
gates.

## Findings and handling

### Info

#### Info-1: single-process multi-session/thread/subagent pilot capability is verified

- Handling: `no-op`
- Basis:
  - focused and full four-file orchestration runs passed
  - exact-scope, dependency barrier, handoff lineage, worker identity, kill switch and checkpoint/restore contracts were exercised

### P0

#### P0-1: runtime durable wiring is still incomplete

- Handling: `defer`
- Basis:
  - `runtime.py` still composes an in-memory coordinator directly
  - BR-150 and ADR-0104 continue to state that complete runtime durable wiring is not finished

#### P0-2: `0100` restore is not yet reconciled against `0099` durable task/event truth

- Handling: `defer`
- Basis:
  - ADR-0104 requires restore-time reconcile
  - this receipt does not establish any fresh executed runtime reconcile proof

#### P0-3: multi-replica disaster-recovery / cross-process production proof is still absent

- Handling: `defer`
- Basis:
  - BR-150 explicitly keeps this boundary open until runtime wiring and recovery rehearsal are complete

### P1

#### P1-1: PostgreSQL contract coverage exists in source but was skipped in this shell

- Handling: `defer`
- Basis:
  - `tests/test_team_agent_persistence_postgres.py` defines the suite
- this shell observed `16 skipped`, not a fresh executed pass

## False-completion boundary

This receipt does **not** prove:

- cross-process runtime durability
- `0099 + 0100` runtime session transaction wiring
- restore-time reconcile against `0099`
- multi-instance recovery rehearsal
- publish deduplication across replicas
- Ozon current fact, order, fulfillment, settlement, bank or customer outcome
- any external write

The verified state is narrower:

- single-process TeamAgentCoordinator pilot
- multi-session / multi-thread / multi-subagent control contracts
- exact-scope / authority / worker / kill / checkpoint fail-closed boundaries
- observation-only terminal publish boundary with `external_write_allowed=false`

## Next action

- Keep BR-150 runtime durable / reconcile / multi-replica gates `NOT PASSED`.
- Treat this receipt as proof of current single-process pilot orchestration capability only.
- Use a future runtime wiring slice to prove:
  - session-serialized transaction across runtime mutation + `0099` + `0100`
  - restore-time reconcile against `0099`
  - multi-replica recovery rehearsal
