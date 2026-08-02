# Commercial Pilot Deployment

This directory contains the minimal production-oriented package for the
commercial pilot gate.

It is deliberately scoped to one customer, one app, one database, one secret
domain, and one browser-facing origin.

## What this package covers

- production-oriented Compose overlay;
- single-customer scope validation;
- TLS termination template;
- file-backed secret references only;
- scheduled backup with retention plus controlled restore scripts;
- machine-runnable preflight with explicit PASS/PARTIAL/MISS/UNKNOWN output.

## What this package does not claim

- no production evidence;
- no cross-customer negative test in a real tenant boundary;
- no live RPO/RTO proof from a production environment;
- no claim of commercial `PASS` until the pilot runs in the real hosted target.

## Suggested flow

1. Copy `customer-scope.example.env` to a local, ignored `.env` or load the
   values into your deployment system.
2. Populate the file-backed secrets named in `secrets/README.md`.
3. Validate the render with `scripts/preflight.ps1`.
4. Run `scripts/backup.ps1` and `scripts/restore.ps1` against a disposable
   rehearsal database.
5. Only after real production checks should the gate move beyond `PARTIAL`.

## Runtime contract

- `KJDS_DEPLOYMENT_NAME` must be non-empty.
- `KJDS_CUSTOMER_SCOPE_JSON` must be present and non-empty.
- Customer scope must use compact canonical JSON so scheduled and operator-run
  backup manifests compute the same scope hash.
- `KJDS_API_TENANT` and `KJDS_API_STORES` must match that customer scope.
- `KJDS_DATABASE_NAME` must be isolated per customer deployment.
- API credentials must carry explicit tenant/store scope, and Supabase Web
  bindings must separate operator and approver users.
- TLS cert/key and application secrets must come from files or external secret
  injection.
- The reverse proxy only exposes 80/443; internal services stay off public
  host ports.
- `KJDS_BACKUP_DIRECTORY` must resolve to durable storage outside the database
  volume. The backup sidecar waits for the scoped API and migrations to become
  healthy, then runs immediately and at
  `KJDS_BACKUP_INTERVAL_SECONDS`, retaining files for
  `KJDS_BACKUP_RETENTION_DAYS`.

## Local rehearsal example

```powershell
$envFile = "deploy/commercial-pilot/customer-scope.example.env"
docker compose --env-file $envFile -f deploy/commercial-pilot/compose.production.yaml config
```

For a full rehearsal, use the preflight script:

```powershell
.\deploy\commercial-pilot\scripts\preflight.ps1
```

The preflight exits non-zero while any commercial production proof remains
`MISS` or `UNKNOWN`. Inspect `runtime/preflight-report.json`; do not treat a
successful local rehearsal as permission to override the production gate.
