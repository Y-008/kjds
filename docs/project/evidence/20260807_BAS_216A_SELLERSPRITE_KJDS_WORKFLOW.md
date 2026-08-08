# BAS-216A SellerSprite MCP / KJDS-Owned Research Workflow Evidence

## Decision

KJDS does not place a marketplace-data vendor inside AgentRuntime and does not let an MCP tool own
Product, Fact, Finance, Approval, Permit, procurement, listing, outreach, or any other operating
truth. The accepted first slice is a vendor-neutral `MarketplaceResearchWorkflow.project()` deep
module. It consumes a frozen source receipt and returns deterministic, proposal-only market
observations with explicit blockers.

The alternatives considered were:

1. Directly expose SellerSprite tools to a model. Rejected because dynamic tools, prompt injection,
   unverified licensing, cost/rate limits, revocation, and exact-scope authority would sit outside
   KJDS governance.
2. Copy marketplace signals into Batch Opportunity or Research Inbox immediately. Deferred because
   BAS-210 owns the existing Evidence/API surface and a vendor-specific first slice would blur the
   source adapter, normalization, and business truth boundaries.
3. Freeze a provider-neutral receipt and synthetic/manual-export contract first. Selected because it
   is deterministic, reversible, reviewable, and leaves live credentials and network access outside
   the repository.

## Benchmark Inputs

- The user-provided Xiaohongshu note demonstrates the operator loop "Codex decomposes the question,
  SellerSprite MCP retrieves marketplace data, Codex analyzes it, and a human decides." It also
  surfaces real cost and accuracy concerns. This is a workflow benchmark, not authoritative product
  or financial Evidence: <http://xhslink.cn/o/5d91KHsjlBI>.
- SellerSprite's official MCP page listed 44 tools and 10 Amazon sites at review time:
  <https://open.sellersprite.com/mcp>.
- SellerSprite's official Codex setup page specifies `Streamable HTTP`, endpoint
  `https://mcp.sellersprite.com/mcp`, and custom header `secret-key`:
  <https://open.sellersprite.com/mcp/40>.

No SellerSprite secret was present in the current process environment. No key was copied into Git,
shell history, test output, Evidence, or the fixture. Live MCP installation and use therefore remain
`not_admitted`.

## Frozen Architecture

```text
SellerSprite manual export / later read-only MCP
        |
        v
MarketplaceResearchSourceReceipt
  - source identity + full registry/profile hashes
  - exact tenant/entity/store/current authority
  - canonical semantic role + tool version + schema hash
  - page/checkpoint/source-total/hash conservation
  - license/revocation/cost/rate status
        |
        v
MarketplaceResearchWorkflow.project()
  - fail-closed validation
  - stable site:ASIN identity
  - deterministic observation normalization
  - transparent heuristic dimensions
        |
        v
MarketplaceResearchProposal
  - Observation/proposal only
  - opaque citations and blockers
  - zero model/provider/MCP invocation
  - zero external or operating write
```

The source registry records only an adapter candidate and selected tool contracts. It is not a
second Product, Evidence, lead, or market-fact store. The fixture contains two synthetic ASIN-like
records and no copied SellerSprite output, customer data, contacts, credentials, or provider request
identifiers.

The deep module depends on two server-owned ports rather than trusting caller assertions:
`MarketplaceResearchScopeAuthority` projects the current exact scope at a trusted clock instant,
and `MarketplaceResearchReceiptAuthority` atomically claims `(scope binding, idempotency key)`
against the immutable receipt and registry hashes. The repository intentionally supplies no
production implementation of either port in this slice.

## Hard Gates

- `MarketplaceResearchScopeContext` binds tenant/entity/store/current authority and separates the
  data cutoff from current authority. `project()` obtains current time from its injected trusted
  clock, rejects caller time rewind, and validates the tuple through a read-only
  `MarketplaceResearchScopeAuthority` port before reading the receipt. After all deterministic
  receipt, record, and scoring checks, it reads the trusted clock again, rejects regression, and
  revalidates current authority at that fresh instant immediately before the durable claim. A revoke
  or rotation between the two reads is therefore visible. Missing/revoked authority, scope drift,
  unknown status text, clock failure, or authority error emits only a stable safe reason and creates
  no receipt claim.
- `MarketplaceResearchReceiptAuthority` is required even for the synthetic path. Exact replay is
  byte-equivalent; the same exact-scope idempotency key with changed receipt or registry hash is a
  conflict. Record coverage, duplicate record/tool rows, identity, freshness, page, and score
  validation all precede the claim, so malformed input cannot poison a durable key.
- The receipt's authority snapshot and `data_as_of` remain immutable content. Ephemeral server
  current-check instants are deliberately excluded from the successful proposal hash: a later
  process can replay the same receipt byte-for-byte while authority remains current, but a later
  revoke or rotation is blocked before the receipt authority is called.
- The receipt must match the exact scope and `data_as_of`; future or stale data is rejected.
- Every observation must fall in the registry-versioned synthetic freshness window ending at
  `data_as_of`; a newly sealed receipt cannot make old observations current.
- Source mode is limited to `synthetic_fixture` in this slice. `manual_export` is registered as a
  future intake mode but is not admitted until license and real-sample reconciliation exist. Live MCP
  is blocked.
- Provider tool IDs map to six canonical semantic roles. Core normalization and cross-field
  conservation depend on those roles, so a future provider can be added by a separately reviewed
  registry contract rather than a core-code fork.
- Registry/profile hash, tool ID, semantic role, version, schema hash, field set, site, ASIN identity,
  page ordering, advancing checkpoints, cumulative export count, terminal state, page hashes,
  observation IDs, counts, and the final receipt hash are immutable.
- Direct and indirect prompt-injection patterns, dynamic tool names, tool schema drift, extra fields,
  plaintext contacts, and secret-header text fail closed with zero observations and citations.
- Grade C fixture Evidence cannot call itself A or B. Seller presence is explicitly not buyer intent.
- Trademark uncertainty blocks a candidate. The heuristic score cannot be a profit estimate, formal
  rank, global Top1 claim, purchasing decision, or listing recommendation.

## Deterministic Fixture Result

- 6 selected read-only tool contracts
- 6 complete pages and terminal checkpoints
- each page freezes the asserted source total, cumulative exported count, and terminal exhaustion
- 12 content-addressed observations
- 2 stable `US:ASIN` synthetic records
- one `ready_for_review` proposal and one trademark-blocked proposal
- production admission: `not_admitted`
- external writes and operating objects created: `0`

The scoring dimensions are transparent heuristics for demand, growth, competition, traffic health,
review opportunity, and trend stability. They intentionally omit margin, landed cost, tax, actual
cash, and causal profit. Real commercial decisions therefore remain `UNKNOWN`.

The fixture's `source_total_observations` is a content-addressed synthetic receipt assertion. It
proves deterministic pagination conservation inside this test artifact, not that SellerSprite's
live account or UI contained exactly that number. Independent real-sample reconciliation remains a
later production Gate.

## Operator Workflow Benchmark And KJDS Improvement

The Xiaohongshu benchmark was re-opened on 2026-08-08 and inspected as the actual 3 minute 33 second
note, rather than inferred from its title. The visible post and author replies support three limited
observations: the author still uses the workflow, considers product research useful, and reports a
meaningful cost trade-off; a direct-AI alternative is described as possible but less accurate and
less efficient. The note does not expose a reproducible source receipt, exact prompt, complete tool
trace, cost ledger, or marketplace reconciliation. KJDS therefore adopts the useful orchestration
pattern while replacing the unverified result path with the following owned funnel.

```text
Ozon candidate family / explicit research question
        |
        v
Stage 0: exact scope + budget + stop policy
        |
        v
Stage 1: SellerSprite product and market screen (Amazon auxiliary signal)
        |
        v
Stage 2: trend, traffic, review and trademark corroboration
        |
        v
MarketplaceResearchSourceReceipt -> MarketplaceResearchWorkflow.project()
        |
        v
KJDS proposal-only candidate observation
        |
        +--> Ozon 28-day demand/competition/return evidence
        +--> 1688 exact offer/SKU/spec/tier comparison
        +--> written RFQ reply and landed-cost evidence
        +--> compliance, media and listing readiness
        |
        v
human decision; no automatic Product, purchase or listing write
```

### Reconstructed benchmark method

The visible video was sampled at the operating brief, initial-screen, pool-expansion, detailed-report,
installation, and pricing frames. The following is the reproducible method demonstrated by those
frames; it is more specific than the post title but remains a benchmark observation rather than a
provider or marketplace fact:

| Video step | Visible operator method | Useful pattern | Missing control that KJDS adds |
| --- | --- | --- | --- |
| 1. Freeze a daily brief | A persistent Codex automation targets Amazon US `Home & Kitchen`, runs each morning, defines inclusion/exclusion rules, requests at least 20 initial candidates and no more than 5 final recommendations, requires rejection reasons, avoids historical duplicates, and permits a no-result day. | Make the task repeatable and let “no qualifying product” be a valid result. | Exact data cutoff, tool/call budget, source receipt, authority, and UNKNOWN propagation. |
| 2. Build an initial table | The result table visibly includes product names/Chinese translation, image, representative ASIN, price, monthly sales and monthly revenue. | Compare candidates in one stable tabular view before writing narrative. | Field provenance, original units/currency, observation time, page coverage, and grade. |
| 3. Expand the product pool | The narration explicitly uses other products in the store and adjacent products to extend the pool. | A seed is a discovery starting point, not a recommendation. | Stable product-family/specification identity and duplicate-family suppression across markets. |
| 4. Produce a detailed packet | The report frames visibly separate trend judgement, keyword suggestions, Listing/PPC terms, product-positioning directions, final judgement, risks, and next evidence to collect. | Separate screening from the later decision memo. | Prevent keyword/positioning advice from being promoted to demand, profit, compliance, or listing truth. |
| 5. Connect Codex to SellerSprite MCP | The final section shows Codex client setup and SellerSprite MCP access. A pricing frame mentions a 4,000-point annual package, while comments describe the workflow as useful but expensive. | Let an agent orchestrate narrow research tools instead of manually copying every screen. | Inventory admission, exact entitlement/cost reconciliation, revocation, immutable tool hashes, and shared-system licensing. |
| 6. Repeat by task | The closing narration emphasizes that output depends on the task supplied to the system. | Reusable task templates improve operator speed. | Prompts are only views; they cannot change evidence, authority, budget, or write permissions. |

The video does **not** provide a complete prompt transcript, immutable tool trace, page-conservation
proof, current SellerSprite price contract, or reconciliation of its reported Amazon metrics. The
visible numeric marketplace values and the 4,000-point mention therefore must not be copied into a
KJDS candidate, cost ledger, or profitability model.

### KJDS-owned daily operating contract

KJDS reuses the existing `MarketplaceResearchWorkflow`; it does not add a separate “AI selection”
pipeline. One daily run is a bounded projection through the following contract:

1. **Freeze the question.** Bind `market`, `site`, product family, specification boundary,
   `data_as_of`, requested metrics, candidate ceiling, provider-call/point ceiling, permitted source
   mode, and stop policy. The run is invalid when any of those values is implicit.
2. **Seed broadly but cheaply.** Accept seeds from an authorized store export, explicit competitor
   ASINs, prior KJDS candidates, or operator-entered keywords. Seed origin remains visible and never
   becomes demand evidence. Run only the `product_research` and `market_research` roles first.
3. **Screen to a small queue.** Normalize the initial table, retain original scalars and citations,
   log a machine-readable rejection reason for every removed candidate, suppress exact historical
   duplicates, and allow a zero-candidate result. Do not invoke the four per-candidate tools for a
   rejected row.
4. **Corroborate survivors.** For at most the configured survivor ceiling, collect all four remaining
   roles: sales trend, traffic/keyword, reviews, and trademark. Missing or contradictory roles stop
   that candidate. Listing/PPC suggestions remain proposal text linked to their keyword receipts.
5. **Project once.** Seal the complete pages into `MarketplaceResearchSourceReceipt` and call the
   existing deterministic `MarketplaceResearchWorkflow.project()`. No model or provider may alter
   the normalized values after sealing.
6. **Bridge markets explicitly.** Treat SellerSprite Amazon observations as auxiliary discovery. A
   candidate reaches RU review only after an explicit product-family/specification mapping to Ozon;
   title or image similarity is insufficient.
7. **Close the commercial loop.** Reuse the existing Ozon 28-day evidence, 1688 exact offer/SKU/tier
   capture, frozen multi-supplier RFQ, landed-cost, compliance, media and Listing gates. The final
   human packet shows assumptions and UNKNOWNs; it does not auto-create Product, purchase, Listing,
   Approval, Permit or external outreach.

The minimum operator-visible packet is therefore:

```text
run scope + cutoff + budget + stop reason
seed and query lineage
initial candidates + every rejection reason
survivor six-role observations + original units
provider tool/page hashes + cost/point reconciliation
KJDS proposal score + blockers (not expected profit)
Ozon mapping and 28-day evidence state
1688 exact SKU/tier/RFQ state
landed-cost/compliance/media/listing UNKNOWNs
human decision and next cheapest evidence action
```

This design outperforms the benchmark on the dimensions that matter to KJDS: it spends expensive
provider calls only after a cheap screen, supports several providers without changing core truth,
distinguishes Amazon discovery from Ozon evidence, carries every source scalar to the reviewer, and
continues through supplier quotation and listing readiness instead of stopping at an AI-generated
recommendation.

### Stage contract

| Stage | Minimal provider role | KJDS output | Stop / reject condition |
| --- | --- | --- | --- |
| 0. Question | no provider call | one market, one product family, one time window, one metric set, one call budget | scope, license, cost approval or exact authority missing |
| 1. Screen | `product_research`, `market_research` | small ASIN shortlist plus immutable query/field/page receipt | no candidate clears transparent demand, growth and competition thresholds |
| 2. Corroborate | `asin_sales_trend`, `traffic_keyword`, `review`, `trademark_list` | six-role normalized observation set for each surviving ASIN | missing page, schema drift, stale observation, trademark uncertainty or contradictory identity |
| 3. Project | no live provider call | proposal-only KJDS candidate observation with blockers and citations | receipt/hash/authority/idempotency validation fails |
| 4. Ozon reconcile | Ozon read-only evidence only | RU-market 28-day comparison on the same stable product family | Amazon-only demand, title similarity, or seller presence is the only support |
| 5. Source | existing 1688 capture and RFQ flow | exact offer/SKU/spec/MOQ/tier matrix plus dated written quote evidence | SKU ambiguity, cross-row tier leakage, unknown reply, captcha, or no written formal quote |
| 6. Decide | no provider ownership | human review packet containing margin assumptions, compliance and media/listing blockers | landed cost, FX/date, fee, return risk or compliance remains unknown |

SellerSprite data is deliberately not normalized as Ozon truth. ASIN, Amazon site, source timestamp,
provider tool/version and original scalar values remain visible so a reviewer can distinguish an
Amazon corroboration signal from RU-market evidence. Title similarity alone cannot merge a
SellerSprite ASIN with an Ozon offer or a 1688 SKU; the mapping must bind stable identifiers and an
explicit product-family/specification comparison.

### Cost and context controls

- Start with the two cheapest information-gain calls: product screen and market screen. Do not run
  trend, traffic, review or trademark tools for rejected candidates.
- Request only the registry-selected scalar fields. `returnFields` is a provider optimization, not
  permission to omit fields required for conservation or reconciliation.
- Cache only immutable content-addressed receipts by exact query, site, time window, provider/tool
  version and page checkpoint. A cache hit never refreshes current authority or makes stale data
  current.
- Use a fixed per-run candidate ceiling and per-candidate tool budget. Any page failure, ambiguous
  identity, exhausted entitlement or schema change stops that candidate without substituting model
  guesses.
- Rank proposals only after all six semantic roles are present. The heuristic is an investigation
  order, not expected profit, purchase authority or listing approval.
- Preserve raw provider cost/visit metadata outside prompts when a future live contract exposes it;
  reconcile the run receipt against the account statement before increasing the budget.

### Operating prompts are views, not contracts

An operator may ask, for example, for low-concentration products with growing demand and review
pain points. Codex must translate that request into the frozen stage contract, show the exact scope
and estimated call budget before live execution, and return a proposal packet containing inputs,
tool/page receipts, normalized observations, blockers and unresolved unknowns. Changing prompt
wording cannot relax the selected tools, authority checks, evidence grade, call budget, stop rules
or zero-write envelope.

### Production entry sequence

The personal MCP product may be used by one operator only after its current terms and entitlement
are verified. SellerSprite's published key policy says internal-system integration or shared use
must use its API service instead of a personal MCP key. KJDS therefore keeps two distinct future
entry paths that converge on the same receipt contract:

1. single-operator pilot: read-only MCP inventory approval, one bounded real sample, UI/export
   reconciliation and revocation test;
2. KJDS production/shared workflow: separately contracted API adapter with the same source receipt,
   scope, cost, rate, lineage and rollback gates.

Neither path is active in the current environment. `credential_missing` is the expected preflight
result, and it proves only that no secret was configured and no network or tool call occurred.

## Frontier Review

Relevant frontier candidates were reviewed against the existing registry. Stable MCP core and
authorization work remain a pilot rather than an automatic provider admission. MCP Tasks are not
used. This slice adds no dependency, SDK, agent framework, model runtime, browser automation, or
protocol implementation. The source provider's live protocol, identity, license, revocation,
rate/cost limits, and real records remain unverified.

## Verification And Remaining Gate

Required engineering verification:

- focused workflow tests, including trusted-clock rewind, in-flight authority rotation, durable
  replay/conflict, invalid-input zero claim, duplicate record/tool, observation freshness, checkpoint
  progression, terminal exhaustion, and provider-contract substitution
- target Ruff and Python compilation
- secret scan
- `git diff --check`
- independent P0/P1 review of the exact five-file slice

Current owner-side current-byte result: `60 passed` for the focused workflow suite; target Ruff and
Python compilation also pass. These results are engineering evidence only. They do not become a
final Gate or production admission until secret/diff checks, exact-five hash freeze, and independent
P0/P1 review all bind the same bytes.

Before a live SellerSprite connection may be enabled, a separate Gate must provide:

1. an operator-owned key stored outside Git and injected only as the `secret-key` header;
2. independently verified account/license/export terms;
3. server identity and tool discovery receipt;
4. rate, cost, revocation, and error contracts;
5. read-only real sample reconciliation against the source UI/export;
6. current exact-scope authority and zero-write proof;
7. an explicit rollback that removes the MCP configuration without losing KJDS truth.

Until then, `live_adapter_configured=false`, `production_admission=not_admitted`, external write is
false, and no Product/Fact/FinanceEntry/Approval/Permit/procurement/listing/outreach is produced.
