# ADR-0038: PostgreSQL RLS and scoped read-model envelope

Status: Accepted for phased M0 implementation

Date: 2026-07-28

Owner: Identity and Data Governance

Approver: Ultimate Start Gate PM/RA authority

## Context

KJDS legacy operating tables were created before tenant/entity/store became an explicit
authorization tuple. Several migrations enabled PostgreSQL Row Level Security, but the application
role still owns tables, no complete tenant/entity/store policies exist, and no production contract
proves that pooled connections reset request scope. `ENABLE ROW LEVEL SECURITY` by itself is not
effective tenant isolation and must not be reported as such.

Marketplace Observation is the first M0 read model to cross this boundary. Its snapshot currently
stores only `store_ref`; historical rows also use the shared label `external`. The old authenticated
GET route queried every Principal store plus `external` and returned raw item details. That label
does not establish tenant or legal-entity ownership, and a global external row cannot be published
to every tenant merely because its source was a public page.

## Decision

### Application authority now

Introduce `ScopedMarketplaceObservationAuthority` and
`ScopedMarketplaceCatalogAuthority` in front of their raw workspaces. They share one
Principal/entity/store/`as_of`/Evidence envelope rather than duplicating authorization policy.

1. The API validates Principal store access and resolves one current append-only entity grant at a
   single explicit `as_of`.
2. Missing or ambiguous entity authority returns `no_data/blocked` before the raw workspace is
   called.
3. The raw query is constrained to the exact requested `store_ref` and cutoff before latest-fact
   deduplication. It never unions the legacy `external` label.
4. Every returned item requires current immutable Evidence that is either independently direct
   scoped or independently bound by grade A Evidence to the exact tenant/entity/store and target
   hash.
5. Unbound, cross-scope, expired, future or damaged rows expose only aggregate counts and reason
   codes. Product identity, supplier, price, source URL, Evidence ID and other business content are
   not returned for excluded rows.
6. The response is a versioned envelope with scope authority hash, Evidence authority hash,
   deterministic snapshot hash, counts, source gaps, Owner/SLA/next action and
   `external_write_allowed=false`.
7. Shared public-market observations remain excluded until a separate versioned publication
   authority proves source licence/terms, collection method, permitted audience, freshness,
   revocation and tenant-safe disclosure. “Public page” is not itself a sharing grant.

Raw capture remains an internal research ingestion mechanism. It may create grade C, unbound
Evidence, but capture does not create entity authority, a Supplier Offer, actual cost, candidate
readiness, Pilot approval or external execution permission. Authenticated capture must target an
authorized store and have a current entity grant; an independent reviewer still supplies the
separate Evidence binding.

For Marketplace Catalog, exact-store snapshot import time and item observation time are filtered
before offer-level latest-fact de-duplication. Canonical Product bindings are projected only when
`bound_at <= as_of`; a future binding cannot rewrite a historical decision. Every returned item
requires the same current/intact/direct-or-independently-bound Evidence authority as an
Observation. Catalog import, existing-listing binding and catalog-backed RFQ creation execute this
scope preflight before the raw mutation. Scoped Analytics and Commerce OS consume only the scoped
Catalog envelope. The envelope does not grant candidate scoring, content generation, Pilot
approval or external execution.

### PostgreSQL RLS envelope

Database enforcement is a later forward-only phase and uses the same tuple:

- add nullable native `tenant_ref`, `entity_ref`, `store_ref` and immutable scope-authority hash;
- allow either a complete tuple or all-null legacy state, with no default-tenant/store backfill;
- classify and reconcile legacy rows through Evidence before any native tuple is populated;
- keep owner/migration roles separate from a non-owner, non-`BYPASSRLS` application role;
- create deny-by-default policies for parent rows and child rows through their immutable parent;
- set request scope transaction-locally only after authenticated application authorization, reset
  it on every pooled checkout/check-in, and test missing/stale/cross-request settings;
- run shadow-policy and dual application/database checks before `FORCE ROW LEVEL SECURITY`;
- provide an audited dedicated administration path instead of a hidden application-role bypass;
- retain application fail-closed checks if FORCE/policies must be disabled during emergency
  rollback.

Phases are: classify legacy rows → add native columns and complete-or-empty constraints → shadow
policy → dual checks and pool-reset tests → non-owner application role → FORCE RLS → remove legacy
compatibility paths. No phase may stamp ambiguous data, rewrite immutable Evidence, or silently
assign `external` observations to a tenant.

## Best-solution decision

Selected: Evidence-bound application authority now, followed by measured native RLS enforcement.
It gives an immediately testable no-leak seam while preserving immutable legacy rows and a
reversible migration path.

Rejected:

- treating `store_ref` as sufficient authority: it has no tenant/entity provenance;
- sharing all `external` rows: public visibility does not prove collection or redistribution rights;
- enabling FORCE RLS immediately: current rows and roles lack the required native authority;
- relying only on application filters indefinitely: one missed query can bypass isolation;
- creating a second scoped Observation database: it would split truth and complicate lineage.

Invalidation trigger: PostgreSQL cannot enforce the complete tuple without operationally unsafe
pool behaviour, or an accepted shared-market publication authority requires a separate audience
model. Either change requires a new ADR and migration plan.

## Compatibility and rollback

Raw workspaces keep internal list/page methods for tests and controlled migration tooling.
Authenticated Observation and Catalog API consumers move from unscoped arrays to scoped envelopes
and read `items`. `as_of` is explicit in Observation list/page and Catalog latest-item contracts.
Existing rows and their hashes are not updated.

The current slice adds no RLS migration and makes no claim of database-enforced tenant isolation.
Future RLS migrations are forward-only. Emergency rollback may disable FORCE/policies under an
audited migration role, but the application authority remains fail closed and external writes
remain disabled.

## Acceptance

- anonymous access is `401`; unauthorized store is `403`;
- missing entity scope returns no data without calling the raw Observation workspace;
- exact store filtering happens in the database before fingerprint deduplication;
- fixed `as_of` excludes later observations and replays deterministically;
- direct-scoped or independently bound current Evidence is included;
- unbound, wrong-scope, bad-hash, future, expired and damaged Evidence is excluded without leaking
  row identifiers or values;
- legacy `external` rows are not returned by store-scoped APIs;
- Catalog latest facts filter snapshot import, item observation and binding time before projection;
- Catalog import, binding and catalog-backed RFQ fail before mutation when entity or Evidence scope
  authority is missing;
- scoped Analytics/Commerce OS do not call the raw global Catalog;
- list and cursor-page responses share the same envelope semantics;
- Web renders loading, error, no-data and scoped item states without client-side authority or profit
  calculation;
- capture remains research-only and creates no Offer, actual cost, approval, Permit or external
  side effect;
- PostgreSQL RLS is reported as pending until role, policy, FORCE and connection-pool tests pass.

Review trigger: native Observation scope columns, shared-market publication, tenant-wide research
libraries, RLS policy rollout, or a new browser/plugin ingestion adapter.
