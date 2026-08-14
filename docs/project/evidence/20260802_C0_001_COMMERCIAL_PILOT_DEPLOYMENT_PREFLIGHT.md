# C0-001 Commercial Pilot Deployment Preflight

Date: 2026-08-02

## Decision

- C0-001 engineering package: `PARTIAL`.
- Commercial Pilot Gate: `NO-GO`.
- The package is ready for a hosted pilot provisioning rehearsal, not for a
  production-readiness claim.

Local checks prove that the production-oriented package renders, rejects blank
scope, starts an exact-scope API, migrates an isolated database, creates
scope-bound backups, rejects an unsafe restore, and restores into a disposable
database. They do not prove hosted TLS, live customer isolation, continuous
backup operation, off-host retention, or production RPO/RTO.

## Implemented Boundary

- one deployment name, database volume, secret domain, and browser origin per
  customer;
- exact tenant/store values required by API and Web configuration;
- API credential profiles must carry the same explicit tenant/store scope;
- compact canonical customer scope is checked before migration or backup;
- distinct Supabase operator and approver bindings are required by the Web
  identity contract;
- external limited execution remains disabled in the example environment;
- only the edge service publishes host ports 80/443;
- the write-capable media worker is excluded from the first commercial pilot;
- secrets are file-backed and the secrets directory rejects unintentional Git
  additions by default;
- scheduled backup sidecar waits for a healthy scoped API and applies retention;
- operator backup and restore scripts bind manifests to scope hash, archive
  hash, and Alembic head.

## Verification

Command:

```powershell
.\deploy\commercial-pilot\scripts\preflight.ps1
```

Expected result: exit code `1`, because production-only checks remain
`UNKNOWN`. The report at
`deploy/commercial-pilot/runtime/preflight-report.json` recorded `PARTIAL`.

Local executable checks recorded `PASS`:

- `compose_static`;
- `identity_scope_binding`;
- `tls_template`;
- `compose_render`;
- `scope_fail_closed`;
- `identity_fail_closed`;
- `api_runtime_migration`;
- `scheduled_backup_package`;
- `backup_manifest`;
- `restore_guard`;
- `restore_drill`.

The rehearsal migrated PostgreSQL to `20260802_0087`. Both the sidecar and
operator-run backup produced 511595-byte custom-format archives whose manifests
matched archive SHA-256, customer-scope SHA-256, and Alembic head. Restore into
`kjds_pilot_restore` returned `PASS` with the same head. The measured local
restore duration was 5.809 seconds and is not a production RTO claim.

Additional checks:

```powershell
.\.venv\Scripts\python.exe scripts\verify_secrets.py
docker run --rm -v "${PWD}/deploy/commercial-pilot/scripts/backup-loop.sh:/tmp/backup-loop.sh:ro" postgres:17-alpine /bin/sh -n /tmp/backup-loop.sh
```

- secret scan: `PASS`, 1176 non-ignored worktree files and 595 historical paths;
- backup sidecar shell syntax: `PASS`;
- PowerShell AST parse for `_common.ps1`, `backup.ps1`, `preflight.ps1`, and
  `restore.ps1`: `PASS`;
- rehearsal Compose project cleanup: `PASS`, no remaining project containers.

## Production Blockers

- `production_backup_runtime`: `UNKNOWN`. Deploy the continuous schedule,
  retention monitoring, alerting, and off-host copy in the hosted target.
- `live_production_evidence`: `UNKNOWN`. Verify real TLS, Supabase login and MFA,
  and browser behavior at the production origin.
- Cross-customer negative isolation: `UNKNOWN`. Provision two isolated customer
  deployments and prove that credentials, database access, and backup/restore
  artifacts cannot cross boundaries.
- Production RPO/RTO: `UNKNOWN`. Run a timed failure and restore drill against
  hosted storage using an approved recovery objective.
- Production secrets and certificates: `UNKNOWN`. Inject them through the
  deployment platform; no real credential or certificate is stored here.

No blocker above may be converted to `PASS` from this local rehearsal alone.
