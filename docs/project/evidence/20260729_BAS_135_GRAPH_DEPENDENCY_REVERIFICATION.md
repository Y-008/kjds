# BAS-135 Evidence — Graph Dependency Re-verification Recovery

## Decision

`BAS-135` engineering is accepted on 2026-07-29. It corrects two real observer
faults without changing any business Gate:

1. Windows Task Scheduler reports a missing task as
   `CimJobException/ObjectNotFound` on this host. The audit now maps that external
   condition to the stable, secret-free missing-task result instead of a generic audit
   failure.
2. The Graph observer now binds every emitted Observation input to the complete direct
   dependency set across the BAS-128 → BAS-132 → BAS-133 → BAS-134 GoalTask DAG.
   An upstream change first invalidates old downstream observations; a real same-run
   re-verification then appends new downstream observations and restores `fresh`.

This accepts dependency invalidation and recovery engineering. It does not accept
BAS-040, Supabase identity provisioning, M0–M4, Pilot, Release or Final Gates.

## Fault observed in the real Graph

After the scheduler audit script and verifier test input changed, the first append-only
replay reached `139` Harness observations. The new BAS-132 test observation was
`passed/fresh`, but the still-current BAS-133 and BAS-134 verifier runs reused old
idempotency inputs:

- `task-bas133-verifier-tests` became
  `stale` with `upstream_changed:task-bas132-verifier-tests`;
- `task-bas133-authority-intake-live` became stale behind that task;
- `task-bas134-verifier-tests` became stale behind BAS-133 tests;
- the runtime topology remained blocked but also carried both stale upstream blockers.

This was correct invalidation and incorrect recovery. The downstream processes had run
again, but their Observation inputs did not include the changed dependency hashes, so
the append-only replay constraint reused old rows.

## Implementation

- `scripts/manage-evidence-health-task.ps1`
  classifies both native `CimException` and PowerShell
  `CimJobException/ObjectNotFound` without recording exception text.
- `tests/test_evidence_health_task.py`
  verifies the exact stable missing-task result on the real Windows contract.
- `scripts/seed_project_engineering_execution_graph.py`
  builds one deterministic dependency-input map for:
  - BAS-128 pytest → database → containers → API → browser → Evidence;
  - BAS-132 tests → scheduler runtime;
  - BAS-132 tests → BAS-133 tests → live intake;
  - BAS-133 tests → BAS-134 tests;
  - BAS-133 live intake + BAS-134 tests → BAS-134 live topology.
- Existing external dependencies, including BAS-124 Evidence, are read from the latest
  append-only Observation and included in the downstream input.
- Missing or out-of-order observed dependencies fail closed instead of silently
  producing a partial dependency hash.
- `tests/test_project_execution_graph_seed.py` fault-injects the scheduler test input
  and both independent topology inputs, proving deterministic replay and downstream
  propagation.

## Real scheduler observation

Latest content-addressed artifact:

`output/graph/bas132-health-scheduler/919a263fbbdac639b92f37fae97c72d2fff102d93ecf899726f4bbe1dc3592be.json`

- Artifact SHA-256:
  `fd46ad17d86c53cffeed01dcb68b4575f2f1ee66eb2dc4d631ba277121ba8dfd`
- Runtime Observation:
  `obs_42bdd8f2a815356d01b85967f49f2bb4`
- State/freshness: `blocked/fresh`
- Task found: `false`
- Stable audit error:
  `Scheduled task was not found or could not be read`
- DAG-bound Harness input/result:
  `1241fba1832d45f0e8172907e0ff43b0c12d9efe3d146b39fb58d2236ff52285 /
  610d077385f6d8f911b1c1f41b747282f9138224ddf2417c842c2c47cb006312`
- Blockers:
  `scheduled_task_missing`,
  `health_operations_readiness_not_ready`,
  `health_evidence_integrity_not_ready`,
  `health_agent_gate_observation_not_ready`
- `mutation_performed=false`
- `external_write_allowed=false`

The `.env` exists, but there is no `KJDS_MONITOR_API_KEY`, registered monitor actor,
Supabase URL, Supabase anonymous key or Web identity binding. No Task Install was run.

## Append-only recovery result

The corrected second replay appended observations from `139` to `151` and returned:

- `task-bas128-pytest`: `passed/fresh`,
  `obs_c848d6830d4abcb5b8cf597a51912272`;
- `task-bas132-verifier-tests`: `passed/fresh`,
  `obs_3b0d2d23d71c08dc39732fc4ec6d0cc0`;
- `task-bas040-health-scheduler-deployment`: `blocked/fresh`,
  `obs_5b0e87f374d0db8ae22c51562ea08a0b`;
- `task-bas133-verifier-tests`: `passed/fresh`,
  `obs_71e9a0824a60a367d97e64dbb529d61c`;
- `task-bas133-authority-intake-live`: `passed/fresh`,
  `obs_3cac3c9912eefb6dfc3634d5373544d0`;
- `task-bas134-verifier-tests`: `passed/fresh`,
  `obs_1e28f4f9977f1a6083c0ce9b32a1fce8`;
- `task-bas134-authority-workflow-topology`: `blocked/fresh`,
  `obs_e4df92bccff4234be8e5d915cfbf00f3`.

The corrected recovery checkpoint had `151` observations. Materializing BAS-135 as its
own verifier-owned GoalTask plus stable Project/Engineering/Evidence nodes and edges
then produced the final Graph:

- revision `20260728_0070`;
- `32` tasks / `110` nodes / `123` edges / `164` observations / `77` bindings;
- Evidence `58`;
- authority source/review/grant `0/0/0`;
- workspace `blocked`;
- BAS-040 `blocked`;
- M0 operating-subject/scope authority and M0→M4 `stale`;
- Release `0.59` `REJECTED`;
- model self-certification and external write both `false`.

Latest final task identities:

- `task-bas128-pytest`: `passed/fresh`,
  `obs_4145b38166b45f509770102b6855cc66`;
- `task-bas132-verifier-tests`: `passed/fresh`,
  `obs_d735553807433974c38e936a2a3e4728`;
- `task-bas040-health-scheduler-deployment`: `blocked/fresh`,
  `obs_42bdd8f2a815356d01b85967f49f2bb4`;
- `task-bas133-verifier-tests`: `passed/fresh`,
  `obs_07dc307e29d69574b93e5029a889505f`;
- `task-bas133-authority-intake-live`: `passed/fresh`,
  `obs_c0fa5b1b06e23d2f8014a4132e02240e`;
- `task-bas134-verifier-tests`: `passed/fresh`,
  `obs_17c7000bc41b0edaba6b6651b6befce6`;
- `task-bas134-authority-workflow-topology`: `blocked/fresh`,
  `obs_8c426ee5add9768bc98cdfb6a36a298f`;
- `task-bas135-verifier-tests`: `passed/fresh`,
  `obs_1210b08d5c08d84dc9821674778a11d9`.

BAS-135 stable nodes are `plan:BAS-135`, `change:BAS-135`,
`code:graph-dependency-reverification`,
`test:graph-dependency-reverification` and `evidence:BAS-135`. All five receive
status only through the immutable BAS-135 GoalTask binding.

## Browser acceptance

The in-app browser read the running Web/API/PostgreSQL projection at the `151`
observation recovery checkpoint. The subsequent BAS-135 node materialization changed
only canonical Graph structure and was verified through the live authenticated Graph
API.

- Desktop TODO: BAS-132 latest runtime Observation, BAS-133 fresh tests and BAS-134
  fresh-blocked topology were all visible; `innerWidth=1440`,
  document/body width `1425`.
- 390px TODO: the same three latest Observation identities remained visible;
  `innerWidth=390`, document/body width `375`, with no horizontal overflow.
- Desktop Authority Graph: scheduler `blocked/fresh`, intake `passed/fresh` and topology
  `blocked/fresh` all drilled into their latest Observation/artifact/Evidence/Owner/SLA;
  console errors `0`.

Screenshots:

- `output/playwright/release-0.59.0/bas135/bas135-goal-todo-dependency-recovery-desktop.png`
  (`a86923b1b01b25097f1ddb1ebad85ba092263e5f60f9f3849fdceeb960176446`);
- `output/playwright/release-0.59.0/bas135/bas135-goal-todo-dependency-recovery-390.png`
  (`b15d9c6ff7b4416fba874b91df7bf52ff74c679eb988eee0f405187615ebc970`);
- `output/playwright/release-0.59.0/bas135/bas135-authority-graph-dependency-recovery-desktop.png`
  (`b133fd26c83546d714dc2101aca475805749e84bba58f7a001547aeda4b4f306`).

## Verification

- Full backend: `796 passed, 9 warnings in 41.07s`
- Scheduler manager + pure verifier: `10 passed`
- Graph seed + Agent Harness: `20 passed`
- Ruff focused checks: pass
- Full Ruff: pass
- Secret scan:
  `767` non-ignored worktree files and `581` historical paths; pass
- Web contract tests: `61 passed`
- `git diff --check`: exit `0`; existing CRLF conversion warnings only
- Real scheduler Plan: `planned_no_mutation`
- Real scheduler Audit: non-zero `not_accepted`, precise missing-task classification
- Real Graph recovery replay: `151` append-only observations
- Final BAS-135 canonical Graph materialization:
  `32/110/123/164/77` tasks/nodes/edges/observations/bindings
- No business Evidence, grant, Approval, Permit or external write was created

## Review findings

| Severity | Finding | Handling |
|---|---|---|
| P0 | None. | no-op |
| resolved P1 | Missing Windows Task was misclassified as generic audit failure on this host. | auto-fix with real exception-category observation and Windows test |
| resolved P1 | Full-DAG downstream re-verification reused old idempotency inputs and remained stale after an upstream change. | auto-fix with deterministic direct-dependency hashes and recovery fault tests |
| P1 | Supabase four-user topology is still absent. | defer to account owner + identity engineering; no synthetic users |
| P1 | Dedicated monitor credential and Windows Task are still absent. | defer to configuration owner; no borrowed operator/admin identity |

## Next safe action

The account owner must provision four independently authenticated Supabase users and a
separate exact-scope monitor credential. Operations may then run the existing explicit
Task Install and collect three consecutive result-0 completions. Only those new external
observations may advance BAS-134, BAS-040 and the monitor-owned M0 chain.
