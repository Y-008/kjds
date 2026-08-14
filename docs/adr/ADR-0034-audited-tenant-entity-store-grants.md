# ADR-0034: Audited tenant/entity/store grants

Status: Accepted for M0 implementation

Date: 2026-07-27

Owner: Identity Governance

Approver: Ultimate Start Gate PM/RA authority

## Context

`Principal` authenticates an actor and bounds tenant/store access, but it does not carry legal or
operating entity authority. Copying `tenant_ref` into `entity_ref` would invent a fact and make
profit, approval, settlement, and audit scopes unreliable. M0 therefore needs a formal authority
that resolves an entity for an authenticated actor, tenant, and store at a deterministic `as_of`.

## Decision

Use one append-only `ScopeGrantAuthority` event ledger. A `grant` or `revoke` event freezes tenant,
entity, store, subject actor, effective time, accepted grade A review Evidence ID and verified
content hash, reason, independent recording actor, idempotency key, request hash, and recorded time.
Authority Evidence is a two-record authenticated chain:

- the account owner submits a grade B immutable source using
  `kjds-scope-authority-source-v1`, with every frozen scope dimension and decision;
- a different authenticated reviewer creates a grade A JSON review using
  `kjds-scope-authority-review-v1`, records the decision/checks/rationale under that reviewer's
  `created_by`, and links it to the exact source ID/hash with an immutable lineage edge.

Uploader-authored `reviewed_by` metadata is not review authority. Owner, reviewer, compliance/admin
recorder and subject must be four distinct authenticated actors; exact scope, decision, effective
time, source hash and lineage mismatches fail closed. A matching independent rejection blocks
admission.

The current scope is derived from effective events; no mutable current-row table is introduced.
The service rejects self-grants, cross-store writes, weak/invalid Evidence, and idempotency-key
payload drift. Multiple active entities for one actor/store are `blocked`, not guessed. A revoked,
missing, expired, or damaged grant yields `entity_ref=null` with a machine-readable reason.

`TruthGovernanceService` consumes this authority dynamically and includes its hash. Tenant/store
access still comes from the authenticated `Principal`; a grant cannot widen it. The M0 endpoint
remains read-only and `external_writes=false`. Grant administration is an internal governance
write restricted to compliance/admin identities and is not an Ozon, supplier, purchase, payment,
or advertising write.

### Scoped Evidence binding

Entity authority alone does not prove that an arbitrary Evidence record belongs to that
tenant/entity/store. Add one `ScopedEvidenceAuthority` deep module with a single read-only
`project(evidence_ids, principal, entity_scope, store_ref, as_of)` interface. It verifies current
blob integrity first, then accepts either:

- direct immutable metadata with
  `evidence_scope_contract_id=kjds-evidence-scope-v1`; or
- a separate grade A immutable binding Evidence with
  `evidence_scope_contract_id=kjds-evidence-scope-binding-v1`, target Evidence ID/hash, exact
  tenant/entity/store, and an independent reviewer.

The binding Evidence may scope a legacy immutable record without editing it. The target hash must
still match, and binding creator/reviewer must be independent of the target creator. Missing scope
metadata remains `unbound/partial`; an unavailable entity grant remains `no_data`; conflicting
tenant/entity/store or target hash is `blocked`. Read-only research and constrained drafts may
continue, but candidate scoring and Pilot approval require `scope_binding_status=ready`.
Truth/Governance exposes the binding authority hash and never lets a binding widen the Principal
or ScopeGrant.

### Scoped governance projection

Approval, Permit, Readback and Compensation records must not enter a store snapshot merely because
an arbitrary nested JSON value happens to contain the requested `store_ref`. Add one
`GovernanceScopeAuthority` deep module with a single read-only
`project(principal, entity_scope, store_ref, as_of)` interface. It uses only explicit immutable
relations:

- Gate reviews are scoped by their complete Evidence set through `ScopedEvidenceAuthority`;
- governed execution plans are scoped by their complete frozen `evidence_ids`;
- commands inherit only from an exactly matching scoped `plan_id`; a receipt additionally requires
  its own Evidence set to be scoped and current;
- observation/readback windows inherit only from an exactly matching scoped plan and command; any
  window Evidence must independently pass the same scope authority.

A direct `store_ref` field, where an older projection exposes one, is a narrowing assertion and
must match; it is never discovered by recursive JSON search and cannot replace scoped Evidence.
Orphan parent IDs, cross-store assertions, invalid/unbound Evidence or unavailable authorities
remain excluded with machine-readable gaps/blockers. `TruthGovernanceService` consumes only the
scoped sets and exposes their authority hash. This projection does not grant, approve, issue a
Permit or perform Readback; it only prevents facts from one entity/store being counted in another.

## Options rejected

- Add `entity_ref` to API-key configuration: not an auditable effective-time fact.
- Treat tenant as entity: semantically false for multi-entity sellers.
- Store only the latest grant row: loses revocation history and deterministic replay.
- Accept self-report or C-grade browser data: insufficient authority for legal/financial scope.
- Search arbitrary nested JSON for `store_ref`: a value occurrence is not an authority relation and
  permits cross-context contamination.

## Migration and rollback

Migration `20260727_0056` adds only the append-only event table and indexes. Migration
`20260728_0069` adds partial unique source-reference indexes for
`scope_authority_source` and `scope_authority_review`; it does not add or infer Evidence or grants.
Existing principals therefore continue to receive `entity_scope=no_data`. Downgrade is for isolated
engineering verification only; a real environment remains forward-only and must not rewrite prior
migrations or erase Evidence.

## Acceptance

- missing grant stays `null/no_data`;
- valid owner source → accepted independent grade A review → independent recorder resolves exactly
  one entity at `as_of`;
- revoke is effective-time deterministic;
- self-grant, self-review, reviewer-as-recorder, uploader-authored review metadata, cross-store
  access, bad Evidence, ambiguous grants, and idempotency drift fail closed;
- anonymous API access is `401`, unauthorized store is `403`;
- Truth/Governance continues to report all external writes closed.
- legacy Evidence without a scope binding remains visible but cannot authorize scoring or Pilot;
- direct and attested bindings resolve only the exact current tenant/entity/store;
- cross-scope, wrong target hash, self-review, expired, missing or damaged binding Evidence fails
  closed while read-only research remains available.
- governance reviews/plans/commands/windows only project through scoped Evidence and exact immutable
  parent IDs; orphan or cross-store records do not affect Approval/Permit/Readback/Compensation.

Review trigger: organization/RBAC provider integration, multiple entities per store, delegated
administration, or database RLS rollout.
