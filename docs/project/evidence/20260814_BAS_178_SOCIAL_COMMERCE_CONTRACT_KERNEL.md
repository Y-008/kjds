# BAS-178 Social-Commerce Intelligence Contract Kernel Evidence (First Slice)

## Scope and result

- Task: `BAS-178`
- Deep module: `GovernedSocialCommerceIntelligenceWorkspace` (`collect`/`analyze`/`operate`)
- Result types: immutable, content-addressed `ObservationBatch`, `InsightBundle`, `CampaignReceipt`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none
- Real platform adapters, account bindings and platform writes: `not_admitted`

This slice freezes the ADR-0090 `SocialCommerceIntelligenceWorkspace` contract.
It validates acquisition, analysis and campaign envelopes and conserves records
deterministically without external collection or mutation. It does not create a
second source of truth, does not mix credentials, and never fabricates missing
data to keep a report or campaign moving.

## Contract surface

- `collect(AcquisitionSpec, Checkpoint?) -> ObservationBatch` — full conservation
  (no sampling cap), content-addressed deduplication, checkpoint continuation,
  explicit gaps for unadmitted adapters.
- `analyze(AnalysisSpec, ObservationSnapshot) -> InsightBundle` — derived-only
  patterns, never overwrites raw records.
- `operate(CampaignSpec, CampaignGrant) -> CampaignReceipt` — one human grant
  authorizes repeated actions inside an envelope; per-item approval not required;
  idempotency, readback and kill-switch are enforced; zero external writes.

## Admission model

- Platforms: `xiaohongshu`, `douyin`.
- Source rank ladder: official API > operator export > operator CLI/browser >
  public page > manual Evidence.
- Actions: publish/update/delete/comment/reply/like/favorite/follow/unfollow/
  message/download.
- Dimensions: actor/content/engagement/conversation/seller_product/time/outcome.
- Campaign grant binds `account_ref` to the campaign spec; mismatch is blocked.
- Sensitive values (credential fields, tokens, cookies, private keys) are rejected
  before hashing.
- Real platform execution is `not_admitted`: `collect` without an admitted
  adapter returns a truthful `NOT_ADMITTED` batch with `platform_adapter_not_admitted`
  gap; `operate` always returns `NOT_ADMITTED` with `external_write_allowed=false`.

## Zero-authority conservation

Every outcome preserves literal `false` for: Fact, FinanceEntry, Approval,
Permit, Pilot, Outbox, canonical Graph write, dependency install, network and
external write.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_social_commerce.py --basetemp D:\KJDS\pytest-bas178
................... [100%]
19 passed in 0.14s

.\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/social_commerce.py tests/test_social_commerce.py
All checks passed!
```

Covered negative contracts include unadmitted-adapter truthfulness, full
conservation with no sampling cap, content-addressed deduplication, deterministic
checkpoint/batch identity, platform/source-rank/dimension/action allowlists,
sensitive-value rejection, grant-account mismatch, missing stop conditions,
readback verify/invalidate, and zero-authority flags.

## Artifact hashes

- module: `apps/control_plane/social_commerce.py`
- contract: `docs/project/registries/social_commerce_contracts.json`
- tests: `tests/test_social_commerce.py`

## UNKNOWN retained

- real platform account binding and authentication;
- real collection pagination, rate limits, CAPTCHA and account-health outcomes;
- real campaign publish/readback/revoke/kill-switch semantics;
- production adapter latency, availability and operating cost.

No production collection or external execution is implied by this contract slice.
