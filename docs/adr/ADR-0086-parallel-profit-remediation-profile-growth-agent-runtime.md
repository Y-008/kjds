# ADR-0086: Parallel profit remediation, store intake, growth ports and governed Agent runtime

- Status: Accepted; engineering implementation complete
- Date: 2026-08-02
- Requirements: BR-136, BR-137
- Deliveries: BAS-163, BAS-164, BAS-165, BAS-166
- Owners: Profit Operations, Data Governance, Growth, AI Platform, Engineering

## Context

The retained market-recon bundle and Profit Command expose 18 real Ozon SKU,
but most retained records cannot yet participate in a profit decision. Sellers
need a ranked repair queue, an Evidence-backed way to propose store/category
roles, governed VK/Telegram attribution and a model runtime that is useful for
uncertain interpretation without becoming a money, fact or execution authority.

These concerns can be developed in parallel, but they must compose over the
existing Evidence, bundle, Profit Command, Scope Grant and execution controls.
They must not create a second truth store or weaken the same operating kernel
for beginner plans.

## Decision

1. Add `ProfitDataRemediationWorkspace` as a deterministic projection over
   every retained bundle item and Profit Command candidate. It preserves source
   conservation, groups blockers by SKU/source/error/evidence requirement and
   ranks work by severity, loss exposure, VaR and unblock impact without
   guessing missing values or aggregating currencies.
2. Authorize a remediation read using the caller's current exact tenant,
   entity and store grant while preserving the bundle's historical grant hash
   as data lineage. Grant rotation must not make same-scope historical Evidence
   unreadable; tenant, entity or store drift continues to fail closed.
3. Add `StoreProfileIntake` as a proposal-only deep module. It accepts graded,
   time-bounded observations, separates official category identity from derived
   operating roles and returns primary, secondary, tertiary or derivative
   assignments only when its review gates allow. It cannot publish, promote a
   fact, issue a Permit or write a marketplace.
4. The first runtime proposal is deliberately limited to the 36 retained
   listing/category observations derived from 18 real Product Info records.
   Order, profit, traffic and exact variant Evidence remain explicit gaps; no
   profile is persisted or automatically activated from this proposal.
5. Add one `GrowthChannelPort` contract for VK and Telegram. Dry-run and
   injected transports share stable attribution IDs, the full
   `impression -> click -> deep_link -> conversation -> add_to_cart -> order ->
   refund -> settlement -> cash_cm3` funnel, reward accrual/confirmation,
   duplicate attribution and fraud checks. Production writes require a valid
   one-time Permit; Telegram additionally requires user initiation or consent.
6. Optimize growth decisions for `incremental_cash_cm3`, including advertising,
   channel, reward and refund costs. The capability API does not claim that an
   official account, credential, event stream or production transport is
   configured.
7. Add `GovernedAgentRuntime` behind the existing `ModelInferencePort`. Route by
   declared capability, measured accuracy, latency, estimated cost and expected
   profit value; enforce cost budgets, fallback, idempotency, redaction,
   deterministic eval linkage and OpenTelemetry GenAI-style spans.
8. Agent results remain proposals. The runtime cannot promote formal facts,
   approve itself, issue Permits or perform marketplace writes. If no model
   adapter is configured, the public descriptor returns truthful `no_data`.
9. Add server-owned read endpoints and Profit Command Web surfaces. The browser
   displays the repair queue, store/category proposal and growth capabilities;
   it does not calculate profit, fabricate history or execute channel actions.
   The full repair queue is server-paginated while summary/group totals remain
   full-snapshot values, avoiding an unbounded dashboard DOM without deleting
   or hiding retained data.
10. No migration, broker, workflow engine, vector store or second ERP is added
    for this slice. PostgreSQL remains the authority for existing persisted
    facts and immutable snapshots; the new pure modules are composed at the
    runtime boundary.

## Public Interface

```text
GET /v1/profit-command/remediation
GET /v1/seller-os/store-profile-proposal
GET /v1/growth-channels/capabilities
GET /v1/agent-control/runtime
```

## Alternatives Rejected

- Delete or filter low-quality records before the dashboard: rejected because
  source conservation and future repair value would be lost.
- Require the current grant hash to equal every historical bundle hash:
  rejected because routine grant rotation would deny legitimate same-scope
  reads. Historical and access authorities are instead retained separately.
- Let a model assign official categories or calculate profit: rejected because
  official taxonomy, money and inventory require deterministic authorities.
- Send VK/Telegram messages directly from an Agent: rejected because consent,
  attribution, spend, Permit and readback controls must remain independent.
- Install new infrastructure before the first profit repair queue: rejected
  because it delays the shortest path to stop-loss and evidenced profitability.

## Acceptance

- `accepted + quarantined = source_total` remains true for all 374 records.
- A normal same-scope identity can read a historical bundle after grant
  rotation; cross-tenant/entity/store access still fails closed.
- The profile proposal contains only observed evidence classes and exposes all
  missing classes and variant ambiguity.
- VK/Telegram ports enforce consent, one-time Permit and incremental cash CM3
  semantics while production configuration remains explicit.
- Agent routing, budget, fallback, trace/eval and authority-negative tests pass.
- Profit Command renders the repair and routing views on desktop and 390px
  without client-side profit arithmetic or synthetic history.

## Review Triggers

Re-open this ADR before persisting growth attribution events, binding official
VK/Telegram production transports, activating an automatically proposed store
profile, allowing model-generated facts or categories, or granting an Agent any
approval, Permit or external-write authority.
