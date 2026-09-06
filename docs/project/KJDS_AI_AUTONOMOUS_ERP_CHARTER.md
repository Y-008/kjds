# KJDS AI Autonomous ERP Charter

| Field | Value |
|---|---|
| `doc_id` | `KJDS-AI-AUTONOMOUS-ERP-CHARTER-001` |
| `status` | `PROPOSED_FOR_IMPLEMENTATION` |
| `owner` | KJDS product and platform owners |
| `source_of_truth` | `MASTER_SPEC.md` and linked ADRs; runtime truth remains code, migrations, tests and Evidence |
| `scope` | private Ozon-first commerce control plane; one entity, one store and three real candidate SKUs for the first evidence slice |
| `approval_required` | policy activation and each high-risk action keep the existing Approval/Permit rules |
| `external_write_allowed` | `false` by default |

## 1. Outcome

KJDS is a deterministic commerce kernel, evidence layer and governed Agent layer. Its target is unattended operation of routine work inside a pre-authorized policy envelope: data collection, reconciliation, analysis, forecasting, task orchestration, bounded recovery and result reporting. Unattended does not mean that an Agent can grant itself access, change a budget, approve its own decision, or convert a forecast into a Fact.

The canonical loop is:

```text
OBSERVE → VALIDATE → DECIDE → POLICY_CHECK → APPROVAL/PERMIT
→ EXECUTE → READBACK → SETTLE → EVALUATE → REPLAN
```

The platform continues independent work when one exact scope is quarantined. A shared authority, evidence-integrity, financial-integrity or security failure stops the affected domain or the whole run as defined by the registered recovery policy.

## 2. Authority and truth

The only authority order is:

1. First-party marketplace, settlement, bank, supplier, logistics, sample and compliance evidence.
2. Immutable KJDS Facts and ledgers derived from that evidence.
3. Versioned projections and metrics.
4. Forecasts, scenarios, Agent suggestions and experiments.

These states remain distinct:

```text
Observation → Fact → Inference → Decision → Execution → Settlement
```

`no_data`, `partial`, `stale`, `conflicted`, `blocked` and `unknown_outcome` are never represented as zero or success. Historical facts are immutable; correction creates a new event or adjustment with lineage.

## 3. Autonomy levels

| Level | Meaning | Default |
|---|---|---|
| `L0_OBSERVE` | read, parse, validate and report | enabled |
| `L1_ANALYZE` | calculate metrics, forecast and simulate | enabled |
| `L2_ORCHESTRATE` | create internal tasks and schedule bounded retries | enabled |
| `L3_POLICY_AUTOPILOT` | execute registered low-risk actions inside a standing policy | disabled until policy gate |
| `L4_CONTROLLED_EXECUTION` | marketplace, payment, procurement, pricing, advertising, refund or inventory side effects | disabled until exact Approval/Permit and runtime revalidation |

An Agent may select only an existing policy. It may not create or edit policies, limits, approval roles, kill switches, legal identity, payout destination, credentials or provider scopes.

## 4. Data and action contracts

Every read returns `DataEnvelope` from [KJDS_DATA_FABRIC_AND_TRANSPARENCY_CONTRACT.md](KJDS_DATA_FABRIC_AND_TRANSPARENCY_CONTRACT.md). Every side effect uses `ActionEnvelope` with an immutable input snapshot, exact scope, idempotency key, budget reservation, Permit, expected readback and rollback reference.

Agents and connectors never write repositories directly. They call domain/application services and registered query or command tools. A missing scope, evidence, freshness, budget, Permit, readback or rollback reference produces a candidate or a quarantine state, never an implicit write.

## 5. Unattended recovery

Recovery is selected from a versioned `RecoveryPolicy` registry:

```text
scope_key, failure_code, auto_action, max_attempts, retry_window,
spend_delta, permission_delta, requires_readback, escalation
```

Every recovery writes an append-only receipt containing before/after hashes, attempt number, actor, evidence, readback and rollback reference. At the limit, the exact tenant/entity/store/warehouse/SKU/source is quarantined. There is no unlimited retry and no `latest` overwrite after drift.

## 6. Product and commercial modes

The same contracts support:

```text
private single-seller deployment
design-partner read-only diagnostic
managed commerce service
modular SaaS after commercial gate
media and Agent Job API with KJDS usage credits
```

Skill, Connector, Auth Token, Usage Credit and model-token cost are separate objects. Customer access keys remain secrets; a Skill cannot grant a platform scope. Each tenant has isolated data, usage, billing, export and deletion boundaries.

## 7. Non-negotiable acceptance

The system must prove:

- every decision and metric can drill to source Evidence;
- the same input snapshot replays to the same result;
- duplicate or timed-out side effects never execute twice;
- late refunds and settlement revisions create traceable adjustments;
- stockout periods are not learned as zero demand;
- cross-tenant and cross-store reads are denied correctly;
- low-quality data cannot trigger price, ad, procurement, payment or inventory actions;
- a failed provider does not stop unrelated local analysis;
- export/import preserves rows, hashes and lineage;
- automation reports eligible volume, excluded volume and exclusion reasons.

## 8. Required implementation order

1. Add the data and metric contracts and registry validation.
2. Add read-only catalog, lineage, quality and drill-down projections.
3. Add period close, adjustment and replay services.
4. Add natural-language read-only analytics and scenario simulation.
5. Add internal task orchestration and recovery receipts.
6. Re-evaluate each external action through the existing `authorize_action` path before any policy activation.

This charter expands the description of routine unattended operation. It does not itself authorize external writes or change existing approval requirements.
