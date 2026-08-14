# BAS-178 Workspace Grant Lifecycle Integration Evidence

## Scope and result

- Task: `BAS-178`
- Change: wire the deep `GovernedCampaignAuthority` into
  `GovernedSocialCommerceIntelligenceWorkspace.operate`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none
- Real platform adapters, account bindings and platform writes: `not_admitted`

This slice closes the campaign-grant lifecycle gap in the workspace: `operate`
now enforces grant expiration, revocation and kill-switch via the deep
authority module when a caller-supplied clock is provided, while remaining
backward compatible with the existing three-field grant.

## Change surface

- `operate(spec, grant, idempotency_key, now=None)` is backward compatible:
  without `now`, behavior is unchanged.
- With `now`, the grant lifecycle is evaluated through
  `GovernedCampaignAuthority`: an expired, revoked or kill-switched grant is
  rejected with a stable `grant_expired` / `grant_revoked` /
  `grant_kill_switched` error instead of producing a receipt.
- The rich grant is assembled from the campaign spec (actions, purpose,
  audience, budget, stop conditions, expiry) plus the grant's optional
  `revoked` / `kill_switched` flags; `not_before` defaults to the Unix epoch.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_social_commerce.py --basetemp D:\KJDS\pytest-sc-op
........................ [100%]
24 passed in 0.07s

.\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/social_commerce.py tests/test_social_commerce.py
All checks passed!
```

Full social lane regression: `123 passed`.

## Artifact hashes

- module `apps/control_plane/social_commerce.py` (git blob)
  `3b56600e73450aa736a22f67a9f5cd74ec7f0748`
- tests `tests/test_social_commerce.py` (git blob)
  `27c24502c8a402021d0193988a080db19013bd1e`

No production collection or external execution is implied by this integration.
