# BAS-178 Social Intelligence Analysis Evidence (Analysis Slice)

## Scope and result

- Task: `BAS-178`
- Deep module: `GovernedSocialIntelligenceAnalysis` (`analyze` / `readback` /
  `zero_authority`)
- Result type: immutable, content-addressed `SocialAnalysisBundle`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none
- Real platform adapters, account bindings and platform writes: `not_admitted`

This slice fills ADR-0090 acceptance #4 (actor/content/comment/time analysis)
and the BAS-178 acceptance outputs. It derives seller segmentation, comment
intent, content structure, product demand, calendar and campaign drafts from
conserved observation records. Every output is derived-only, never mutates raw
records, and missing data is reported as an explicit gap instead of being
fabricated.

## Contract surface

- `analyze(records, platform) -> SocialAnalysisBundle` — validates platform and
  records, then derives six read-only output families deterministically.
- `readback(bundle, observed?)` — `PENDING` without an observed hash,
  `VERIFIED` on hash match, `INVALIDATED` on mismatch.
- `zero_authority()` — every conservation key is literal `false`.

## Derived outputs

- `seller_segments`: distinct actors grouped by `account_type` with verified /
  unverified counts and audience totals.
- `comment_intents`: conversation items clustered by `intent` with sentiment
  and seller-response-status distribution.
- `content_structures`: content format counts, hashtag/topic frequency and hook
  presence.
- `product_demands`: product reference frequency and topic-product
  co-occurrence.
- `calendar`: distinct publish dates, posts per date and average cadence.
- `campaign_drafts`: at most one `DRAFT` assembled from observed top signals
  (`derived_from_observed_top_signals_only=true`, `execution_allowed=false`).

## Admission model

- Platforms: `xiaohongshu`, `douyin`.
- Missing dimensions produce explicit gaps (`seller_segmentation_no_actor_data`,
  `comment_intent_no_conversation_data`, `content_structure_no_content_data`,
  `product_demand_no_product_mentions`, `calendar_no_published_at`,
  `campaign_draft_insufficient_data`) instead of fabricated values.
- Sensitive values (credential fields, tokens, cookies, private keys, `sk-`)
  are rejected before hashing.
- Unknown enums normalize to explicit `unknown` / `unclassified` /
  `unspecified` buckets rather than silent failure.

## Zero-authority conservation

Every outcome preserves literal `false` for: Fact, FinanceEntry, Approval,
Permit, Pilot, Outbox, canonical Graph write, dependency install, network and
external write.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_social_analysis.py --basetemp D:\KJDS\pytest-social-analysis
............... [100%]
15 passed in 0.14s

.\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/social_analysis.py tests/test_social_analysis.py
All checks passed!
```

Covered negative contracts include empty records, unknown platform, missing
dimension gaps, missing publish date, sensitive value rejection, campaign draft
non-executability, readback verify/invalidate, and zero-authority flags.

## Artifact hashes

- module `apps/control_plane/social_analysis.py` (git blob)
  `51394b4934adab94780585f68011af3286cca701`
- tests `tests/test_social_analysis.py` (git blob)
  `78d5593c74e16845b57f9e32ac21271c9b8a5829`

## UNKNOWN retained

- real platform account binding and authentication;
- real collection pagination, rate limits, CAPTCHA and account-health outcomes;
- production content transcription / OCR quality;
- production sentiment and intent classifier accuracy.

No production collection or external execution is implied by this contract slice.
