# BAS-178 Campaign Authority Evidence (Campaign Authority Slice)

## Scope and result

- Task: `BAS-178`
- Deep module: `GovernedCampaignAuthority` (`issue` / `status` / `authorize` /
  `readback` / `zero_authority`)
- Result types: immutable, content-addressed `CampaignGrant`, `GrantStatus`,
  `AuthorizationDecision`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none
- Real platform writes, credential mix and external mutation: `not_admitted`

This slice freezes the campaign-grant lifecycle for ADR-0090 platform
operations: issue, activate, expire, revoke and kill-switch. A grant binds an
account to a set of authorized actions inside an envelope, and the authority
evaluator decides, purely from frozen grant state and a caller-supplied clock,
whether an action is authorized.

## Contract surface

- `issue(grant) -> CampaignGrant` — validates grant fields, actions, budget,
  stop conditions, ISO timestamps and booleans, then freezes a content-addressed
  grant.
- `status(grant, now) -> GrantStatus` — deterministic lifecycle state
  (`ACTIVE` / `NOT_YET_ACTIVE` / `EXPIRED` / `REVOKED` / `KILL_SWITCHED`).
- `authorize(grant, action, now) -> AuthorizationDecision` — action-level
  authorization under the current lifecycle state.
- `readback(value, observed?)` — `PENDING` / `VERIFIED` / `INVALIDATED`.
- `zero_authority()` — every conservation key is literal `false`.

## Lifecycle state machine

- `REVOKED` when `revoked=true` (highest priority).
- `KILL_SWITCHED` when `kill_switched=true`.
- `EXPIRED` when `expiry <= now`.
- `NOT_YET_ACTIVE` when `not_before > now`.
- `ACTIVE` otherwise; only `ACTIVE` grants authorize actions.

## Admission model

- `authorized_actions` is a non-empty subset of the ADR-0090 action set
  (publish/update/delete/comment/reply/like/favorite/follow/unfollow/message/
  download); unknown actions are rejected.
- `expiry` must be strictly after `not_before`.
- An action not present in `authorized_actions` yields
  `action_not_authorized` with `authorized=false`.
- Sensitive values (credential fields, tokens, cookies, private keys, `sk-`)
  are rejected before hashing.
- ISO timestamps are normalized to timezone-aware UTC; naive timestamps are
  treated as UTC.

## Zero-authority conservation

Every outcome preserves literal `false` for: Fact, FinanceEntry, Approval,
Permit, Pilot, Outbox, canonical Graph write, dependency install, network and
external write.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_campaign_authority.py --basetemp D:\KJDS\pytest-campaign-authority
................ [100%]
16 passed in 0.24s

.\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/campaign_authority.py tests/test_campaign_authority.py
All checks passed!
```

Covered negative contracts include expiry-before-not-before, unknown action,
sensitive value rejection, empty authorized actions, action out of scope,
expired/revoked/kill-switched/not-yet-active authorization denial, readback
verify/invalidate, and zero-authority flags.

## Artifact hashes

- module `apps/control_plane/campaign_authority.py` (git blob)
  `5d7f39fb5dbcc9af97b9900fa2169934fe37762d`
- tests `tests/test_campaign_authority.py` (git blob)
  `6def93cbedd728040dadab7abd07e9e673d9dfa7`

## UNKNOWN retained

- real platform account binding and authentication;
- real campaign publish/readback/revoke/kill-switch semantics;
- production adapter latency, availability and operating cost.

No production collection or external execution is implied by this contract slice.
