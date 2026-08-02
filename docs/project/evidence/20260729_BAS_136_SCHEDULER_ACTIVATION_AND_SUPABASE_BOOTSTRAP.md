# BAS-136 Evidence — Scheduler Activation and Supabase Bootstrap

## Decision

`BAS-136` accepts the real BAS-040 scheduler deployment on 2026-07-29 and
records a partial external Supabase bootstrap:

- the dedicated monitor identity, secret-free Windows Task definition and three
  consecutive native result-0 completions are real and externally observed;
- the Supabase `KJDS-059` project is real, healthy and configured locally with
  its public connection settings;
- Supabase Auth still has zero application users, so Web auth remains
  fail-closed in `legacy` mode and BAS-134 remains `blocked/fresh`;
- Release `0.59`, M0–M4, Pilot and Final Gates remain unaccepted.

No credential value, database password, raw Supabase user ID, Approval, Permit,
scope grant or external commerce write is recorded by this Evidence.

## Dedicated scheduler identities

The ignored project `.env` now contains:

- one existing exact-scope `r0-requester / operator` readiness credential;
- one new `kjds-monitor-scheduler-059 / monitor` credential;
- explicit `default / ozon-primary` scope for the monitor;
- distinct operator and monitor key material;
- `KJDS_HEALTH_REQUIRED=true`.

The values were generated and merged locally without printing them. The API
container was recreated so the seven-profile identity map became the live
runtime configuration. A real `ControlPlaneOnly` run then returned:

- control plane `200`;
- operations readiness `200`;
- Evidence integrity complete, `58` scanned, `0` invalid;
- Agent Gate Observation recorded against revision `20260728_0070`;
- `external_write_allowed=false`.

## Real Windows Task deployment

`scripts/manage-evidence-health-task.ps1 -Mode Install` performed the explicit
authorized mutation and installed:

- task `\KJDS-Evidence-Integrity-Health`;
- interval `15m`;
- execution limit `5m`;
- `IgnoreNew`;
- exact workspace `D:\KJDS\kjds`;
- a fixed `pwsh -NoProfile -NonInteractive ... -ControlPlaneOnly` action;
- no credential or secret in the command line.

The Windows Task Scheduler Operational channel was disabled. It was enabled
through a user-approved UAC operation before acceptance runs were collected.
Three explicit task executions then completed at:

- `2026-07-28T17:34:52Z`, result `0`;
- `2026-07-28T17:34:55Z`, result `0`;
- `2026-07-28T17:34:58Z`, result `0`.

The final real Audit returned:

- `status=accepted`;
- `task_found/enabled/definition_valid=true`;
- `action_valid/arguments_secret_free/working_directory_valid=true`;
- `trigger_valid/execution_limit_valid/overlap_policy_valid=true`;
- native history available;
- `matching_events=5`;
- latest `consecutive_successes=3`;
- `last_result=0`.

## Native event compatibility correction

The first real audit exposed a verifier bug rather than a scheduler failure:
Windows Event `102` confirms task completion but does not carry the process exit
result on this host. Event `201` is the native action-completed event and
contains `TaskName`, `TaskInstanceId` and `ResultCode`.

The verifier now reads Event `201`; it does not infer success from Event `102`
or from model/process self-report. The Windows mock rejects any event filter
other than `201`.

Focused verification:

- `tests/test_evidence_health_task.py`: `5 passed`;
- full backend: `796 passed, 9 warnings in 32.83s`;
- Web contracts: `61 passed`;
- Ruff focused check: pass;
- PostgreSQL/API/media-worker/Web: healthy;
- final real scheduler Audit: exit `0`, `accepted`;
- `git diff --check`: exit `0`, existing CRLF warnings only.

## Canonical Graph recovery

The real Graph observer appended the new scheduler, intake, topology and
dependency observations. Latest scheduler artifact:

`output/graph/bas132-health-scheduler/5e0ed3f84f1f6d86c5055a364b7f4754894cfa19de75658a03e85f5f3795feaa.json`

- artifact SHA-256:
  `ec65f7672f5b8465ace9fcbd7e411891682365ef5914725c52c30c6684645001`;
- BAS-040 Observation:
  `obs_867f9f0bd1141506a8ede8792b285ea2`;
- state/freshness: `passed/fresh`.

The canonical runtime now reports:

- revision `20260728_0070`;
- `32` tasks / `110` nodes / `123` edges / `184` observations /
  `77` bindings;
- `25 passed / 5 blocked / 2 no_data / 0 stale`;
- `77` verified nodes;
- Evidence `67`;
- scope-grant events `0`;
- Approvals `0`;
- workspace `blocked`;
- Release `0.59` `REJECTED`;
- external write and model self-certification both `false`.

## Real Supabase bootstrap

A new project was created in the account owner's existing Supabase
organization:

- name: `KJDS-059`;
- project ref: `wqwjdxcpzzobptvholcy`;
- public URL: `https://wqwjdxcpzzobptvholcy.supabase.co`;
- plan/status: Free / Healthy;
- region: South Asia (Mumbai), `ap-south-1`;
- Email provider enabled;
- email confirmation enabled;
- anonymous sign-in disabled;
- Site URL `http://localhost:3000`;
- automatic exposure of new tables disabled;
- automatic RLS enabled.

The ignored `.env` contains the project ref, public URL, publishable key and
locally generated database password. Secret values are not present in this
Evidence or the desktop record.

The real Auth Users page reports `No users in your project`. Therefore:

- `KJDS_WEB_AUTH_MODE` was not changed to `supabase`;
- `KJDS_WEB_USER_ACTORS_JSON` remains empty;
- no synthetic email, alias, user UUID or role switch was created;
- the running Web remains healthy in `legacy` mode.

Latest BAS-134 topology artifact:

`output/graph/bas134-authority-workflow-topology/3aac04c51d8c83705f724fbb0f2452f2a52f4798c796547c7efeaa852fc7f59e.json`

- artifact SHA-256:
  `c7ca126665022764b879d044bff943afc82f7b0f6e2013ba48a05618925f070b`;
- Observation:
  `obs_4c3d58a056e11172be602265014c5b1e`;
- state/freshness: `blocked/fresh`;
- blocker: `web_auth_mode_not_supabase`.

## Remaining external action

The account owner must provide four independently controlled real Supabase Auth
users for:

`r0-requester → kjds-owner-lunar → r0-risk → r0-admin`.

Only after those four users exist may identity engineering store their
non-secret UUID-to-actor bindings, switch Web auth to `supabase`, recreate Web
and obtain a new passed BAS-134 external topology Observation. Source Evidence,
independent review and compliance recording must still be performed by their
respective authenticated principals.

The no-secret desktop handoff is:

`C:\Users\Lunar\Desktop\KJDS配置记录_20260729.md`

SHA-256:
`323d87dcb18e5fdd1b06cec3e7eb190421a850ebf1632f1aac994f11bf326623`.

## Authoritative continuation acceptance — four-party Supabase identity

The earlier zero-user/legacy/blocked statements above remain the historical
bootstrap observation. They were superseded by a new external observation on
2026-07-29 after the account owner explicitly authorized identity creation and
local record retention.

Four distinct, auto-confirmed Supabase Auth users now exist for the exact
workflow actors:

- `r0-requester` — `operator`, subject;
- `kjds-owner-lunar` — `reviewer`, owner;
- `r0-risk` — `risk + approver`, independent reviewer;
- `r0-admin` — `admin`, recorder.

The user labels use the RFC-reserved `kjds059.example.com` subdomain. They are
real, independently authenticated Supabase users with four different strong
passwords, but they are not external mailboxes and no email was delivered to a
third party. Each credential completed a direct Supabase password-token
exchange with HTTP `200`. Raw passwords, API keys and user UUIDs are absent
from this Evidence.

The UUID hashes are:

- `r0-requester`:
  `be1f5391dd2938078472cdb4e9ccbfbab4741388eb136b00cdba86fb6607c2d3`;
- `kjds-owner-lunar`:
  `57caa8df85b5cea685568ec3527713738c81953fc8fe8cc3d3087d392424f720`;
- `r0-risk`:
  `b68942980b6971ea322c5cd5ce9ad7e17dff5c709dc6b2e4283b8bd47c090f73`;
- `r0-admin`:
  `603794b23257e996e2a409623a3615442f9dc21d84083a2a27428601b3960d7b`.

The ignored `.env` now contains:

- `KJDS_WEB_AUTH_MODE=supabase`;
- four UUID-to-actor bindings;
- the four local verifier credentials;
- explicit `default / ozon-primary` scope for all four actors;
- a distinct `r0-risk / approver` role, separate from the operator.

The Web and API containers were recreated. All delivery containers are
healthy. A real Web `r0-requester` login returned `303` to `/`; the authenticated
Authority topology endpoint returned:

- HTTP `200`;
- `state=passed`;
- `web_user_bindings=4`;
- `api_chain_ready=true`;
- `web_chain_ready=true`;
- no blockers;
- `external_write_allowed=false`.

The Graph observer now establishes that authenticated Web session itself
before reading the secret-free topology. No credential enters the artifact,
Graph node, Observation or log summary.

Latest accepted BAS-134 topology artifact:

`output/graph/bas134-authority-workflow-topology/4dfc79fc1f4f09a8f6302b72835a245beb60353e1993a2fbc5dd6f12a80a9c79.json`

- artifact SHA-256:
  `8724a042c910f3e5bdeedd55da6a6d05966d8d57a34f8975f2f9fe06fda88d10`;
- Observation:
  `obs_e3029ad8452afd294f20ac93972fecdc`;
- state/freshness:
  `passed/fresh`;
- observation input SHA-256:
  `1800b5b69c14d4c4c4de23db83728c92c40e72a7708b0e858e28794627203fa9`.

The canonical runtime after re-observation reports:

- revision `20260728_0070`;
- `32` tasks / `110` nodes / `123` edges / `204` observations /
  `77` bindings;
- `26 passed / 4 blocked / 2 no_data / 0 stale`;
- `77` verified nodes;
- BAS-040 and BAS-134 `passed/fresh`;
- M0 current authority and scope authority `no_data`;
- M1–M4 blocked by the missing real downstream facts;
- workspace `blocked`;
- Release `0.59` `REJECTED`;
- external write and model self-certification both `false`.

Credential retention is split deliberately:

- ignored runtime store: `D:\KJDS\kjds\.env`;
- current-Windows-user DPAPI encrypted backup:
  `C:\Users\Lunar\Desktop\KJDS-Supabase-Auth-Credentials-20260729.clixml`,
  SHA-256
  `a48069d6e94f8afc34b1554743bbf4af7a0c267a0ea909b50cf944ad98304cbb`;
- no-secret operator record:
  `C:\Users\Lunar\Desktop\KJDS配置记录_20260729.md`,
  SHA-256
  `54e16752524832ae874d4472512e6e654f992cd63a76dd40b747053aa35250ca`.

No source Evidence, independent review row, scope grant, Approval, Permit or
commerce write was synthesized. The next safe external step is an authenticated
owner source-Evidence submission followed by a distinct risk review and admin
recording.
