# DATA-COV-002 — Append-only Coverage Ledger Evidence

## Issuance authority deployment contract

Revision `20260804_0095` requires two externally provisioned PostgreSQL
principals with exact attributes: a `NOLOGIN`/`NOINHERIT` owner and an isolated
`LOGIN`/`NOINHERIT` issuer runtime. The generic application and migration
principals are not members of either principal and have no issuer-function
execution right. Neither issuer role may have any role member. Role absence,
attribute drift, or any unexpected membership fails the migration before
ledger objects are created; runtime construction repeats the global membership
and generic `SET ROLE` checks.

Membership validation is bidirectional: owner, issuer runtime, and the actual
generic runtime must be isolated whether they appear as the granted role or as
the member of any other role. The migration, trigger, function, startup factory,
and per-call port checks therefore reject both direct and transitive privilege
drift before accepting reserved Evidence.

PostgreSQL generates a database-internal issuance key during migration and
stores it only in an owner-readable authority row. Neither the generic runtime
nor the issuer runtime can read it. The issuer runtime can invoke only a
`SECURITY DEFINER` function with a fixed `pg_catalog, public` search path. That
function validates the canonical contract, purpose, exact scope and time
metadata; then it atomically creates the blob, reserved Evidence record, and
issuance receipt. The PostgreSQL application process does not receive a signing
key and cannot pre-sign or directly insert reserved intake Evidence. The
reserved-Evidence trigger requires both the owner `current_user` produced by the
function and the exact issuer `session_user`, so even a mistakenly granted owner
membership cannot use `SET ROLE` to bypass the function. The trigger, issuer
function, and issuer port each re-check zero membership and deny the call if the
runtime login gains owner `SET ROLE` capability after startup; revocation restores
the valid issuance path without accepting any intervening Evidence. They also
re-check the complete owner/runtime role-attribute matrix on every issuance, so
post-startup changes to login, superuser, inheritance, role/database creation,
replication, or row-security bypass privileges fail closed with zero new Evidence.

The database time contract mirrors the service: `data_as_of` is mandatory,
issuer authority time cannot be in the future, and both `data_as_of` and the
current authority check must precede any upstream expiry. Missing, future, or
expired authority metadata is rejected before Evidence insertion.

G-1 creates disposable owner, issuer-login, and generic-runtime principals,
generates their credentials in process memory, injects separate generic and
issuer DSNs, runs migration replay, and removes the database and principals in
`finally`. Credentials are neither committed nor serialized into the G-1
report. Deployment must provide the same two-connection separation; missing or
misbound issuer credentials fail runtime construction closed.

Before touching the fixed G-1 database or cluster-global role names, each run
atomically acquires a random-token lease in the PostgreSQL admin database.
Database and role comments store only that token's SHA-256 ownership receipt,
while lease state records exactly which resources this run created. A competing
run and a failed run encountering pre-existing production roles perform no
DROP; cleanup verifies the receipt and deletes only resources owned by its run.

The raw issuer engine is not stored on `EvidenceService` or `RuntimeServices`.
Runtime composition creates the narrow issuer port only inside
`GlobalDataCoverageEvidenceAuthorityAdapter`, together with the trusted intake
attestation authority and current scope authority.
`KJDS_RUNTIME_DATABASE_URL` is mandatory and must name a non-migration login;
there is no fallback from runtime composition to the migration connection.

## Scope

DATA-COV-002 adds a governed, exact-scope, append-only projection for the frozen
DATA-COV-001 manifest and native-capability contracts. It does not collect data,
call a network or model provider, create a domain Fact, or expose an API.

The service accepts only `principal`, `store_ref`, `data_as_of`, an idempotency
key, and two server-issued intake Evidence IDs. Tenant, entity, current scope
authority, canonical payloads, source contract versions, and denominator claims
are derived and verified by server authorities.

## Trust and time model

- Manifest, native-capability, and denominator Evidence use reserved sources and
  purpose-specific issuance through `GlobalDataCoverageEvidenceAuthorityAdapter`.
- The issuance hash binds exact current scope, source contract ID/version,
  attestation contract/version/hash, issuer hash, payload hash, and upstream
  effective/recorded interval.
- Reserved intake source references include that issuance hash, so identical
  payload bytes under a different issuer, contract version, attestation, or
  validity interval conflict instead of replaying an older Evidence record.
- Local Evidence `recorded_at` is ingest time. Historical admissibility uses the
  independently attested upstream recorded/effective interval.
- Authority is checked with a trusted current clock; `data_as_of` remains a
  separate historical cutoff.

## Persistence contract

Revision `20260804_0095` adds one immutable snapshot table and seven immutable
typed child tables for native caps, fields, failed pages, windows, conflicts,
Evidence links, and events. Every child carries the exact scope and a
server-stamped transaction ID, enforced by composite foreign keys and a
same-transaction trigger.

PostgreSQL deferred conservation joins immutable Evidence blobs and validates
the canonical manifest, native-capability, and denominator payloads against the
typed root/child projection. It also validates exact-scope supporting Evidence,
effective intervals, typed counts, role-specific Evidence bindings, source
contract versions, full-coverage semantics, the two-event terminal chain, a
database-recomputed event hash, and canonical event Evidence payload/metadata.
UPDATE/DELETE is rejected for all ledger rows and all four coverage Evidence
sources.

The issuer function and downgrade both acquire the same transaction advisory
lock before touching authority, Evidence, or ledger tables. This serializes
in-flight issuance with migration rollback and removes their inverse table-lock
ordering cycle.

## Idempotency and replay

The row ID is independent and random. Concurrent writers contend only on the
named exact-scope idempotency constraint. The sole winner persists one snapshot,
one child set, and two event Evidence records; losers replay only after exact
scope, authority, request, payload, version, and hash equality is rechecked.

## Rollback

Downgrade uses the writer-compatible global lock order: ledger tables first,
then Evidence blobs/records and lineage. Any ledger row, reserved-source
Evidence, or related lineage on either edge blocks downgrade. PostgreSQL tests
hold an in-flight writer while downgrade waits, prove the writer can still take
its later Evidence locks without a lock cycle, and verify that the failed
downgrade preserves the head, tables, triggers, and data. Empty
`0094 -> 0095 -> 0094 -> 0095` replay remains the supported rollback proof.
The externally provisioned principals survive revision downgrade so the empty
re-upgrade can revalidate the same principal contract; the deployment/G-1
lifecycle owner removes them after database teardown.

## Boundaries

The receipt remains an Observation with `formal_fact`, `decision`, `approval`,
`permit`, `pilot`, `outbox`, and `external_write` fixed to `false`. The only
runtime/deployment addition is a private narrow issuer port and its ephemeral
G-1 principal lifecycle. The raw issuer engine is not a `RuntimeServices`
capability. Only the API process receives the issuer DSN; media and Ozon workers
do not. No router, public API, OpenAPI, scheduler, outbox, network adapter,
dependency, customer payload, or external-write path is introduced.
