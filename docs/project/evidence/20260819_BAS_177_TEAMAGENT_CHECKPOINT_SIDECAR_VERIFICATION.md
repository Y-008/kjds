# 20260819 BAS-177 TeamAgent Checkpoint Sidecar Verification

## Metadata

- Date: 2026-08-19
- Scope: read-only engineering review of TeamAgent checkpoint sidecar primitive
- Requirement: BR-150
- Related governance baseline: BAS-177
- ADR reference: ADR-0104
- Frontier review: checked_no_change
- Frontier candidates reviewed:
  - `durable_workflow_adapter=pilot`
  - `mcp_tasks_durable_protocol=watch`
  - `a2a_cross_agent_interoperability=watch`
- External write: false
- Business truth promotion: false
- Runtime durable completion claimed: false

## Exact files reviewed

- `apps/control_plane/team_agent_checkpoint_store.py`
- `apps/control_plane/team_agent_durable_recovery.py`
- `migrations/versions/20260819_0100_team_agent_session_checkpoints.py`
- `tests/test_team_agent_checkpoint_store.py`
- `tests/test_team_agent_durable_recovery.py`
- `tests/test_team_agent_persistence_postgres.py`
- `docs/adr/ADR-0104-teamagent-runtime-durable-session-checkpoint.md`
- `docs/project/MASTER_SPEC.md`
- `docs/project/registries/frontier_technology_adoption.json`
- `AGENTS.md`

## Requirement and authority alignment

- BR-150 requires exact-scope session control, authority-hash revalidation, fail-closed lease semantics, checkpoint/restore, and no false claim of cross-process production orchestration before runtime wiring and recovery rehearsal are complete.
- BAS-177 requires observation-only evolution boundaries, source-hashed control, and forbids runtime agents from self-modifying authority, Fact, Approval, Permit, or external-write policy.
- ADR-0104 defines the accepted boundary:
  - `0099` remains the task lease/CAS truth source.
  - `0100` sidecar stores a full per-session coordinator checkpoint.
  - Runtime wiring must reconcile sidecar state against `0099`.
  - The runtime wiring gate remains `NOT PASSED` until reconcile and multi-instance recovery tests pass.

## PostgreSQL verification status

### Source-defined PostgreSQL contract coverage

`tests/test_team_agent_persistence_postgres.py` defines five PostgreSQL contract tests covering:

1. migration replay `0098 → 0100 → 0099 → 0098 → 0100`
2. one CAS winner for task claim and expiry reclaim
3. exact-scope and idempotency conflict fail-closed behavior
4. heartbeat/release atomicity and append-only event history
5. checkpoint CAS winner and tamper rejection during restore

### Current shell execution

Command executed:

```text
uv run pytest tests/test_team_agent_persistence_postgres.py -q
uv run --env-file .env pytest tests/test_team_agent_persistence_postgres.py -q
```

Observed result in the current shell:

```text
sssss
5 skipped in 0.28s
sssss
5 skipped in 0.29s
```

Interpretation:

- The repository currently defines a five-test PostgreSQL 17 contract suite for the sidecar and `0099` persistence path.
- In this review shell, `KJDS_TEAM_AGENT_DATABASE_URL` was not available to the test process, so the suite did not execute against PostgreSQL and therefore did not re-establish a fresh `5 passed` result in this receipt.
- This receipt records the intended PostgreSQL contract scope and the actual observed execution status separately to avoid a false completion claim.

### Disposable PostgreSQL 17 execution

A separate verification worker then started an isolated disposable PostgreSQL 17 container and
executed the same contract file with an explicit, task-scoped database URL:

```text
docker run -d --rm --name kjds-teamagent-pg17-0100 \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=kjds_teamagent \
  -p 55497:5432 postgres:17

KJDS_TEAM_AGENT_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55497/kjds_teamagent \
  uv run pytest -q tests/test_team_agent_persistence_postgres.py
```

Observed result:

```text
5 passed, 12 warnings in 3.50s
```

The warnings are historical `Column.copy()` deprecation warnings from migration
`20260728_0067_native_scoped_formal_facts.py`; they did not change the five contract outcomes.
The disposable container was stopped after verification. This establishes a current PostgreSQL 17
result for the `0099 + 0100` persistence contract, but it does not close the runtime reconcile or
session-transaction P0 findings below.

## What is implemented and verified by inspection

- `apps/control_plane/team_agent_checkpoint_store.py` implements:
  - canonical checkpoint JSON validation
  - authority-bound checkpoint save
  - revision CAS for checkpoint updates
  - immutable checkpoint save history rows
  - restore-time checkpoint self-validation
- `migrations/versions/20260819_0100_team_agent_session_checkpoints.py` implements:
  - checkpoint and checkpoint-event tables
  - append-only checkpoint-event trigger
  - deferred revision-conserved trigger
  - downgrade block when checkpoint data exists
- `tests/test_team_agent_checkpoint_store.py` verifies in-memory save/restore CAS and authority-drift rejection by design.

## Findings and handling

### P0

#### P0-1: Sidecar restore does not reconcile against `0099` task/event truth

- Files:
  - `apps/control_plane/team_agent_checkpoint_store.py`
  - `docs/adr/ADR-0104-teamagent-runtime-durable-session-checkpoint.md`
- Evidence:
  - `restore()` validates only sidecar checkpoint content and metadata.
  - It does not read `team_agent_orchestration_tasks` / `team_agent_orchestration_events`.
  - ADR-0104 requires restore-time reconcile against `0099`.
- Risk:
  - A stale sidecar may restore a session that appears valid even when `0099` has already advanced, reclaimed, or expired the underlying task lease.
  - This creates a false impression of durable restart safety.
- Handling:
  - `defer`
  - Explicitly not fixed in this slice.
  - BR-150 runtime wiring gate remains `NOT PASSED`.

#### P0-2: No atomic runtime transaction spans `0099` task mutation and `0100` sidecar save

- Files:
  - `apps/control_plane/team_agent_checkpoint_store.py`
  - `docs/adr/ADR-0104-teamagent-runtime-durable-session-checkpoint.md`
- Evidence:
  - `save()` writes only checkpoint-side tables.
  - No runtime wrapper yet performs the session-serialized transaction ADR-0104 requires for `restore coordinator → mutate 0099 → save sidecar`.
- Risk:
  - Crash windows can leave `0099` truth and `0100` sidecar diverged.
  - Current restore path cannot fail-closed on that divergence because it never reconciles with `0099`.
- Handling:
  - `defer`
  - Explicitly not fixed in this slice.
  - BR-150 runtime wiring gate remains `NOT PASSED`.

### P1

#### P1-1: Current authority source revalidation is still deferred to runtime wiring

- Files:
  - `apps/control_plane/team_agent_checkpoint_store.py`
  - `docs/project/MASTER_SPEC.md`
  - `docs/adr/ADR-0104-teamagent-runtime-durable-session-checkpoint.md`
- Evidence:
  - Sidecar save/restore validates the authority hash embedded in the checkpoint and the caller-supplied authority hash.
  - It does not independently re-read the current authority source required by BR-150 mutation semantics.
- Risk:
  - Hash equality alone is not the same as fresh current-authority verification.
- Handling:
  - `defer`

#### P1-2: Checkpoint history metadata proof is narrower than the full ADR-0104 target

- Files:
  - `apps/control_plane/team_agent_checkpoint_store.py`
  - `migrations/versions/20260819_0100_team_agent_session_checkpoints.py`
- Evidence:
  - The deferred revision trigger proves revision/history presence through `checkpoint_revision` and `checkpoint_sha256`.
  - It does not fully conserve all sidecar tail metadata as an independent DB-level invariant.
- Risk:
  - Audit strength for authority/cursor/event-tail history is weaker than the eventual runtime durable target.
- Handling:
  - `defer`

#### P1-3: Populated downgrade blocking is implemented and now has a focused contract test, but this shell still cannot execute it

- Files:
  - `migrations/versions/20260819_0100_team_agent_session_checkpoints.py`
  - `tests/test_team_agent_persistence_postgres.py`
- Evidence:
  - The migration blocks downgrade when checkpoint rows or checkpoint events exist.
  - The PostgreSQL test file now includes `test_postgres_checkpointed_state_blocks_0100_downgrade`, which seeds a real checkpoint row and asserts that `command.downgrade(config, "20260809_0098")` raises the migration guard while preserving the `20260819_0102` version and seeded rows.
  - This shell still lacks a usable PostgreSQL connection, so the new assertion was collected but skipped here.
- Risk:
  - Migration safety is now contract-backed, but this receipt still lacks a live PostgreSQL execution result.
- Handling:
  - `contract_added`
  - Execute the new populated-downgrade contract in a PostgreSQL-enabled shell before closing the gate.

### P2

#### P2-1: `last_control_event_sha256` names an event-chain hash, not a payload SHA

- Files:
  - `apps/control_plane/team_agent_checkpoint_store.py`
  - `migrations/versions/20260819_0100_team_agent_session_checkpoints.py`
- Evidence:
  - The stored value comes from checkpoint event `event_hash`.
  - The field name suggests a generic SHA-256 rather than an event-chain tail hash.
- Risk:
  - Naming ambiguity for operators and future maintainers.
- Handling:
  - `defer`

## False-completion boundary

This review does **not** prove:

- runtime durable completion
- atomic runtime wiring across `0099` and `0100`
- multi-instance restart safety
- real Ozon fact, order, fulfillment, settlement, bank, or customer outcome
- any external write
- any business outcome

The sidecar is currently verified only as a checkpoint-store primitive with CAS/history semantics, not as a complete BR-150 runtime durable orchestration implementation.

## Next action

- Keep BR-150 runtime durable gate `NOT PASSED`.
- Treat `0099` reconcile plus session-serialized runtime transaction wiring as the next required implementation step.
- Treat the populated-downgrade contract as a PostgreSQL-only verification item that still needs a live execution result in an environment with `KJDS_TEAM_AGENT_DATABASE_URL`.

## 2026-08-19 continuation: reconcile and shared-transaction seam

- `TeamAgentDurableRecovery.restore()` now restores the authority-bound 0100 sidecar and compares it with the 0099 task/event checkpoint before admitting the coordinator. Task-set, durable revision, state/lease/terminal projection, exact scope, session identity, and expired-running-lease drift fail closed.
- `PostgresTeamAgentPersistence` and `PostgresTeamAgentCheckpointStore` now accept a caller-owned SQLAlchemy `Connection`. The checkpoint store can lock the exact session row with `FOR UPDATE`; neither adapter commits or closes that caller-owned transaction.
- `test_task_mutation_and_checkpoint_share_one_commit_boundary` defines the PostgreSQL acceptance contract: a forced exception rolls back both the 0099 claim/event and the 0100 checkpoint revision; the success path advances both and preserves the same lease reference.
- Current-shell evidence: `29 passed, 17 skipped` for persistence, checkpoint, recovery, and PostgreSQL contract files; the wider Harness-focused set is `123 passed, 17 skipped`. Docker daemon and a local PostgreSQL service were unavailable, so the new PostgreSQL atomicity test was collected but not executed in this continuation.
- Runtime wiring remains `NOT PASSED`: `runtime.py` still constructs the in-process coordinator directly and does not yet run restore/reconcile/mutate/checkpoint through the shared transaction seam.

## 2026-08-19 continuation: PostgreSQL runtime composition and scoped publication

The final sentence of the preceding continuation is now historical. Current source state adds the runtime composition, but the production Gate remains open because this shell cannot execute the PostgreSQL contracts.

Implemented in source:

- `apps/control_plane/team_agent_postgres_runtime.py` now supplies a PostgreSQL-only facade. Mutation transactions lock the exact 0100 checkpoint row, run `TeamAgentDurableRecovery`, mutate 0099 task/event state and the Coordinator projection on one caller-owned connection, bind the resulting durable revision/request identity, and save the next sidecar revision before commit. A replay of an identical durable handoff returns the existing lineage without another checkpoint revision.
- The facade covers session creation, task submit/claim/heartbeat/complete/fail, thread creation, handoff sidecar mutation, pause/resume, kill-switch engage/release, exact-scope snapshot and restart restoration. An active claim replay by the same worker and lease returns the existing running task without adding a task or checkpoint revision.
- `apps/control_plane/runtime.py` selects the facade when the repository engine is PostgreSQL; non-PostgreSQL local/test composition retains the in-process Coordinator.
- `apps/control_plane/routers/agent_control.py` resolves the current scope-grant authority before durable restore, admits the session by exact tenant/entity/store, and forwards that exact scope plus authority to reads, controls, task mutations, and Harness publication. Worker identity and lease fencing remain explicit.
- `TeamAgentHarnessBridge.publish_completed()` accepts an admitted durable scope and restores that exact session instead of performing a second global `session_ref` lookup. `AgentHarnessService.record_observation()` already derives a deterministic observation ID and database replay key; a savepoint now converts concurrent unique-key losers into the same durable response.
- Migration `20260819_0102_team_agent_session_task_controls.py` admits the durable `resumed` event while preserving downgrade refusal when resumed history exists.

Current-shell verification:

```text
151 passed, 29 skipped in 4.73s
```

This is the complete Harness-focused set across Agent Harness, TeamAgent Coordinator/resilience/handoff/router, checkpoint store, durable recovery, persistence, and PostgreSQL contract collection. A separate runtime-composition check passed:

```text
2 passed in 1.32s
```

The focused total includes two composition tests that directly exercise the SQLite Pilot/PostgreSQL facade dialect selector. The 29 skipped tests require `KJDS_TEAM_AGENT_DATABASE_URL` pointing at PostgreSQL. New unexecuted PostgreSQL contracts specifically cover:

- active claim replay without revision inflation;
- two runtime instances converging on one terminal transition;
- stale-replica kill-switch fencing for claim and completion;
- pause/resume/kill-switch mutation followed by strict restart reconcile;
- handoff sidecar mutation followed by strict restart lineage reconcile;
- atomic expired-lease recovery and exhausted-attempt blocking;
- concurrent multi-worker Harness observation publication converging to one row;
- shared task/checkpoint commit and rollback boundaries.

Remaining false-completion boundary:

- No running Docker daemon or local PostgreSQL service was available in this shell, so migrations 0099–0102 and the new runtime contracts were collected but not executed against PostgreSQL 17.
- No live two-process restart/failover rehearsal has yet proved row-lock serialization, retry behavior, or recovery after process loss.
- Handoff mutation is exposed through the durable facade and has a restart-reconcile contract, but that PostgreSQL contract has only been collected in this shell and has not executed.
- These changes do not prove Ozon facts, orders, fulfillment, settlement, bank receipts, customer outcomes, or any external write.

Gate status: source wiring is delivered; cross-process production orchestration remains `NOT PASSED` until real PostgreSQL execution and multi-instance recovery rehearsal succeed.

## Pre-execution current-tree receipt (historical, 2026-08-19)

The current focused suite is `194 passed`; the expanded PostgreSQL contract file is
collected as `37 skipped`. It includes the exact budget-capped heartbeat
deadline regression: the Coordinator absolute deadline is carried into 0099
instead of being recomputed by truncating a fractional second. Read-only
restore remains free of recovery writes; only write-authorized mutation
admission/recovery may transition expired leases. No PostgreSQL contract or
multi-process restart/failover claim is promoted from this shell, so the
BR-150/BAS-177 production Gate remains `NOT PASSED`.

The current transaction boundary also maps PostgreSQL-aborted `40001` and
`40P01` outcomes to a structured, retryable 409 that requires a fresh restore;
it does not automatically replay the mutation and does not reclassify unrelated
database failures. The 33rd PostgreSQL contract uses spawned processes rather
than threads to verify one claim winner, process exit, restart hydration and
post-expiry recovery. It is collected but unexecuted in this shell.

`scripts/verify_team_agent_postgres_gate.py` is the executable acceptance
entrypoint. It accepts the URL only through `KJDS_TEAM_AGENT_DATABASE_URL`,
requires PostgreSQL 17 and isolated-schema/role capability, runs the complete
contract file, and refuses PASS if JUnit reports any failure, error or skip.
Its blocked path, receipt conservation, retained-JUnit hashing, and credential
redaction have `7 passed` unit coverage; the current focused receipt is
`194 passed in 5.29s`, with the PostgreSQL file separately `37 skipped in 0.48s`.

The latest rerun also covers PERSONAL-value, completed-result defensive-copy,
unscoped durable-publication rejection, and exact-scope-only durable runtime reads;
it is `194 passed` with the PostgreSQL file separately `37 skipped`. The PostgreSQL 17 contract file
remains unexecuted because no database listener is available in this shell.

## 2026-08-20 PostgreSQL execution update

The preflight-only boundary above is historical. A fresh, run-owned PostgreSQL
17 container subsequently executed the current 38-contract file with `38
passed, 0 skipped`, including spawned-process loss/recovery and caller-owned
transaction-isolation preservation. The PostgreSQL-enabled 14-file focused set
returned `237 passed, 0 skipped`. Credential-scanned JSON/JUnit artifacts and
their hashes are recorded in
`docs/project/evidence/20260820_BR_150_TEAMAGENT_POSTGRES_GATE.md`; the container
and random listener were removed after verification. This closes the local
contract Gate, not the deployed multi-replica/SLO/RPO/RTO production Gate.

The final receipt includes `test_postgres_spawned_worker_crash_after_commit_before_ack_is_idempotent`;
the current disposable local Gate is closed for all 38 contracts. Deployed
multi-instance recovery and production SLO/RPO/RTO remain open.
