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
