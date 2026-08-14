# ADR-0090: Governed Social-Commerce Intelligence and Platform Operations

- Status: Accepted
- Date: 2026-08-03
- Owners: Business, Growth, Market Intelligence, Agent Platform and Risk
- Decision authority: Business owner
- Related: BR-007, BR-054, BR-085, BR-093, BR-138, BAS-117, BAS-138, BAS-178

## Context

KJDS needs current seller, creator, content, comment, product and operating
signals from Xiaohongshu, Douyin and later platforms. A narrow product-price
capture does not model videos, notes, transcripts, comments, actors, content
patterns or campaign outcomes. Conversely, installing a broad crawler or MCP
directly would create a second source of truth and mix credentials, collection,
analysis and platform mutations in one shallow interface.

The business owner explicitly requires full multidimensional collection and
retention of publish, comment, like, message, download and account-operation
capabilities. KJDS therefore does not impose an arbitrary sampling limit or a
blanket read-only product policy. It keeps only source, account-health,
credential, tenant-isolation and truth-quality controls.

## Decision

### One deep module

The future external seam is one `SocialCommerceIntelligenceWorkspace`:

```text
collect(AcquisitionSpec, Checkpoint?) -> ObservationBatch
analyze(AnalysisSpec, ObservationSnapshot) -> InsightBundle
operate(CampaignSpec, CampaignGrant) -> CampaignReceipt
```

Callers provide a platform, store/account reference, research objective,
time range and campaign intent. They do not provide raw cookies, private
selectors, signatures or provider-specific request bodies. Adapters hide
official API, export, CLI, browser and future provider details.

`ObservationBatch` conserves every returned record and page, exposes source
coverage and gaps, and carries source URL/ID, observed/published time, adapter
version, acquisition basis, raw Evidence/hash, normalized hash, checkpoint and
structured failure. `InsightBundle` is derived and never overwrites raw data.
`CampaignReceipt` records commands and provider readback without becoming the
platform or business truth owner.

### Full collection contract

Full means all fields, pages and time windows made available by the selected
and operating-account-approved source, with no additional KJDS sample cap.
Collection uses cursor/checkpoint continuation, content-addressed deduplication,
bounded retries and resume after interruption. Source denial, CAPTCHA or account
health warnings are returned as explicit gaps; data already collected remains
available and the resolver tries the next admitted route rather than abandoning
the objective.

The source ladder is:

1. official authorized API;
2. official operator export;
3. operator-selected CLI or dedicated visible browser profile;
4. public official or indexed page;
5. manual Evidence.

When one route fails, the resolver searches official documentation, upstream
source, Releases, Issues, forks and alternative adapters; reproduces the failure
in isolation; then records a versioned adapter or SkillCandidate. It may change
route but may not invent missing data.

### Multidimensional model

The raw and normalized model covers:

- actor/account: platform actor ID, public/authorized profile fields,
  verification, account type, public audience totals and account binding;
- content: note/video/live ID, title/body, hashtags, topics, media references,
  transcript/OCR, format, duration, publish time and product mentions;
- engagement: views, likes, favorites, comments, replies, shares, watch or
  completion metrics when the authorized source supplies them;
- conversation: text, thread, question, intent, pain point, objection,
  sentiment, request, spam signal and seller response status;
- seller/product: shop, product/SKU reference when exact, offer, content-product
  relationship, campaign and visible commercial call to action;
- time: captured-at and effective-at snapshots, deltas, velocity, cadence,
  seasonality and source freshness;
- outcome: campaign, lead, diagnostic, Pilot and cash outcome references only
  when their canonical owners and Evidence exist.

Analysis produces cohorts and patterns, not immutable labels about people.
It supports topic and demand discovery, content-hook and structure analysis,
seller cadence, comment-intent clustering, creator/product fit, funnel analysis,
trend/change detection and controlled experiment comparison. Engagement is not
silently converted into sales, and inferred identity, sensitive traits or exact
profit remain unknown unless an authorized source supplies them.

### Platform operations

Publish, update, delete, comment, reply, like, favorite, follow, unfollow,
message, download and supported account operations remain capabilities. They
are grouped into a `CampaignSpec` containing account, purpose, audience,
content/template versions, action set, schedule, volume/cost budget, stop
conditions and expiry. One human campaign grant can authorize repeated actions
inside that envelope; per-item approval is not required unless the campaign
changes or the platform requests human verification.

Every action uses idempotency, target verification, before-state where
available, provider receipt/readback, failure classification and a kill switch.
Credentials never enter prompts, Git, Evidence bodies or Agent output. A
CAPTCHA is handed to the operator rather than bypassed. These are hard account
and truth controls, not arbitrary limits on collection or analysis.

### Selected open-source path

`jackwener/xiaohongshu-cli` 0.6.4 at commit
`4d63f3c0c85ccd9054fa8e96d7f761aaf2507449` is the operator-selected first
Xiaohongshu runtime. It is installed only in an ignored project-local runtime,
uses its upstream lock file, and defaults to a dedicated QR profile. An operator
may explicitly select a browser source, but implicit all-browser scanning is not
used by the KJDS wrapper and the resulting session is stored in the ignored
project profile. All read and supported
write commands are available through the future campaign capability manifest.
The repository declares Apache-2.0 in `pyproject.toml` but has no root LICENSE
file at the reviewed commit; commercial redistribution therefore remains a
license clarification item and the runtime is not vendored into KJDS.

OpenCLI supplies the preferred adapter/failure-memory design; `last30days-skill`
and `xhs-research` supply query-expansion, deduplication and scoring patterns.
MediaCrawler remains excluded from commercial runtime because its license is
explicitly non-commercial. Other candidates follow the machine registry.

## Consequences

- Xiaohongshu and Douyin operate as separate workstreams sharing one collection,
  Evidence, analysis and campaign module.
- Existing `BrowserCaptureInbox` remains the product-price capture seam; it is
  not expanded into a generic content model.
- Raw source data and derived insight stay separate, enabling re-analysis when
  models or business questions change.
- KJDS can collect deeply and act at campaign speed without granting an Agent
  credentials or an unbounded cross-account mutation surface.
- This ADR authorizes architecture, installation evaluation and preparation;
  it does not claim a real account is authenticated or that any platform action
  has succeeded.

## Acceptance

1. The source-adoption registry covers official routes and reviewed GitHub
   candidates with version, license, decision, entry and exit gates.
2. The active workstream registry contains independent shared, Xiaohongshu and
   Douyin lanes with one task per lane.
3. The selected CLI is pinned, isolated, upstream-tested and reports its exact
   unauthenticated state without reading personal browser cookies.
4. A later engineering slice proves full pagination conservation, resume,
   deduplication, actor/content/comment/time analysis and campaign readback.
5. Cross-account credentials or raw customer data never mix, and missing data
   is not fabricated to keep a campaign or report moving.
