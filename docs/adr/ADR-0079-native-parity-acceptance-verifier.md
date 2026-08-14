# ADR-0079: Capability-granular native parity acceptance verifier

- Status: Accepted for implementation
- Date: 2026-08-01
- Requirement: BR-133
- Delivery: BAS-159
- Owners: Architecture, Runtime Verification, Evidence, Commerce OS, Web

## Context

`CommerceOperatingSystem` still projects parts of `_capabilities` and
`_native_modules` from hard-coded `implementation_status="implemented"` and
shared stage completion. A menu, a benchmark mapping or one shared stage
Evidence can therefore upgrade an entire capability family even when a
provider-specific code path, permission boundary, runtime replay or external
verifier is absent.

That is incompatible with KJDS's rule that mapping is not implementation and
engineering completion is not native business verification.

## Decision

Freeze one acceptance seam,
`NativeParityAcceptanceWorkspace.project(...)`, backed by a
verifier-owned capability ledger. Each provider/capability/version/exact-scope
projection must independently bind:

- code artifact and content hash;
- required migration and current/head/replay result;
- API/OpenAPI contract;
- executable Web state and responsive browser evidence;
- permission and write-path policy;
- authenticated runtime replay;
- immutable Evidence;
- fresh external Graph verifier observation.

The server owns capability counts, filters, opaque pagination, stable snapshot,
acceptance artifact and state. The client and `CommerceOperatingSystem` may
consume this projection but cannot recalculate or promote acceptance.

States are capability-granular:

- `mapped`;
- `implemented_unverified`;
- `gated`;
- `verified_native`;
- `blocked`;
- `stale`.

Missing or stale dimensions fail closed. Shared stage Evidence may be a
dependency but cannot upgrade sibling capabilities. The eight
provider-specific C-grade benchmark families remain gated until each exact
capability has its own complete verifier bundle.

## Safety

This acceptance workspace is read-only. It does not create business Facts,
Approval, Permit, credentials, listings, orders, inventory, payments or
external writes. Neither an Agent nor a module may certify itself; only a
registered external verifier may append an acceptance observation.

No migration is authorized by this freeze. A forward-only schema change is
allowed only if an append-only capability acceptance authority cannot be
expressed by the existing Harness/Graph ledger.

## Acceptance

- remove hard-coded implementation/native verification promotion from
  Commerce OS;
- bind all eight acceptance dimensions per provider/capability/version/scope;
- demonstrate missing, stale, bad-latest, cross-scope and shared-stage-family
  drift fail closed;
- keep mapping distinct from implementation and engineering distinct from
  verified native;
- deliver API/OpenAPI, executable Web states, runtime replay, browser Evidence,
  Harness/Graph materialization and full gates before `DONE_ENGINEERING`.
