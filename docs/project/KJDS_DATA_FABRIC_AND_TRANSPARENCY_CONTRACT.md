# KJDS Data Fabric and Transparency Contract

| Field | Value |
|---|---|
| `doc_id` | `KJDS-DATA-FABRIC-TRANSPARENCY-001` |
| `status` | `PROPOSED_FOR_IMPLEMENTATION` |
| `owner` | data platform owner |
| `scope` | all KJDS data products, projections, APIs, Agents and exports |
| `external_write_allowed` | `false` |

## 1. Source layers

```text
raw_evidence → canonical_fact → ledger → projection/metric → decision/action
```

The raw layer is immutable and preserves bytes, source, capture time and hash. Canonical Facts are validated, scoped and versioned. Ledgers are append-only. Projections may be rebuilt. A projection cannot become a new source of truth.

Initial physical deployment may use PostgreSQL schemas and existing transactional outbox. New storage or queue dependencies require a separate ADR and measured benefit.

## 2. Canonical DataEnvelope

Every query and Agent input uses:

```json
{
  "dataset": "profit.cm3.v1",
  "scope": {"tenant_id":"t1","entity_id":"e1","store_ids":["s1"],"warehouse_ids":["w1"]},
  "as_of": "2026-09-06T00:00:00Z",
  "fresh_until": "2026-09-06T01:00:00Z",
  "status": "ready",
  "data": [],
  "quality": {"completeness":1.0,"freshness":"fresh","excluded_count":0,"reasons":[]},
  "lineage": [{"kind":"evidence","id":"ev-1","sha256":"..."}],
  "schema_version": "1.0",
  "authority_hash": "...",
  "next_cursor": null
}
```

Required statuses are `ready`, `partial`, `stale`, `conflicted`, `blocked`, `no_data` and `unknown_outcome`. Missing values are not zero. All APIs must preserve tenant, entity, store, warehouse, currency, timezone and `as_of` scope.

## 3. Event envelope

```text
event_id
event_type
aggregate_type
aggregate_id
tenant_id/entity_id/store_id/warehouse_id
occurred_at
captured_at
effective_from/effective_until
source_system/source_ref/source_hash
schema_version
causation_id/correlation_id
idempotency_key
authority
fact_level
```

Duplicate, out-of-order and late events are deduplicated, ordered or compensated. An old event is never edited to hide a correction.

## 4. Data product descriptor

Each dataset registers:

```text
dataset_id, version, owner, source_refs, grain, schema,
allowed_scopes, allowed_purposes, refresh_sla, watermark,
quality_threshold, retention_policy, rebuild_method, status
```

The descriptor is required before a metric, report, Agent or export can consume the data product.

## 5. Scope and access

Reads use RBAC plus ABAC:

```text
tenant + entity + store + warehouse + field + purpose + time + export
```

Services use least privilege. Sensitive buyer, bank and credential fields are masked by default. Agents can call registered query tools only; they never use direct SQL or repository access. Bulk exports, cross-store queries, break-glass access and deletion generate immutable audit records.

## 6. Quality and quarantine

Every dataset reports:

```text
freshness
completeness
validity
uniqueness
referential_integrity
cross_source_consistency
reconciliation
lineage_coverage
```

Quality failure records the affected scope and reason. It quarantines the smallest exact scope and prevents high-risk actions. Unrelated work continues when its evidence and authority remain valid.

## 7. Lineage and transparency

`LineageEdge` references existing Evidence, Fact, Decision and Action IDs; it must not recursively scan arbitrary JSON. Every metric and decision displays:

```text
source records
source hashes
calculation formula and version
as_of/fresh_until
included and excluded rows
quality state
policy/model/skill versions
```

The UI provides `global → store → warehouse → category → SKU → order/fee → raw evidence` drill-down and a time slider for event time, capture time and current recomputation.

## 8. Import, export and replay

Import is:

```text
preserve original → map fields → preview → quality report
→ quarantine error rows → commit → verify → rollback if required
```

Export includes schema, scope, time, source watermarks, evidence references and checksums. A replay uses the same snapshot, metric version and rule version. A correction creates an adjustment event and a new result hash.

## 9. Action boundary

```text
DataEnvelope = read and explain
ActionEnvelope = propose or execute an authorized command
```

Data availability never implies write authority. An ActionEnvelope requires exact scope, input snapshot, policy, budget reservation, Permit, idempotency, expected readback and rollback reference.

## 10. Acceptance

The contract is accepted only when tests demonstrate scoped denial, event replay equality, no duplicate side effects, late-data adjustment, import/export hash equality, projection rebuild equality, evidence drill-down, and zero cross-tenant leakage.
