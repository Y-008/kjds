# ADR-0080: Governed agent inference and one-SKU AI listing dry-run

- Status: Accepted for implementation
- Date: 2026-08-01
- Requirement: BR-134
- Owners: Architecture, Evidence, Product Content, Profit, Media, Listing, Runtime, Web

## Context

KJDS already owns deterministic Product/Passport, supplier offer, fifteen-item
cost, content/media, approval, execution-plan and dry-run authorities. Its
named Agents are responsibility projections, not a governed model-inference
runtime. Calling Ollama or a cloud model from pages, routers or individual
business modules would create several competing inference seams, make model
outputs look like formal facts, duplicate approval logic and weaken exact-scope
Evidence controls.

VIC·SERP is retained only as a journey and evaluation baseline. Its extension
code, cookies, local storage, internal protocols, private endpoints, wide host
permissions, static fee tables and unverified media are not imported.

## Decision

Create one deep module, `AgentInferenceService`, with the single business
interface `infer(AgentTaskSpec) -> AgentArtifact`. The service owns task
admission, exact scope, data minimization, immutable input hashes, prompt and
model provenance, Provider routing, schema validation, quality thresholds,
budget/timeout limits, response Evidence and append-only artifacts. Pages,
routers, prompts and domain modules may not call model Providers directly.

The versioned `agent_task_registry` admits only:

- `extract_1688_product_v1`;
- `map_ozon_taxonomy_v1`;
- `draft_ru_listing_v1`;
- `build_media_brief_v1`;
- `vision_consistency_qa_v1`;
- `listing_quality_qa_v1`.

Routing is local-first. An eligible task gets at most one Ollama attempt and,
only for Provider/timeout/schema/quality/capability failure, at most one
OpenAI-compatible attempt. Policy, Evidence, scope, classification and budget
failures are terminal and cannot be bypassed by changing Provider. A leased
attempt whose transport outcome is unknown is not replayed automatically.

Every successful model response is first captured as immutable Evidence and
then projected as an immutable `AgentArtifact`. Artifacts always state
`proposal_only=true`, `formal_fact=false` and
`external_write_allowed=false`. Human feedback creates a superseding artifact;
historical output is never overwritten.

Create one `AiListingPipeline` for one 1688 capture and one selected variant.
It orchestrates existing deep modules and stores only orchestration state and
internal references. It may create a ListingDraft only through the existing
scoped listing approval-plan path, may create an execution plan only from the
existing approved listing path, and may run only the existing deterministic
dry-run. It never calls the limited executor, signs a Permit, publishes to
Ozon, changes price/inventory, purchases or pays.

The browser contract advances to 1.1 while continuing to accept 1.0. It still
uses an explicit active-tab action and visible DOM/JSON-LD only. It adds the
selected variant and bounded public image references, but never reads cookies,
local storage, private network responses or platform credentials. Image
references remain unverified external references until the existing material
rights workflow approves independent originals.

PostgreSQL remains the only work queue and truth source. Runs, attempts,
artifacts and events use unique idempotency keys, leases, immutable hashes and
Transactional Outbox events. No Redis, Kafka, Temporal or second approval
system is introduced.

## Safety invariants

- public page price is C-grade observation, never actual purchase cost;
- the model cannot create Ozon category IDs, enumerations, dimensions,
  materials, prices, costs or hard facts;
- profit, price, logistics, commission, returns, FX and CM3 remain Decimal
  deterministic calculations;
- only task-approved minimal fields may leave the machine; cookies, credentials,
  customer data, bank files, full HTML and unrelated Evidence are forbidden;
- non-loopback model gateways require HTTPS and secret values never enter
  errors, events, artifacts or logs;
- missing Evidence, rights, reviews, approvals or positive downside CM3 yields
  `blocked`, never guessed completion;
- `dry_run_passed` is the terminal v1 success state and still has no external
  side effect.

## Consequences

The AI layer can improve extraction, taxonomy suggestions, Russian copy and
visual/text QA without becoming a competing facts or approval system. Runs are
auditable and recoverable, but real completion still depends on independent
human and official Evidence gates. Provider changes remain behind one port and
one registry.

## Acceptance

- Provider contract and fallback tests prove no more than two total calls;
- all hard-fact output has an allowed Evidence reference or is explicitly
  unknown;
- injected page instructions and credential-like data cannot enter model
  requests;
- stale/cross-scope/duplicate/cancelled runs fail closed;
- human edits create a new artifact and new hash;
- Listing creation, approval and dry-run use existing authorities;
- dry-run creates no execution command, Permit, Receipt or Ozon request;
- API/OpenAPI, PostgreSQL forward migration, desktop and 390px Web states,
  regression and delivery gates pass before the feature flag is enabled.
