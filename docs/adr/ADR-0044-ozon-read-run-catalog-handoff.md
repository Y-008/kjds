# ADR-0044: Governed Ozon Read-Run to Catalog Handoff

Date: 2026-07-28<br>
Status: Accepted for BAS-120<br>
Requirements: BR-096<br>
Depends on: ADR-0020, ADR-0022, ADR-0034, ADR-0041, ADR-0043

## Context

KJDS already has both sides of the official Ozon Catalog acquisition boundary:

1. the isolated `OzonReadOnlyWorker` reads only the admitted Seller API product endpoints and
   checkpoints an immutable grade-A two-response bundle into Evidence through `PilotRunService`;
2. the Marketplace Catalog validates that bundle and, after BAS-119, persists a native
   tenant/entity/store/Evidence/adapter authority tuple.

The two modules are intentionally not coupled today. An operator can manually copy the raw response
Evidence ID into the Catalog import request, but no durable state proves which read run was handed
off, whether the exact frozen scope and adapter contract were used, or whether an interrupted
internal import was replayed safely.

The handoff cannot be automatic at read completion because raw Seller API Evidence still needs an
independent scope binding. It also cannot become a second workflow engine or grant the read worker
Catalog ownership.

## Material solution selection

Decision profile: `best_solution`.

Feasible options:

- keep the Evidence ID copy/paste flow: minimal code, but no durable recovery or run-to-snapshot
  audit and high operator error risk;
- call Catalog directly from the isolated read worker: fast, but crosses the network/credential
  trust boundary and would let the worker select business scope;
- add a small control-plane handoff ledger over existing run, Evidence, adapter and Catalog
  authorities: one extra transactional record, deterministic replay and no new external authority.

Selected: the bounded handoff ledger. It has the highest long-term risk-adjusted value because it
keeps source acquisition, scope review and Catalog truth independently authoritative while making
their transition recoverable. The worker-direct alternative is rejected for authority coupling.
The no-action option is rejected because manual copying cannot meet M1 lineage and replay
acceptance.

Invalidation condition: replace this ledger only if an accepted future ingestion/outbox authority
offers the same exact-scope, immutable-request and crash-recovery guarantees without moving
canonical Catalog ownership.

## Decision

Add `CatalogReadRunHandoffService` and one native-only handoff table. A handoff freezes:

```text
tenant_ref + entity_ref + store_ref + scope grant hash
run_id + unique verified raw-response Evidence ID
scoped Evidence-authority hash
effective source-adapter contract JSON/hash
request hash + operator id + prepared/completed/blocked state
Catalog snapshot ID/hash after completion
```

The authenticated transition is:

1. resolve Principal store and one current entity grant;
2. require a completed, successful `ozon.product.read` run with exactly one verified raw response;
3. independently project that Evidence into the exact tenant/entity/store scope;
4. compile the admitted Ozon Catalog adapter contract;
5. create or replay a `prepared` handoff under
   `tenant + entity + store + idempotency_key`;
6. invoke the existing Catalog import with the server-frozen authority and a handoff-derived
   Catalog idempotency key;
7. record the resulting immutable Catalog snapshot ID/hash as `completed`.

If the process stops after step 5 or 6, the same request resumes from the stored frozen authority.
Concurrent callers converge on the same handoff and Catalog snapshot. A changed run, scope,
Evidence or contract under the same key conflicts. Deterministic Catalog rejection marks the
handoff `blocked` with a machine-safe code; infrastructure failure leaves it `prepared` for retry.

The table is not a queue. It schedules nothing, acquires no lease and contacts no provider.

## Authority and failure boundary

- The raw Evidence ID comes only from `PilotRunService`; a client cannot substitute an arbitrary
  record after run verification.
- Independent Evidence scope binding remains mandatory before `prepared`.
- The server, not the client, freezes grant and adapter authority.
- A revoked/replaced grant cannot resume an older prepared handoff.
- Missing credentials or no active read pilot is `no_data` outside this handoff; the service never
  claims that a live Seller API read occurred.
- Catalog parser/hash/identity drift is blocked without a Catalog snapshot.
- The transition creates no Product binding, Supplier Offer, actual cost, content rights, Listing,
  Approval, Permit, inventory, price, purchase, payment or advertising action.
- `external_write_allowed=false` in every response.

## API

- `POST /v1/marketplace-catalog/ozon/import-read-run`
- `GET /v1/marketplace-catalog/ozon/read-run-handoffs`
- `GET /v1/marketplace-catalog/ozon/read-run-handoffs/{handoff_id}`

All routes require authentication, role and exact store scope. Lists are filtered in SQL before
serialization. Missing entity authority returns no data for reads and rejects creation before a
handoff row.

## Acceptance

1. Successful handoff binds one verified product read run to one scoped Catalog snapshot.
2. No client-provided Evidence, tenant, entity, grant or adapter authority is accepted.
3. Replay returns the same handoff/snapshot without rereading Ozon.
4. Same key with changed run/scope conflicts; two scopes are independent.
5. Crash/retry from `prepared` converges on one Catalog snapshot.
6. Concurrent preparation converges without duplicate Catalog rows.
7. Bad/missing/raw-response Evidence, finance runs, failed runs and contract drift create no
   Catalog snapshot.
8. Missing/revoked scope cannot prepare or resume.
9. List/get cannot cross tenant/entity/store and anonymous access is 401.
10. PostgreSQL rejects partial scope, invalid state/result combinations and duplicate scoped keys.
11. Empty PostgreSQL base-to-head and 0062-to-0061-to-0062 replay pass.
12. Real forward migration preserves all read runs, Evidence and Catalog rows/hashes.
13. Full tests, OpenAPI, Compose and browser readback prove no external side effect.

## Consequences

This makes the existing official read path operationally usable without weakening scope review or
moving Catalog truth into a connector. A real completed native handoff still requires production
credentials, an active read-only pilot, an independently bound entity grant and original response
Evidence. Until those exist, live state remains `no_data`.
