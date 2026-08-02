# ADR-0045: Native Scoped Ozon Read Pilots and Runs

Date: 2026-07-28<br>
Status: Accepted for BAS-121<br>
Requirements: BR-097<br>
Depends on: ADR-0020, ADR-0034, ADR-0041, ADR-0044

## Context

The original read-only Pilot predates tenant/entity/store authority. Its create mutation is
authenticated, but Pilot list/get/evaluation are public and Pilot/Run records contain no operating
scope. Run list/get are authenticated only by role and query global rows. Consequently, knowing a
Pilot or Run ID can reveal another tenant's account alias, target hash, worker, result summary and
Evidence IDs.

BAS-120 correctly scopes the later Catalog handoff, but cannot make the acquisition authority
itself tenant-safe. Hiding global rows after serialization is not sufficient because latest/current
selection and Evidence traversal must occur only after SQL scope filtering.

## Material solution selection

Decision profile: `best_solution`.

- Route-only authentication: closes anonymous reads but leaves cross-tenant ID access and global
  query semantics.
- Duplicate a second scoped Pilot/Run subsystem: cleaner migration boundary but creates two
  schedulers, two quota authorities and divergent workers.
- Add a complete-or-empty native scope tuple to the existing Pilot aggregate and authorize Runs
  through their Pilot FK: one quota/runtime authority, legacy preservation and SQL-first isolation.

Selected: extend the existing aggregate. The second subsystem is rejected because it duplicates the
read workflow. Route-only authentication is rejected because role membership is not resource
authority.

## Decision

New native Pilot rows freeze:

```text
tenant_ref + entity_ref + store_ref
scope_grant_authority_sha256 + scope_evidence_authority_sha256
scope_as_of
```

The tuple is complete or entirely empty. Existing rows remain legacy with the tuple empty and are
not guessed or backfilled.

The authenticated API:

1. resolves Principal tenant/store and one current entity grant;
2. independently projects every Pilot Evidence target into that exact scope;
3. creates/replays the Pilot under native
   `tenant + entity + store + idempotency_key`;
4. filters Pilot list/get/evaluation and all lifecycle mutations by the exact tuple before using
   the core state machine;
5. filters Run list/get/usage and worker mutations by joining `read_only_pilot_runs` to the
   authorized Pilot in SQL.

Legacy idempotency remains globally unique only among legacy rows; native idempotency is scoped.
Run idempotency remains globally unique because worker requests already use a globally generated
key and replaying it across scopes must conflict rather than alias.

Raw domain services remain available only as internal authorities for existing tests and recovery.
Tenant-facing routes use the scoped authority. Missing entity scope returns `no_data` for
collections and rejects mutations before raw Pilot/Run/Evidence reads. A resource outside scope is
reported as not found in authorized scope.

## Authority and safety boundary

- `pilot_reader` is permission to operate a scoped read worker, not permission to choose tenant,
  entity or store.
- A current grant is required at each tenant-facing mutation. Revoked authority blocks later
  attest/review/activate/start/checkpoint/finalize transitions.
- Original Pilot Evidence remains immutable and independently scoped.
- Runs inherit scope only through their immutable Pilot FK; no client-submitted run scope exists.
- The product/finance read allowlist, request/target quota, credential isolation, raw response
  checkpoint and Evidence integrity contracts remain unchanged.
- No Ozon product, inventory, price, promotion, order, return, advertising or finance write is
  introduced. No Supplier contact, purchase or payment action is introduced.

## Migration

Revision 0063:

- adds the nullable native tuple to `read_only_pilots`;
- enforces complete-or-empty authority;
- replaces the old global Pilot idempotency unique constraint with legacy and scoped partial unique
  indexes;
- adds a scope/time index used before Run joins;
- leaves every existing Pilot, Run, attestation and Evidence row unchanged.

The real database is forward-only. Empty-database base-to-head and 0063-to-0062-to-0063 replay are
performed only against an explicitly named independent PostgreSQL database using
`KJDS_DATABASE_URL`.

## Acceptance

1. Pilot create requires auth, role, store, entity grant and independently scoped current Evidence.
2. Client cannot submit tenant/entity/grant/Evidence authority.
3. Missing entity list is `no_data` without raw reads; create/lifecycle/run mutations create zero
   rows.
4. Anonymous Pilot and Run list/get are 401.
5. Cross-store and cross-tenant Pilot/Run access is 403 or authorized-scope not found.
6. List/get/evaluation/usage filter in SQL before serialization.
7. Worker start/checkpoint/finalize cannot operate a Run outside its exact scope.
8. Legacy rows remain byte/hash stable and are absent from native tenant reads.
9. PostgreSQL rejects partial authority and same-scope duplicate keys while allowing the same key
   in a different native scope.
10. BAS-120 handoff verifies the Run in the same authorized scope before using its raw Evidence.
11. Full tests, OpenAPI, migration replay, Compose and desktop/390px browser acceptance pass.
12. All external writes remain false.

## Consequences

A production read Pilot must be recreated under verified native scope rather than having legacy
rows silently upgraded. The current real legacy Pilot/Run therefore remains auditable but is
intentionally unavailable to tenant-scoped acquisition until an independent entity grant and
Evidence binding exist.
