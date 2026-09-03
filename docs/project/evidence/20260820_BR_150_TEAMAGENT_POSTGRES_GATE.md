# BR-150 TeamAgent PostgreSQL 17 Gate Receipt — 2026-08-20

## Current-head all-42 rerun (2026-08-20, authoritative)

A fresh run-owned PostgreSQL 17 container executed the current 42 PostgreSQL
contracts through `scripts/verify_team_agent_postgres_gate.py` at the sole
Alembic head `20260820_0103`: `42 passed, 0 failures, 0 errors, 0 skipped`.
The 13-contract required recovery manifest now includes complete/fail terminal
response-loss replay and drift-conflict contracts. Credential-free artifacts are
retained under `D:\KJDS\kjds\.runtime\team-agent-pg17-terminal-final2\`:

- JUnit SHA-256: `f9f8015e3be74f00dc25e413d657fa6eed87d8dfaec660408f08f59b9a4eb982`
- Receipt SHA-256: `4a1001f335d5c3f7870f8f6562d648bd374f46f3083d3b00bc3622400b98ac73`
- Required manifest SHA-256: `eec27cf9677aa82cb02e79fa8a39c262e24c817d8ddcdb603bbb3e6433de71c9`
- Contract source SHA-256: `510d414870dd870fb0cdd660fc8f89f814e273fa21ad745551006fb30d1bc662`

The receipt has `business_truth_proven=false` and `external_write_allowed=false`.
This closes the current local persistence/replay contract Gate only; terminal
publish liveness, deployed multi-replica failover, and production SLO/RPO/RTO
remain `NOT PASSED`.

## Current-head all-40 rerun (historical, superseded by all-42 receipt)

A fresh run-owned PostgreSQL 17 container executed the current 40 PostgreSQL
contracts through `scripts/verify_team_agent_postgres_gate.py` after migrating
to the sole Alembic head `20260820_0103`: `40 passed, 0 failures, 0 errors, 0
skipped`. The required recovery manifest contains 11 contracts, including the
hard process crash and retry-wait pause/restart recovery contracts; 0103 downgrade
is fail-closed while a paused retry schedule exists. Credential-free
receipt/JUnit are retained under
`D:\KJDS\kjds\.runtime\team-agent-pg17-gate-0103-final\`; JUnit SHA-256 is
`c6c65a385cc60167efa6e036c50bfc5975a322e278f3a6be3ba32e72b3516287`,
receipt SHA-256 is
`de57f42b53670eb5650aab83d679e7b98c686cc32a677474f4a09622707cd261`, and
the required-contract manifest SHA-256 is
`49422c81aec0e480a454ca717f7d33ce5c57ed5703fe7f8fdf951b77e333e8e0`.
the contract source SHA-256 bound into the receipt is
`e747f8f4b03850ac3ce89590a260563797afba9d5daa68aad90410b63fa8f2fc`.
The disposable container was removed. This closes the
local contract Gate only; deployed multi-replica failover, long-running
recovery/SLO/RPO/RTO rehearsal, and the BR-150 cross-process production Gate
remain `NOT PASSED`.

The matching no-database 14-file focused run returned `205 passed, 40 skipped`;
all 40 skips belong to the PostgreSQL-only contract file and are covered by the
current-head run above. Full-tree Ruff, the secret scan, scoped compilation,
and `git diff --check` passed. This local, reversible correctness fix required
no new provider or dependency, so `frontier_review=not_required`.

## Scope

This receipt covers the durable TeamAgent persistence and runtime contracts only. It
does not promote any task observation into Fact, Approval, Permit, FinanceEntry, or
business truth, and it does not authorize an external write.

## Preflight execution (historical, superseded by all-40 receipt)

- Runner: `scripts/verify_team_agent_postgres_gate.py`
- Database URL: not configured in this shell (`KJDS_TEAM_AGENT_DATABASE_URL` unset)
- Contract file: `tests/test_team_agent_persistence_postgres.py`
- A bounded probe against `127.0.0.1:5999` also failed closed because no PostgreSQL
  listener is available. Docker Desktop is not usable from this shell.

## Observed result (historical, superseded by all-40 receipt)

The runner returned `status=BLOCKED`, exit code `2`, with reason
`KJDS_TEAM_AGENT_DATABASE_URL is required`. The 33 PostgreSQL contracts are collected
but unexecuted; no PostgreSQL 17 migration, spawned-process recovery, or production
cross-process Gate pass is claimed. The blocked receipt did not serialize a DSN or
password.

## Boundary (historical preflight boundary)

This does not close the local PostgreSQL 17 contract Gate or the BR-150 cross-process
production Gate. A real PostgreSQL 17 run, deployed multi-replica failover,
long-running serialization/recovery rehearsal, operational SLO/RPO/RTO evidence, and
real business-source validation remain required. The Harness result stays
observation-only and exact-scope.

## Historical focused verification before PostgreSQL execution

The bounded non-PostgreSQL focused rerun was executed against the current tree
with the current TeamAgent/Harness/Gate set (including the control-snapshot,
G-1 phase contract, PostgreSQL, and Gate-runner unit contracts). It returned `195 passed, 34
skipped`; every skip is in the PostgreSQL contract file and therefore remains
unexecuted. This receipt does not promote the older `184 passed`/`183 passed`
historical receipts and does not claim a PostgreSQL 17 or spawned-process pass.

## Disposable PostgreSQL 17 contract run (historical all-38 receipt)

After the historical preflight-only run above, a fresh, run-owned
`postgres:17-alpine` container was started on a disposable host port and
removed after verification. The runner created a random schema, applied
migrations through `20260819_0102`, executed the full PostgreSQL contract file,
and removed the schema during fixture cleanup. No existing project container
or business database was used.

- Runner: `scripts/verify_team_agent_postgres_gate.py`
- PostgreSQL: major `17` (`postgres:17-alpine`, image ID
  `sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193`)
- Result: `status=PASSED`
- Tests: `38`
- Failures/errors/skips: `0/0/0`
- `spawned_process_recovery_executed=true`
- `business_truth_proven=false`
- `external_write_allowed=false`
- Duration: `11.89s`
- Gate JUnit: `D:\KJDS\kjds\.runtime\team-agent-pg17-gate-20260820-final\junit.xml`
- Gate JUnit SHA-256:
  `072c7e9877f6d6009ef87732771b3ed27565f17c5b1681807889ed2bd6700a75`
- Machine receipt: `D:\KJDS\kjds\.runtime\team-agent-pg17-gate-20260820-final\receipt.json`
- Machine receipt SHA-256:
  `5f7523e187503b2e865bdd6a4a0433747a0e8da5f879ee626f9cc77aa7e06c42`

The PostgreSQL-enabled 14-file TeamAgent/Harness/Gate set returned `237 passed,
0 skipped`. Its JUnit is
`D:\KJDS\kjds\.runtime\team-agent-pg17-final-20260820\focused-junit.xml` with
SHA-256 `56bb735bb6188e44d1f5b00b25d32dd460a463031edd2a04ee82eec0ae85aab2`.
The three retained files were checked and contain neither the database URL nor
its password. The run-owned container was removed by exact ID after evidence
verification, and its random host port no longer has a listener.

The run emitted only existing Alembic deprecation warnings (`Column.copy()`);
they did not affect the contract result. This closes the local disposable
PostgreSQL 17 contract Gate, but not deployed multi-replica failover,
long-running SLO/RPO/RTO rehearsal, or production business-source validation.
The final contract set also proves that a fresh caller-owned default
transaction can be elevated with transaction-local `SET TRANSACTION`, while a
stronger `SERIALIZABLE` caller remains serializable rather than being
downgraded.

## Current-source delta correction

The previously appended 41-contract delta is superseded by the authoritative
all-42 receipt above. The retained run-owned PostgreSQL 17 artifacts under
`.runtime/team-agent-pg17-terminal-final2/` bind source hash
`510d414870dd870fb0cdd660fc8f89f814e273fa21ad745551006fb30d1bc662` and report
`42 passed, 0 failures, 0 errors, 0 skipped`, including the terminal
complete/fail response-loss replay and drift-conflict contracts. This closes
the current local persistence/replay Gate only. Terminal publish liveness,
deployed multi-replica failover, long-running SLO/RPO/RTO rehearsal, and
production business-source validation remain open.

## Current-head all-42 rerun correction (latest source)

The persistence/runtime tree changed after the preceding all-42 receipt, so a
fresh run-owned PostgreSQL 17.10 container reran the current 42 contracts at
Alembic head `20260820_0103`: `42 passed, 0 failures, 0 errors, 0 skipped`.
Credential-free artifacts are retained under
`D:\KJDS\kjds\.runtime\team-agent-pg17-root-final3-20260820\`:

- contract source SHA-256: `510d414870dd870fb0cdd660fc8f89f814e273fa21ad745551006fb30d1bc662`
- JUnit SHA-256: `2f3c27e6cb1a13598ae4783977a14f363c8cec654de77a65aae252dde8d0430c`
- `spawned_process_recovery_executed=true`
- `business_truth_proven=false`; `external_write_allowed=false`

The earlier all-42 receipt remains historical for its source hash; this
correction is authoritative for the latest persistence/runtime source. It
still closes only the disposable local contract Gate, not terminal publish
liveness, deployed multi-replica failover, cross-restart publication
deduplication, SLO/RPO/RTO rehearsal, or production business-source truth.

## Current-source delta after terminal outbox increment

The all-42 receipt above remains valid for its recorded source hash, but the
current tree now adds transactional terminal-publish outbox staging in
`team_agent_postgres_runtime.py` and the
`TeamAgentTerminalOutboxPublisher` replay adapter. A fresh PostgreSQL 17 run is
required to bind the updated source hash and verify outbox atomicity alongside
the existing 42 contracts. Until that rerun, the local persistence Gate is
historical for the captured tree; terminal publish liveness, release/expiry
blocked-terminal enqueue coverage, deployed multi-replica failover, and
production SLO/RPO/RTO remain open.

## Current-head all-42 rerun after terminal outbox increment

A fresh run-owned PostgreSQL 17 Gate was executed against the updated tree at
Alembic head `20260820_0103`: `42 passed, 0 failures, 0 errors, 0 skipped`.
The run includes the terminal outbox payload contract assertion; the payload is
scope/session/task-only and excludes the TeamAgent result. Credential-free
artifacts are retained under
`D:\KJDS\kjds\.runtime\team-agent-pg17-terminal-outbox-final\`:

- JUnit SHA-256: `4613ea76ac60fa2fbc3c8f3d907091d6eca13ad3916db91bfabc4c4ac43d7608`
- Receipt SHA-256: `962c0469dff33af350ea945538d7ea6bf27a3f5e74d38d75020594c08aab2ff5`
- Contract source SHA-256: `fe81d26e5483f928faa0fca9855a14cf014a8788c88c762882c434b183580d7d`
- Required recovery manifest SHA-256: `eec27cf9677aa82cb02e79fa8a39c262e24c817d8ddcdb603bbb3e6433de71c9`

This proves local transactional enqueue plus the existing persistence/recovery
contracts. It does not prove an always-on publisher, release/expiry blocked
terminal enqueue, deployed multi-replica failover, or production liveness SLO.

## G-1 phase integration

`scripts/verify-g1.ps1` now invokes the dedicated runner immediately after the
run-owned primary database is recreated and before the normal migration replay.
The TeamAgent database environment variable is removed immediately after the
phase and again during final cleanup; the report initializes
`team_agent_postgres_gate=false` and sets it true only after the runner exits
successfully. The static G-1/release/Gate contract set returned `31 passed`, and
PowerShell parsing succeeded. The full Web/API G-1 release harness was not run
for this persistence slice, so no complete current-head G-1 PASS is claimed.

## Current-tree receipt verification (historical all-38 receipt)

The final raw artifacts at
`D:\KJDS\kjds\.runtime\team-agent-pg17-gate-20260820-final` were re-read after the
latest PostgreSQL contracts were added. `receipt.json` reports PostgreSQL
major 17, `38` tests, zero failures/errors/skips, and
`spawned_process_recovery_executed=true`; the recorded SHA-256 values match the
retained JUnit and focused-JUnit files. A credential scan found no database URL,
password, or DSN in the three artifacts. The disposable local PostgreSQL 17
contract Gate is therefore `PASSED` for this receipt; deployed multi-replica
failover, long-running SLO/RPO/RTO rehearsal, and production business-source
validation remain open.

## Current-tree contract delta after the retained receipt (historical)

The earlier 37-test receipt is historical. The final all-38 receipt above was
executed after `test_postgres_spawned_worker_crash_after_commit_before_ack_is_idempotent`
was added; its JUnit reports `38` tests with zero failures, errors, or skips,
and its receipt/required-recovery-contract hash was independently re-read.
