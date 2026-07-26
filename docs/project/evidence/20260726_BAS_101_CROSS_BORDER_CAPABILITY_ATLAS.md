# BAS-101 Cross-border Capability Atlas Evidence

- Date: 2026-07-26
- Release: 0.55.0
- Branch: `feature/cross-border-capability-atlas-055`
- Requirement: BR-076
- ADR: [ADR-0027](../../adr/ADR-0027-cross-border-capability-atlas.md)
- Status: point-line-surface implementation, full quality gates, Docker runtime, and motion proof passed; clean IAB desktop/mobile proof capture and user-approved MP4 render pending

## Delivered outcome

KJDS now exposes one server-owned, read-only capability atlas that turns the public
LinkFox workflow audit into a Russia-first product and engineering contract. It does
not treat LinkFox marketing copy as platform, API, model-quality, or operating-result
evidence.

The stable navigation atlas contains 10 domains and 49 macro capability leaves. A
companion operating graph in the same server-owned registry deepens those leaves into
143 atomic points, 14 end-to-end value streams, and 8 operating control surfaces:

| Domain | Leaves | Product boundary |
| --- | ---: | --- |
| 灵感、商品与资产中枢 | 6 | Source-aware research, canonical product/link records, brand/compliance, licensed team assets |
| AI 服装视觉 | 6 | Apparel suites with product-fidelity, identity/rights, and Russia-market QA gates |
| AI 商品视觉 | 6 | Product suites tied to Canonical Product, platform ratios, claims, and evidence |
| AI 修图与质量提升 | 6 | Reproducible image transforms, masks, quality checks, and output provenance |
| AI 视频、POD 与设计 | 5 | Approved-script/media pipelines with likeness, license, and claim controls |
| 批量生产与企业治理 | 3 | Recoverable batch isolation, quotas/costs, roles, and independent approval |
| Agent、Skills 与 24×7 协作 | 5 | Objective-to-plan contracts, durable tasks, explicit tools, memory and write gates |
| 选品、市场与 Listing | 3 | Evidence-backed research, Russian localization, Canonical Listing, monitored signals |
| 供应链、利润与增长闭环 | 5 | Supplier, logistics, CM3, reconciliation, exception, and controlled-growth workflows |
| Evidence、受控执行与全球扩展 | 4 | Evidence/lineage, permit/readback/rollback, eval/routing, market/platform adapters |

Leaf states are truthful and server-owned: 18 `implemented`, 18 `ready`, 13 `gated`,
and 0 promoted from marketing claims. Every leaf records:

- the public LinkFox reference and KJDS surpass design;
- Russia/Ozon behavior and global expansion behavior;
- technology implementation, input contract, output contract, supported markets and
  platforms;
- current status, controls, and the KJDS workspace boundary.

The three operating layers close the gap between a feature catalog and an operating
system:

| Layer | Count | Required contract |
| --- | ---: | --- |
| Point | 143 | Parent capability, business object, operation kind, contract profile, source/evidence tier, input/output, technology, Evidence gate, failure modes and queue, readback, KPI, SLA, owner/reviewer, market/platform, controls, value-stream membership and workspace |
| Line | 14 | Ordered stages, supporting points, object transitions, entry/exit gates, events, exceptions, human takeover, KPI, SLA and adapter boundary |
| Surface | 8 | Related lines and focus points, dimensions, management decisions, truth owner, KPI, alerts and read-only/write boundary |

The 14 lines are: trend-to-opportunity, opportunity-to-supplier,
supplier-to-unit-economics, product-to-passport, passport-to-content,
content-to-listing, listing-to-publish, publish-to-growth,
demand-to-replenishment, order-to-delivery, delivery-to-return-support,
settlement-to-reconciliation, signal-to-experiment, and
exception-to-human-control. The 8 surfaces cover store operations, product truth,
content factory, controlled execution, supply/profit, customer/after-sales,
Agent/Skill governance, and global expansion.

The machine-readable source of truth is
`docs/project/registries/cross_border_capability_atlas.json`. Its companion competitive
registry keeps LinkFox at evidence tier C and explicitly states that Ozon support is
not verified.

## Technical implementation

- `CrossBorderCapabilityAtlas` validates the committed registry, rejects an invalid
  source tier, status, domain, incomplete leaf, duplicate identifier, dangling
  point/line/surface reference, or promoted LinkFox observation, computes a canonical
  SHA-256, and returns defensive copies.
- `scripts/build_cross_border_operating_graph.py` deterministically builds the graph
  and provides `--check` drift detection. The current build is exactly 143/14/8.
- Authenticated `GET /v1/capability-atlas/snapshot` is read-only. No capability-atlas
  mutation endpoint exists.
- The control envelope fixes `read_only=true`,
  `marketing_claims_are_business_facts=false`,
  `linkfox_ozon_integration_verified=false`,
  `client_can_promote_status=false`, `external_write_allowed=false`, and
  `operating_graph_is_execution_authority=false`.
- `/capability-atlas` defaults to a Point view and switches to Line, Surface, or the
  stable 49-capability trunk. Search and Russia/global/status filters apply across
  layers. Point details expose contract/Evidence/failure/readback/responsibility/KPI;
  Line details expose gates/transitions/events/exceptions/takeover; Surface details
  expose dimensions/truth/decisions/alerts/write boundaries.
- The implementation uses provider-neutral multimodal adapters, JSON Schema structured
  outputs, evidence-grounded retrieval, champion/challenger shadow evaluation,
  human approval separated from execution permits, immutable lineage/replay, and
  market/platform adapters around one governed kernel.
- No vector database, local model runtime, Redis, Kafka, Kubernetes, Temporal, or other
  new distributed dependency was introduced without an observed need and accepted ADR.

## Public LinkFox audit boundary

The in-app browser audit covered the public home/navigation surface, apparel and
product suites, designer, video, repair, batch, link management, Skills, Agent, Claw,
and pricing pages. The public price matrix additionally exposed separate entries for
free/model-labelled conversations, templates, sensitive-word detection, page context,
operating templates, product and apparel transformations, designer/team templates,
video, POD, 15 image-repair operations, batch conversation/image production, account
scope, compute/concurrency/storage/history and a team API example. The observed
public workflows include product/link/assets,
apparel/product image generation, image editing, video, POD/design, batch production,
research/listing skills, Agent orchestration, scheduled tasks, team workspaces, and
usage-based compute plans.

These observations are product-workflow references only. A public team API example
does not prove entitlement, endpoint correctness, service-level quality or permitted
integration. They do not verify LinkFox
Ozon access, provider APIs, model identifiers, generated-media quality, data licensing,
financial or sales outcomes, or production write authority.

## Runtime and test evidence

Verified after the point-line-surface extension on 2026-07-26:

- Docker PostgreSQL, API, and Web: healthy.
- `GET /health/ready`: `status=ok`, version `0.55.0`, database `ok`.
- PostgreSQL `pg_isready`: accepting connections.
- Alembic: one head, `20260726_0050`; database current at the same head.
- Secret scan: 545 non-ignored worktree files and 525 historical paths passed.
- Ruff: passed.
- Python: 503 passed; one upstream Starlette/httpx deprecation warning.
- Web: 40 passed.
- Next.js production build: passed; `/capability-atlas` emitted.
- `git diff --check`: passed.
- Targeted atlas and authenticated API contracts: 29 passed.
- Runtime snapshot from the rebuilt API image: 49 macro capabilities, 143 atomic
  points, 14 value streams, 8 operating surfaces; 73 C-tier public observations,
  50 repository-verified contracts, 20 product-architecture points and 0 public
  observations promoted to implemented. UTF-8 JSON payload is about 312 KB.
- Browser interaction before the deep extension loaded 10 domains/49 leaves,
  `CM3` search returned the expected capabilities, and the Russia filter retained
  all Russia-scoped macro leaves. A clean IAB point/line/surface desktop/mobile
  capture is still required; no terminal browser substitute is used as fidelity
  evidence.
- HyperFrames 0.7.72 default full check: runtime 0 errors/0 warnings, layout
  0 issues across 9 samples, motion 0 errors/0 warnings, and 203/203 text
  contrast checks passed WCAG AA. Lint retains one reviewed maintainability
  warning for the single continuous tree composition.
- OpenCLI doctor via `@jackwener/opencli` 1.8.6: daemon healthy; optional
  Chrome/Chromium extension not connected, so COOKIE/INTERCEPT/UI bridge use remains
  unavailable and was not used as evidence.
- Skill installer curated listing succeeded through the authenticated GitHub token;
  it was an audit only and no extra skill was installed.

Targeted post-extension evidence:

- Deterministic registry build `--check`: current.
- Atlas and authenticated API contract tests: 29 passed.
- Targeted Ruff: passed.
- Web tests: 40 passed.
- Next.js production build: passed.
- Docker API/Web images rebuilt; PostgreSQL, API and Web returned healthy.
- `/health/ready`: version `0.55.0`, database `ok`.
- HyperFrames default full check: lint 0 errors/1 reviewed size warning; runtime
  0 errors/0 warnings; layout 0 issues across 9 samples; motion 0 errors/0
  warnings; 203/203 text checks pass WCAG AA. A second check at the six proof
  times also passed.

## Visual evidence

Ignored release artifacts are kept under `output/release-0.55.0/`:

- `capability-atlas-desktop-viewport.jpg` — desktop fixed-viewport proof, visually
  inspected.
- `capability-atlas-desktop.png` — raw in-app-browser full-page capture; the browser's
  long-page compositor repeats tiles and this file is not used as a fidelity claim.
- `capability-atlas-mobile.png` — raw mobile full-page capture; the same compositor
  distortion was observed and a clean fixed-viewport replacement is required before
  BAS-101 is marked done.
- `motion-capability-tree-proof/contact-sheet.jpg` and six proof frames at
  0.4s, 1.25s, 3.7s, 5.45s, 6.45s, and 8.05s — visually inspected; the
  deterministic build-up preserves the 3-branch, 10-domain, 49-leaf hierarchy and
  finishes with a readable 29/11/9 proof.
- `motion-point-line-surface-proof/contact-sheet.jpg` and six proof frames at the
  same timestamps — visually inspected; the deterministic build renders 143
  connected atomic micro-nodes grouped 14/9/9/14/19/11/8/25/15/19, branch totals
  65/44/34, and a final 143 points / 14 lines / 8 surfaces lockup.
- Formal MP4 rendering remains intentionally user-gated by the motion workflow.

Git tracks only source, tests, contracts, ADRs, and project documentation. Release
screenshots and rendered media remain ignored artifacts.
