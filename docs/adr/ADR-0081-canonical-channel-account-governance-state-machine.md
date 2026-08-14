# ADR-0081: Canonical channel-account governance state machine

- Status: Accepted; implementation in progress
- Date: 2026-08-01
- Requirement: BR-135
- Delivery: BAS-160
- Owners: Security, Scope Authority, Platform Integration, Evidence, Runtime, Agent Team

## Context

BAS-158 established deep canonical authorities for separation-of-duties Evidence,
authorization lifecycle events, Kill Switch, managed credential lease admission,
Permit, official Readback and Compensation.  The production interface is still
read-only, however.  Channel-account execution-plan source variants exist in the
database contract while `ExecutionPlanService` has no channel-account adapter or
approved-source creation interface.  Tests can assemble Plan, Command and Receipt
rows directly; authenticated API and Web callers cannot reach the same valid state.

The Ozon read and write workers also retain a legacy process-global credential
path.  A complete internal governance ledger therefore does not yet prove that a
production worker received the exact tenant/entity/store/account/capability lease
verified by the channel-account authority.

## Decision

Introduce one deep module with one command interface:

```python
ChannelAccountGovernanceStateMachine.advance(
    *, principal, entity_scope, store_ref, command, as_of
)
```

The module composes, and never duplicates, the existing canonical Evidence,
Approval, ExecutionPlan, authorization-event, Kill, Permit, Readback,
Compensation and managed-credential authorities.  Commands are versioned,
idempotent and server-scoped.  The first production-reachable transitions are:

1. submit a typed governance Evidence candidate;
2. independently review that candidate;
3. create an internal approved channel-account change or compensation plan from
   canonical reviewed Evidence and an independent canonical Approval;
4. project the resulting state and next safe action.

No command may directly insert canonical rows, accept client-generated hashes,
create or approve its own Approval, issue a Permit, read a secret, contact a
provider or perform an external mutation.  Router, Web, Agent Tool and worker must
all call this same module and may not reproduce transition logic.

The worker runtime seam is an exact-scope credential lease handle.  The worker
must receive a server-issued opaque handle and resolve it through the managed
credential resolver.  Admission requires tenant/entity/store/platform/account,
adapter/version, capability, authorization epoch, secret-reference fingerprint,
lease purpose and expiry to match the latest canonical authority plus a fresh
official/authorized provider readback verifier.  Environment credentials are a
legacy unverified deployment pattern only: production workers must not fall back
to them, and they may not produce `verified_native` or a write-ready identity.

## State and authority rules

- Scope derives from authenticated Principal plus canonical Scope Grant; request
  bodies cannot choose tenant or entity.
- Submitter, reviewer, approver, verifier and executor identities are distinct
  where the action policy requires separation of duties.
- Latest rejected, revoked, killed, stale, malformed, cross-scope, hash-drifted or
  ambiguous authority fails closed without falling back to an older success.
- `approved_channel_account_change` and
  `approved_channel_account_compensation` plans use dedicated registered adapters
  and action policies; generic Listing adapters cannot be substituted.
- Plan creation is an internal L2/L4 governance transition.  Provider execution
  remains `policy_only` until a separate external-write canary has Approval,
  one-time Permit, worker lease, fresh provider Readback, Kill Switch and
  Compensation.
- Agent artifacts may suggest commands and create internal work only.  They cannot
  submit as a human, review, approve, resolve credentials, issue Permit or execute.

## Interface and delivery

Authenticated endpoints expose the same command interface with explicit command
contracts, role checks, CSRF protection, exact-store authorization and immutable
idempotency.  Read-only projection remains
`GET /v1/channel-accounts/workspace`; mutation endpoints return only non-secret
receipts and canonical next-state references.  Web renders submit/review/plan
states, blocked/no_data/error/retry and never accepts or displays secret material.

The implementation proved that the existing canonical rows cannot atomically
represent a derived single-use worker credential grant without mutating the
Channel Account, Approval, Permit, Command or Pilot truth sources.  Forward-only
`0082` therefore adds a non-secret grant/redemption ledger with one conditional
consumption update; applied `0081` remains unchanged.

## Acceptance

- normal authenticated API happy path reaches canonical submit → independent
  review → approved internal plan without direct `Session.add()` in tests;
- 401, 403, CSRF, role, cross-tenant/store/entity and self-review/approval denial;
- immutable idempotent replay and conflicting replay rejection;
- no client hashes, credential bytes, Cookies, private Tokens or private ERP
  interfaces admitted;
- exact-scope resolver/lease preflight integrated into Ozon read/write workers;
- production workers fail closed before reading legacy environment credentials;
  that legacy deployment pattern remains `implemented_unverified` and cannot
  satisfy native-parity acceptance;
- PostgreSQL, OpenAPI, Web, runtime, Graph/Harness and immutable Evidence gates;
- provider contact and every external write remain false until the later governed
  write canary is separately accepted.
