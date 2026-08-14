# ADR-0078: Native exact-scope channel account authority

- Status: Accepted; read-only contract implemented
- Date: 2026-07-30
- Requirement: BR-132
- Delivery: BAS-158
- Owners: Security, Scope Authority, Platform Integration, Evidence, Agent Team

## Context

Must-have ERP parity still lacks one native authority for channel account and
store authorization. Existing Scope Grants authorize a KJDS actor to an
internal tenant/entity/store; they do not prove that an Ozon or other channel
account, subaccount, role, credential or Adapter is officially authorized,
current, least-privilege and revocable. Store Matrix labels and successful API
responses cannot fill that gap.

Copying a third-party Cookie, internal Token, device session or private
endpoint would bypass the Evidence, revocation and audit boundary and remains
prohibited.

## Decision

Freeze one deep composition seam,
`ScopedChannelAccountAuthorityWorkspace.project(...)`. It will admit exact
tenant/entity/store/platform/channel-account/as-of scope before any credential
or source read, then combine existing Scope Grant and Store Matrix authority
with versioned official/public or expressly authorized read-only Adapter
authorization Evidence.

The projection may expose only non-secret credential fingerprints, Adapter
identity/version, role/subaccount and least-privilege capability, rotation and
revocation state, connection health, Owner/SLA/next, server counts/filter,
opaque cursor, stable snapshot and versioned Agent artifact. Plaintext secrets,
Cookies, internal Tokens, session material and CAPTCHA/access-control bypass
must never be stored in Evidence metadata or returned by API/Web.

Missing entity or store performs zero credential and upstream reads. Latest
revocation, cross-scope actor/role, Adapter/account binding, hash/as-of,
rotation or readiness drift fails closed without fallback.

## Safety

The Agent may suggest an authorization repair packet and internal task only.
It cannot create or modify a platform authorization, role, subaccount or
credential; log in to a third party; approve itself; issue a Permit; contact a
provider; or write externally.

No migration is authorized by this freeze. A new forward-only schema is
allowed only if a persistent, non-secret authorization authority is proven
necessary. Existing Scope Grant and warehouse authorities remain immutable.

## Acceptance

- exact scope and zero-read early gates;
- explicit separation of internal Scope Grant from external channel authority;
- official/authorized Adapter Evidence, fingerprint, rotation and revocation;
- no secret, Cookie, internal Token or private endpoint admission;
- server-owned pagination/snapshot/artifact and adversarial Agent closure;
- API/OpenAPI/Web/runtime/PostgreSQL/Evidence/Graph before
  `DONE_ENGINEERING`;
- production without authorized account binding remains honest
  `no_data/blocked`, never `verified_native`.
