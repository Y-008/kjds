# BR-150 TeamAgent / Harness Graph hardening follow-up

- Date: 2026-08-19
- Scope: local safety and consistency repair for the TeamAgent in-process Pilot.
- `frontier_review`: `not_required` — no new external provider, market claim, or product recommendation was introduced.
- External writes: none. Harness output remains Observation-only and `gate_eligible=false`.

## Contract alignment

This follow-up preserves the BR-150 fail-closed boundary:

- Public coordinator results are defensive copies; callers cannot mutate canonical nested result, acceptance-contract, provider-bucket, handoff, session, task, or thread state without a coordinator transition.
- Default event timestamps are current UTC time. Fixed-time tests explicitly supply their fixture time rather than weakening production event-time rollback protection.
- A pre-claim time-budget terminal now records a replayable terminal event and a `task.blocked` Observation. Retry exhaustion, explicit blocked release, and expiry-to-blocked also produce terminal observations for the Harness bridge.
- Event merge accepts a single-session incoming batch only. A mixed-session batch fails closed because one returned cursor cannot safely represent both session chains.
- Harness publication de-duplication is keyed by observation, project, exact scope including authority hash, and principal identity. A recovered coordinator with the same observation reference but a different exact scope is published and re-authorized instead of inheriting a stale cache result.
- The HTTP contract requires `lease_ref` for heartbeat, complete, and fail, and the generated OpenAPI snapshot is synchronized from the runtime application.
- Result admission rejects `PERSONAL` as well as `SECRET` classification before values can enter task results, events, checkpoints, or observations.

## Verification evidence

Passed locally:

```text
uv run pytest -q -p no:cacheprovider --basetemp=D:\KJDS\kjds\.runtime\pytest-root-harness-20260819j \
  tests/test_agent_team_orchestration.py \
  tests/test_agent_team_orchestration_edge_contracts.py \
  tests/test_agent_team_orchestration_resilience.py \
  tests/test_agent_team_handoff_lineage.py \
  tests/test_agent_team_router_guards.py \
  tests/test_team_agent_checkpoint_store.py \
  tests/test_team_agent_persistence.py
# 116 passed

uv run python scripts/export_openapi.py
uv run pytest -q -p no:cacheprovider --basetemp=D:\KJDS\kjds\.runtime\pytest-root-openapi-20260819a \
  tests/test_api_contract.py::test_openapi_v1_snapshot_matches_runtime_contract \
  tests/test_agent_team_router_guards.py
# 4 passed

uv run pytest -q -p no:cacheprovider --basetemp=D:\KJDS\kjds\.runtime\pytest-root-harness-nonpg-20260819b \
  tests/test_team_agent_evolution.py \
  tests/test_compile_teamagent_control_snapshot.py \
  tests/test_agent_harness.py
# 30 passed
```

Final merged local regression (the above groups, recovery-only reconcile tests,
and the OpenAPI snapshot):

```text
152 passed, 1 known FastAPI/Starlette httpx deprecation warning
```

The cache recovery regression is covered by
`tests/test_agent_team_orchestration.py::test_harness_bridge_cache_does_not_cross_restored_exact_scope`.
The isolated Harness fixture explicitly imports the two model modules required
by current AI-listing foreign keys, matching the existing listing test pattern;
this removes an order-dependent `Base.metadata.create_all()` failure without
changing Harness authority or business behavior.

The current shared tree also contains a recovery-only `TeamAgentDurableRecovery`
module. Its five in-memory tests pass and it rejects task-set, revision, request
identity, projection, lease, completed-result, evidence, and reviewer drift.
It is not imported by `runtime.py`; this is a recovery admission check, not
runtime durable wiring.

## PostgreSQL verification boundary

ADR-0103 source includes the requested `REPEATABLE READ` checkpoint snapshot and same-worker concurrent-claim CAS winner reread. The current adapter also upgrades an unused caller-owned connection to `REPEATABLE READ` for task/event checkpoint reads (and fails closed if a weaker transaction has already started), while the durable runtime opens its shared transaction at that level. Fresh PostgreSQL integration execution was not available in this environment: Docker Desktop's daemon was unavailable and no listener was present on port 5432, so the PostgreSQL contract tests skipped. No alternate database was started and no environment credential was changed.

## Production gate remains open

This paragraph records the earlier checkpoint and is superseded by the current
receipt below. ADR-0104 remains the governing open gate.

## Superseding runtime-wiring verification receipt

This section supersedes only the earlier statements that `runtime.py` did not
invoke durable reconcile. It does not supersede the production Gate boundary.

Implemented and reviewed in the current shared tree:

- PostgreSQL composition selects `PostgresTeamAgentRuntime`; every durable
  mutation replays current exact-scope authority and serializes on the 0100
  sidecar row.
- Recovery compares the full 0099/0100 task set, request identity, revision,
  operational projection, completed result, Evidence and reviewer fields.
- An expired running lease remains rejected by read-only restore. The explicit
  locked `recover_session` path transitions Coordinator state, the 0099 task and
  event, and the 0100 checkpoint/history in one transaction. Attempt exhaustion
  closes as `blocked` without violating the PostgreSQL `expired_at` shape.
- Runtime transactions normalize PostgreSQL SQLSTATE `40001` and `40P01` into
  a structured HTTP 409 that states the transaction rolled back and requires a
  fresh restore before retry. They do not replay an unknown terminal action;
  unrelated database failures remain unclassified.
- Collected PostgreSQL regressions cover rollback of task and both event
  histories, dual-runtime single terminal winner, stale-replica Kill Switch
  fencing, expired-lease recovery, terminal round-trip and concurrent Harness
  observation convergence.

Latest focused verification:

```text
uv run pytest -q -p no:cacheprovider <13 TeamAgent and Harness test files>
# 177 passed, 33 skipped

uv run ruff check <scoped implementation and test paths>
# All checks passed

uv run python scripts/verify_secrets.py
# Secret scan passed: 1673 non-ignored worktree files and 1705 historical paths checked

git diff --check
# exit 0; line-ending warnings only
```

The 33 skipped cases all require `KJDS_TEAM_AGENT_DATABASE_URL`. Docker client
inspection returned permission denied for the Docker API, and `127.0.0.1:5432`
had no listener, so no alternate database was installed or started.

Repository-wide gates remain distinguishable from this slice:

- `uv run ruff check .` still reports the pre-existing import-order error in
  `apps/control_plane/ai_listing.py:1`.
- the full pytest command reached 3 percent and then made no progress in the
  existing database/API portion; it was interrupted without a passing result.

Therefore BR-150 cross-process production status remains `NOT PASSED`. A real
PostgreSQL 17 migration replay, the 33 PostgreSQL contracts, and a live
 multi-process restart/failover rehearsal are still required. No result in this
 receipt grants Fact, Approval, Permit, FinanceEntry or external-write authority.

## Latest focused receipt (2026-08-19)

The current shared tree adds the durable PostgreSQL composition and preserves the
read-only/recovery split: `restore_session` is a pure read, while mutation
admission or explicit `recover_session` is write-authorized. Coordinator-derived
absolute lease deadlines are now passed through both claim and heartbeat into
the 0099 adapter; the adapter rejects a deadline outside the requested window,
including sub-second budget-capped deadlines.

```text
uv run --no-cache pytest -q -p no:cacheprovider <TeamAgent/Harness-focused files>
# 177 passed, 33 skipped

uv run --no-cache pytest -q -p no:cacheprovider tests/test_team_agent_persistence_postgres.py
# 33 skipped
```

The 33 PostgreSQL contracts remain unexecuted because this shell has no usable
Docker API and no listener on `127.0.0.1:5432`. The cross-process production
Gate remains `NOT PASSED`; a real PostgreSQL 17 run and multi-instance
restart/failover rehearsal are still required.

## 2026-08-20 fencing and publication-cache receipt

The current tree additionally rejects a same-worker active-claim replay when
the caller supplies a lease reference different from the canonical active
lease. Harness in-memory publication de-duplication now includes `session_ref`
in addition to observation, project, exact scope and principal, so two sessions
that produce the same task-shaped observation reference cannot reuse each
other's cached authorization/result. Budget exhaustion remains a blocked
terminal without populating the lease-specific `expired_at` field.

```text
python -m pytest -q -p no:cacheprovider <13 TeamAgent/Harness-focused files>
# 177 passed, 33 skipped

python -m pytest -q -p no:cacheprovider \
  tests/test_api_contract.py::test_openapi_v1_snapshot_matches_runtime_contract \
  tests/test_agent_team_router_guards.py
# 10 passed, 1 Starlette deprecation warning

python -m ruff check <scoped implementation and test paths>
# All checks passed

git diff --check
# exit 0; line-ending warnings only
```

An expanded run that also included the separate
`test_team_agent_evolution_postgres.py` suite did not produce a database proof:
its configured generic `DATABASE_URL` pointed to an unreachable local
PostgreSQL endpoint, so 31 tests errored in module fixture connection setup.
This is an environment failure, not a confirmed PostgreSQL no-change and not a
BR-150 pass. The dedicated BR-150 file still collected as 33 skipped because
`KJDS_TEAM_AGENT_DATABASE_URL` was unavailable. The production Gate therefore
remains `NOT PASSED`.

## 2026-08-20 transaction-conflict and spawned-process contract

- `TeamAgentTransactionConflict` distinguishes PostgreSQL-aborted serialization
  and deadlock transactions from ordinary durable-state conflicts. Its API
  detail is stable and machine-readable: `retryable=true`,
  `transaction_outcome=rolled_back`, and
  `retry_requires_fresh_restore=true`.
- Unit contracts cover SQLSTATE `40001`, SQLSTATE `40P01`, and preservation of
  an unrelated `08006` connection failure. This prevents both blind mutation
  replay and false retryability.
- The PostgreSQL suite now contains a real `multiprocessing` `spawn` contract:
  two fresh interpreters and connection pools race for one task, exactly one
  durable claim wins, the winner process exits, and a newly constructed runtime
  restores the active lease before recovering it after expiry.
- That spawned-process case is one of the 33 collected PostgreSQL skips in this
  shell. It becomes evidence only after execution against PostgreSQL 17; its
  presence alone does not close the multi-instance Gate.

Latest reproducible checks:

```text
python -m pytest -q -p no:cacheprovider <13 non-PostgreSQL TeamAgent/Harness/Gate files>
# 194 passed in 5.29s

python -m pytest -q -p no:cacheprovider tests/test_team_agent_persistence_postgres.py
# 37 skipped in 0.48s

uv run pytest -q -p no:cacheprovider \
  tests/test_api_contract.py::test_openapi_v1_snapshot_matches_runtime_contract \
  tests/test_agent_team_router_guards.py
# 10 passed, 1 known Starlette deprecation warning

uv run pytest -q -p no:cacheprovider tests/test_team_agent_runtime_composition.py
# 5 passed in 1.13s
```

The executable PostgreSQL acceptance entrypoint is now
`scripts/verify_team_agent_postgres_gate.py`. It reads the URL only from
`KJDS_TEAM_AGENT_DATABASE_URL`, requires PostgreSQL 17 and isolated-schema/role
capability, runs all 38 contracts, and parses JUnit so any failure, error or
skip prevents PASS. The receipt never serializes the database URL. Its five
failure-closed/unit contracts bring the latest combined result to:

```text
uv run pytest -q -p no:cacheprovider <14 TeamAgent/Harness/Gate files>
# 194 passed in 5.29s; PostgreSQL file separately 37 skipped in 0.48s
```

The skip-only rerun above is historical: it was `194 passed` with the expanded
PostgreSQL file separately `37 skipped`.
In addition to PERSONAL-value rejection, completed-result defensive copies, and
unscoped durable Harness-publication rejection, the six new runtime contracts reject
five bare global durable read shapes before I/O and prove exact-scope/authority
delegation; three further contracts cover stable snapshot hashing and retained
Gate JUnit/machine receipts. This does not alter
the disposable PostgreSQL Gate now closed by the later retained receipt; the
deployed multi-instance boundary remains `NOT PASSED`.

## 2026-08-20 PostgreSQL execution update

The skip-only receipt above is historical. The final 38-contract PostgreSQL
17 Gate returned `38 passed, 0 skipped`, and the PostgreSQL-enabled 14-file
focused set returned `237 passed, 0 skipped`. Retained machine receipt/JUnit
paths, SHA-256 values, credential scans, and exact-container cleanup evidence
are recorded in `20260820_BR_150_TEAMAGENT_POSTGRES_GATE.md`. The local
disposable contract Gate is now closed; deployed multi-replica failover,
long-running recovery/serialization rehearsal, and production SLO/RPO/RTO
remain open.

The final receipt includes
`test_postgres_spawned_worker_crash_after_commit_before_ack_is_idempotent`; the
current disposable local Gate is closed for all 38 contracts. Deployed
multi-instance recovery and production SLO/RPO/RTO remain open.

## 2026-08-20 reviewer-authority fail-closed update

The production completion route no longer accepts a caller-provided reviewer
name as proof of independent review. If the request names a reviewer, the task
already carries a reviewer, or the task requires a reviewer role, admission
returns stable 409 `team_agent_reviewer_authority_unavailable` before calling
the coordinator. The in-process Coordinator retains reviewer fields for
deterministic pilot and replay contracts only.

The current non-PostgreSQL focused suite is `203 passed in 8.83s`; the
reviewer/runtime router focus is `23 passed`, and the available Agent
Control/API schema focus is `15 passed` with one known Starlette warning.

## 2026-08-20 hidden-boundary audit addendum

The follow-up audit reproduced and closed three remaining mutable/authorization
edges: cached Harness replays now re-enter sink authorization; TeamAgent durable
observation identity binds the closed exact scope and principal; and public
checkpoint/`ControlEvent` objects no longer retain caller-owned nested dicts.
It also makes release/fail time-budget equality use the same budget-first
terminal path as complete/heartbeat. The current no-database 14-file collection
is `206 passed, 40 skipped`, and the Agent Control/OpenAPI focus is `15 passed`
with one known Starlette warning. PostgreSQL skips are not promoted; a new
current-source PostgreSQL 17 receipt is required before updating the local Gate
receipt, while the deployed production Gate remains `NOT PASSED`.

## 2026-08-20 reviewer-authority seam correction

The completion route now exposes the versioned
`team-agent-reviewer-appointment@1` server-authority seam. The production
runtime injects an unavailable authority by default, so the fail-closed 409
above remains the default. An injected attestation is admitted only when its
exact scope/session/task, role, reviewer identity, current authority hash, and
actor separation all match; its appointment evidence ref is added to the
completion evidence. This is a seam, not a durable appointment registry.
The current non-PostgreSQL focus is `210 passed`, reviewer/runtime router focus
is `25 passed`, and the Agent Control/OpenAPI focus is `15 passed`.
